# This file is part of the Maker Keeper Framework.
#
# Copyright (C) 2019-2021 EdNoepel, KentonPrescott
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import List

from web3 import Web3

from pymaker import Address, web3_via_http
from pymaker.auctions import Clipper, Flipper
from pymaker.deployment import Collateral, DssDeployment
from pymaker.dss import Ilk, Urn
from pymaker.gas import DefaultGasPrice
from pymaker.keys import register_keys
from pymaker.lifecycle import Lifecycle
from pymaker.numeric import Wad, Rad, Ray

from auction_keeper.urn_history import ChainUrnHistoryProvider
from auction_keeper.urn_history_vulcanize import VulcanizeUrnHistoryProvider
from auction_keeper.gas import DynamicGasPrice


class CageKeeper:
    """Keeper to facilitate Emergency Shutdown"""

    logger = logging.getLogger('cage-keeper')

    def __init__(self, args: list, **kwargs):
        """Pass in arguements assign necessary variables/objects and instantiate other Classes"""

        parser = argparse.ArgumentParser("cage-keeper")

        parser.add_argument("--rpc-host", type=str, default="https://localhost:8545",
                            help="JSON-RPC host:port (default: 'localhost:8545')")

        parser.add_argument("--rpc-timeout", type=int, default=60,
                            help="JSON-RPC timeout (in seconds, default: 60)")

        parser.add_argument('--previous-cage', dest='cageFacilitated', action='store_true',
                            help='Include this argument if this keeper previously started the processing phase of ES')

        parser.add_argument("--eth-from", type=str, required=True,
                            help="Ethereum address from which to send transactions; checksummed (e.g. '0x12AebC')")

        parser.add_argument("--eth-key", type=str, nargs='*',
                            help="Ethereum private key(s) to use (e.g. 'key_file=/path/to/keystore.json,pass_file=/path/to/passphrase.txt')")

        parser.add_argument("--psm", type=str, default="",
                            help="When provided, PSM will be flowed along with other collaterals")

        parser.add_argument("--dss-deployment-file", type=str, required=False,
                            help="Json description of all the system addresses (e.g. /Full/Path/To/configFile.json)")

        parser.add_argument("--vat-deployment-block", type=int, required=False, default=0,
                            help="Block that the Vat from dss-deployment-file was deployed at (e.g. 8836668")

        parser.add_argument("--vulcanize-endpoint", type=str,
                            help="When specified, urn history will be queried from Vulcanize, conserving resources")
        parser.add_argument("--vulcanize-key", type=str,
                            help="API key for the Vulcanize endpoint")

        parser.add_argument("--debug", dest='debug', action='store_true',
                            help="Enable debug output")

        parser.add_argument("--ethgasstation-api-key", type=str, default=None, help="ethgasstation API key")

        parser.add_argument("--gas-initial-multiplier", type=str, default=1.0, help="ethgasstation API key")
        parser.add_argument("--gas-reactive-multiplier", type=str, default=2.25, help="gas strategy tuning")
        parser.add_argument("--gas-maximum", type=str, default=5000, help="gas strategy tuning")

        parser.set_defaults(cageFacilitated=False)
        self.arguments = parser.parse_args(args)

        self.web3: Web3 = kwargs['web3'] if 'web3' in kwargs else web3_via_http(
            endpoint_uri=self.arguments.rpc_host, timeout=self.arguments.rpc_timeout, http_pool_size=100)

        self.web3.eth.defaultAccount = self.arguments.eth_from
        register_keys(self.web3, self.arguments.eth_key)
        self.our_address = Address(self.arguments.eth_from)

        if self.arguments.dss_deployment_file:
            self.dss = DssDeployment.from_json(web3=self.web3, conf=open(self.arguments.dss_deployment_file, "r").read())
        else:
            self.dss = DssDeployment.from_node(web3=self.web3)

        self.deployment_block = self.arguments.vat_deployment_block
        self.complete = False
        self.cageFacilitated = self.arguments.cageFacilitated
        self.confirmations = 0

        # Create gas strategy
        if self.arguments.ethgasstation_api_key:
            self.gas_price = DynamicGasPrice(self.arguments, self.web3)
        else:
            self.gas_price = DefaultGasPrice()

        self.lifecycle = None
        logging.basicConfig(format='%(asctime)-15s %(levelname)-8s %(message)s',
                            level=(logging.DEBUG if self.arguments.debug else logging.INFO))

    def main(self):
        """ Initialize the lifecycle and enter into the Keeper Lifecycle controller

        Each function supplied by the lifecycle will accept a callback function that will be executed.
        The lifecycle.on_block() function will enter into an infinite loop, but will gracefully shutdown
        if it recieves a SIGINT/SIGTERM signal.

        """
        with Lifecycle(self.web3) as lifecycle:
            self.lifecycle = lifecycle
            lifecycle.on_startup(self.check_deployment)
            lifecycle.on_block(self.process_block)

    def check_deployment(self):
        self.logger.info('')
        self.logger.info('Please confirm the deployment details')
        self.logger.info(f'Keeper Balance: {self.web3.eth.getBalance(self.our_address.address) / (10**18)} ETH')
        self.logger.info(f'Vat: {self.dss.vat.address}')
        self.logger.info(f'Vow: {self.dss.vow.address}')
        self.logger.info(f'Flapper: {self.dss.flapper.address}')
        self.logger.info(f'Flopper: {self.dss.flopper.address}')
        self.logger.info(f'Jug: {self.dss.jug.address}')
        self.logger.info(f'End: {self.dss.end.address}')
        self.logger.info('')

    def process_block(self):
        """Callback called on each new block."""
        if self.complete:
            self.lifecycle.terminate()
        else:
            self.check_cage()

    def check_cage(self):
        """ After live is 0 for 12 block confirmations, facilitate the processing period, then thaw the cage """
        blockNumber = self.web3.eth.blockNumber
        self.logger.info(f'Checking Cage on block {blockNumber}')

        live = self.dss.end.live()

        # Ensure 12 blocks confirmations have passed before facilitating cage
        if not live and (self.confirmations == 12):
            self.logger.info('======== System has been caged ========')

            when = self.dss.end.when()
            wait = self.dss.end.wait()
            whenInUnix = when.replace(tzinfo=timezone.utc).timestamp()
            now = self.web3.eth.getBlock(blockNumber).timestamp
            thawedCage = whenInUnix + wait

            if not self.cageFacilitated:
                self.cageFacilitated = True
                self.facilitate_processing_period()

            # wait until processing time concludes
            elif now >= thawedCage:
                self.thaw_cage()
                joined_mkr = self.dss.esm.sum()
                if joined_mkr > Wad(0):
                    self.logger.info('')
                    self.logger.info(f'======== Burning {float(joined_mkr)} deposited MKR ========')
                    self.logger.info('')
                    self.dss.esm.burn().transact(gas_price=self.gas_price)
                self.logger.info('')
                self.logger.info('======== Completed emergency shutdown ========')
                self.logger.info('')
                self.complete = True

            else:
                whenThawedCage = datetime.utcfromtimestamp(thawedCage)
                self.logger.info('')
                self.logger.info(f'Cage has been processed and will be thawed on {whenThawedCage.strftime("%m/%d/%Y, %H:%M:%S")} UTC')
                self.logger.info('')

        elif not live and self.confirmations < 13:
            self.confirmations = self.confirmations + 1
            self.logger.info(f'======== System has been caged ({self.confirmations} confirmations) ========')

    def facilitate_processing_period(self):
        """ Yank active flap/flop auctions, cage ilks, snip clip auctions, skip flip auctions, skim underwater urns """
        self.logger.info('')
        self.logger.info('======== Facilitating Cage ========')
        self.logger.info('')

        # check ilks
        ilks = list(map(lambda l: l.ilk, self.get_collaterals()))

        # Get all auctions that can be yanked after cage
        auctions = self.all_active_auctions()

        # Yank all flap and flop auctions
        self.yank_auctions(auctions["flaps"], auctions["flops"])

        # Cage all ilks
        for ilk in ilks:
            assert self.dss.end.cage(ilk).transact(gas_price=self.gas_price)

        # Snip all clip auctions
        for key in auctions["clips"].keys():
            ilk = self.dss.vat.ilk(key)
            for bid in auctions["clips"][key]:
                self.dss.end.snip(ilk, bid.id).transact(gas_price=self.gas_price)

        # Skip all flip auctions
        for key in auctions["flips"].keys():
            ilk = self.dss.vat.ilk(key)
            for bid in auctions["flips"][key]:
                self.dss.end.skip(ilk, bid.id).transact(gas_price=self.gas_price)

        # Cancel vault debt, confiscating backing collateral
        self.skim_urns(ilks, undercollateralized_only=True)

    def reconcile_debt(self):
        joy = self.dss.vat.dai(self.dss.vow.address)
        ash = self.dss.vow.ash()
        woe = self.dss.vow.woe()

        if ash > Rad(0):
            if joy > ash:
                self.dss.vow.kiss(ash).transact(gas_price=self.gas_price)
            else:
                self.dss.vow.kiss(joy).transact(gas_price=self.gas_price)
                return
        if woe > Rad(0):
            joy = self.dss.vat.dai(self.dss.vow.address)
            if joy > woe:
                self.dss.vow.heal(woe).transact(gas_price=self.gas_price)
            else:
                self.dss.vow.heal(joy).transact(gas_price=self.gas_price)

    def skim_urns(self, ilks: List, undercollateralized_only: bool):
        """ Skim each urn to cancel debt """

        for ilk in ilks:
            if self.arguments.vulcanize_endpoint:
                urn_history = VulcanizeUrnHistoryProvider(self.web3, self.dss, ilk,
                                                          self.arguments.vulcanize_endpoint,
                                                          self.arguments.vulcanize_key)
            else:
                urn_history = ChainUrnHistoryProvider(self.web3, self.dss, ilk, self.deployment_block)
            urns = urn_history.get_urns()
            self.logger.info(f'Collected {len(urns)} urns from {ilk}')

            for count, urn in enumerate(urns.values()):
                # ignore vaults with no debt
                if urn.art == Wad(0):
                    continue
                # while facilitating the processing period, only underwater vaults will be confiscated
                if undercollateralized_only:
                    mat = self.dss.spotter.mat(urn.ilk)
                    usd_debt = Ray(urn.art) * urn.ilk.rate
                    usd_collateral = Ray(urn.ink) * urn.ilk.spot * mat
                    # Check if underwater ->  urn.art * ilk.rate > urn.ink * ilk.spot * spotter.mat[ilk]
                    if usd_debt < usd_collateral:
                        continue

                self.dss.end.skim(urn.ilk, urn.address).transact(gas_price=self.gas_price)
                if count % 50 == 0:
                    self.logger.info(f'Submitted skim transactions for {count} of {len(urns)} {ilk.name} urns')
                    # after the processing period, check whether we've skimmed enough to cover the surplus
                    if not undercollateralized_only:
                        self.reconcile_debt()
                        if self.dss.vat.dai(self.dss.vow.address) == Rad(0):
                            self.logger.info(f'Enough urns were skimmed to eliminate surplus')
                            break

    def thaw_cage(self):
        """ Once End.wait is reached, annihilate any lingering Dai in the vow, thaw the cage, and set the fix for all ilks  """
        self.logger.info('')
        self.logger.info('======== Thawing Cage ========')
        self.logger.info('')

        collaterals = self.get_collaterals()

        # Reconcile surplus and debt to reduce joy, skim as necessary until surplus is eliminated
        self.reconcile_debt()
        if self.dss.vat.dai(self.dss.vow.address) > Rad(0):
            ilks = list(map(lambda l: l.ilk, self.get_collaterals()))
            self.skim_urns(ilks, undercollateralized_only=False)

        # Call thaw and Fix outstanding supply of Dai
        assert self.dss.end.thaw().transact(gas_price=self.gas_price)

        # Set fix (collateral/Dai ratio) for all Ilks
        for collateral in collaterals:
            self.dss.end.flow(collateral.ilk).transact(gas_price=self.gas_price)
            if collateral.clipper:
                self.dss.esm.deny(collateral.clipper.address).transact(gas_price=self.gas_price)
            if collateral.flipper:
                self.dss.esm.deny(collateral.flipper.address).transact(gas_price=self.gas_price)

        # Flow the PSM if configured to do so
        if self.arguments.psm:
            self.dss.end.flow(Ilk("PSM-USDC-A")).transact(gas_price=self.gas_price)
            self.dss.esm.deny(Address(self.arguments.psm)).transact(gas_price=self.gas_price)

    def get_collaterals(self) -> List[Collateral]:
        """ Use Ilks as saved in https://github.com/makerdao/pymaker/tree/master/config """

        collaterals_filtered = filter(lambda l: l.ilk.name != 'SAI', self.dss.collaterals.values())
        collaterals_with_debt = list(filter(lambda l: self.dss.vat.ilk(l.ilk.name).art > Wad(0), collaterals_filtered))

        self.logger.info(f'Collaterals to check: {[c.ilk.name for c in collaterals_with_debt]}')
        return collaterals_with_debt

    def all_active_auctions(self) -> dict:
        """ Aggregates active auctions that meet criteria to be called after Cage """
        clips = {}
        flips = {}
        for collateral in self.dss.collaterals.values():
            # Each collateral has it's own contract; add auctions from each.
            if collateral.clipper:
                clips[collateral.ilk.name] = self.cage_active_auctions(collateral.clipper)
            elif collateral.flipper:
                flips[collateral.ilk.name] = self.cage_active_auctions(collateral.flipper)

        return {
            "clips": clips,
            "flips": flips,
            "flaps": self.cage_active_auctions(self.dss.flapper),
            "flops": self.cage_active_auctions(self.dss.flopper)
        }

    def cage_active_auctions(self, parentObj) -> List:
        """ Returns auctions that meet the requiremenets to be called by End.skip, Flap.yank, and Flop.yank """
        active_auctions = []
        auction_count = parentObj.kicks()+1

        # clip auctions
        if isinstance(parentObj, Clipper):
            active_auctions = parentObj.active_auctions()

        # flip auctions
        elif isinstance(parentObj, Flipper):
            for index in range(1, auction_count):
                bid = parentObj._bids(index)
                if bid.guy != Address("0x0000000000000000000000000000000000000000"):
                    if bid.bid < bid.tab:
                        active_auctions.append(bid)
                index += 1

        # flap and flop auctions
        else:
            for index in range(1, auction_count):
                bid = parentObj._bids(index)
                if bid.guy != Address("0x0000000000000000000000000000000000000000"):
                    active_auctions.append(bid)
                index += 1
        return active_auctions

    def yank_auctions(self, flapBids: List, flopBids: List):
        """ Calls Flap.yank and Flop.yank on all auctions ids that meet the cage criteria """
        for bid in flapBids:
            self.dss.flapper.yank(bid.id).transact(gas_price=self.gas_price)

        for bid in flopBids:
            self.dss.flopper.yank(bid.id).transact(gas_price=self.gas_price)


if __name__ == '__main__':
    CageKeeper(sys.argv[1:]).main()

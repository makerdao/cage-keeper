# This file is part of the Maker Keeper Framework.
#
# Copyright (C) 2019 EdNoepel, KentonPrescott
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
import time
from datetime import datetime, timezone
import types
from os import path
from typing import List

from web3 import Web3, HTTPProvider

from pymaker import Address
from pymaker.gas import DefaultGasPrice, FixedGasPrice
from pymaker.auctions import Flipper, Flapper, Flopper
from pymaker.keys import register_keys
from pymaker.lifecycle import Lifecycle
from pymaker.numeric import Wad, Rad, Ray
from pymaker.token import ERC20Token
from pymaker.deployment import DssDeployment
from pymaker.dss import Ilk, Urn

from auction_keeper.urn_history import UrnHistory
from auction_keeper.gas import DynamicGasPrice

class CageKeeper:
    """Keeper to facilitate Emergency Shutdown"""

    logger = logging.getLogger('cage-keeper')

    def __init__(self, args: list, **kwargs):
        """Pass in arguements assign necessary variables/objects and instantiate other Classes"""

        parser = argparse.ArgumentParser("cage-keeper")

        parser.add_argument("--rpc-host", type=str, default="localhost",
                            help="JSON-RPC host (default: `localhost')")

        parser.add_argument("--rpc-port", type=int, default=8545,
                            help="JSON-RPC port (default: `8545')")

        parser.add_argument("--rpc-timeout", type=int, default=1200,
                            help="JSON-RPC timeout (in seconds, default: 10)")

        parser.add_argument("--network", type=str, required=True,
                            help="Network that you're running the Keeper on (options, 'mainnet', 'kovan', 'testnet')")

        parser.add_argument('--previous-cage', dest='cageFacilitated', action='store_true',
                            help='Include this argument if this keeper previously helped to facilitate the processing phase of ES')

        parser.add_argument("--eth-from", type=str, required=True,
                            help="Ethereum address from which to send transactions; checksummed (e.g. '0x12AebC')")

        parser.add_argument("--eth-key", type=str, nargs='*',
                            help="Ethereum private key(s) to use (e.g. 'key_file=/path/to/keystore.json,pass_file=/path/to/passphrase.txt')")

        parser.add_argument("--dss-deployment-file", type=str, required=False,
                            help="Json description of all the system addresses (e.g. /Full/Path/To/configFile.json)")

        parser.add_argument("--vat-deployment-block", type=int, required=False, default=0,
                            help=" Block that the Vat from dss-deployment-file was deployed at (e.g. 8836668")

        parser.add_argument("--vulcanize-endpoint", type=str,
                            help="When specified, frob history will be queried from a VulcanizeDB lite node, "
                                 "reducing load on the Ethereum node for Vault query")

        parser.add_argument("--vulcanize-key", type=str,
                            help="API key for the Vulcanize endpoint")

        parser.add_argument("--max-errors", type=int, default=100,
                            help="Maximum number of allowed errors before the keeper terminates (default: 100)")

        parser.add_argument("--debug", dest='debug', action='store_true',
                            help="Enable debug output")

        parser.add_argument("--ethgasstation-api-key", type=str, default=None, help="ethgasstation API key")

        parser.add_argument("--gas-initial-multiplier", type=str, default=1.0, help="ethgasstation API key")
        parser.add_argument("--gas-reactive-multiplier", type=str, default=2.25, help="gas strategy tuning")
        parser.add_argument("--gas-maximum", type=str, default=5000, help="gas strategy tuning")



        parser.set_defaults(cageFacilitated=False)
        self.arguments = parser.parse_args(args)

        self.web3 = kwargs['web3'] if 'web3' in kwargs else Web3(HTTPProvider(endpoint_uri=f"https://{self.arguments.rpc_host}:{self.arguments.rpc_port}",
                                                                              request_kwargs={"timeout": self.arguments.rpc_timeout}))
        self.web3.eth.defaultAccount = self.arguments.eth_from
        register_keys(self.web3, self.arguments.eth_key)
        self.our_address = Address(self.arguments.eth_from)

        if self.arguments.dss_deployment_file:
            self.dss = DssDeployment.from_json(web3=self.web3, conf=open(self.arguments.dss_deployment_file, "r").read())
        else:
            self.dss = DssDeployment.from_network(web3=self.web3, network=self.arguments.network)

        self.deployment_block = self.arguments.vat_deployment_block

        self.max_errors = self.arguments.max_errors
        self.errors = 0

        self.cageFacilitated = self.arguments.cageFacilitated

        self.confirmations = 0

        # Create gas strategy
        if self.arguments.ethgasstation_api_key:
            self.gas_price = DynamicGasPrice(self.arguments, self.web3)
        else:
            self.gas_price = DefaultGasPrice()


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
        """Callback called on each new block. If too many errors, terminate the keeper to minimize potential damage."""
        if self.errors >= self.max_errors:
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
            elif (now >= thawedCage):
                self.thaw_cage()

                if not (self.arguments.network == 'testnet'):
                    self.lifecycle.terminate()

            else:
                whenThawedCage = datetime.utcfromtimestamp(thawedCage)
                self.logger.info('')
                self.logger.info(f'Cage has been processed and will be thawed on {whenThawedCage.strftime("%m/%d/%Y, %H:%M:%S")} UTC')
                self.logger.info('')

        elif not live and self.confirmations < 13:
            self.confirmations = self.confirmations + 1
            self.logger.info(f'======== System has been caged ( {self.confirmations} confirmations) ========')


    def facilitate_processing_period(self):
        """ Yank all active flap/flop auctions, cage all ilks, skip all flip auctions, skim all underwater urns  """
        self.logger.info('')
        self.logger.info('======== Facilitating Cage ========')
        self.logger.info('')

        # check ilks
        ilks = self.get_ilks()

        # Get all auctions that can be yanked after cage
        auctions = self.all_active_auctions()

        # Yank all flap and flop auctions
        self.yank_auctions(auctions["flaps"], auctions["flops"])

        # Cage all ilks
        for ilk in ilks:
            self.dss.end.cage(ilk).transact(gas_price=self.gas_price)

        # Skip all flip auctions
        for key in auctions["flips"].keys():
            ilk = self.dss.vat.ilk(key)
            for bid in auctions["flips"][key]:
                self.dss.end.skip(ilk,bid.id).transact(gas_price=self.gas_price)

        #get all underwater urns
        urns = self.get_underwater_urns(ilks)

        #skim all underwater urns
        for i in urns:
            self.dss.end.skim(i.ilk, i.address).transact(gas_price=self.gas_price)


    def thaw_cage(self):
        """ Once End.wait is reached, annihilate any lingering Dai in the vow, thaw the cage, and set the fix for all ilks  """
        self.logger.info('')
        self.logger.info('======== Thawing Cage ========')
        self.logger.info('')

        ilks = self.get_ilks()

        # check if Dai is in Vow and annialate it with Heal()
        dai = self.dss.vat.dai(self.dss.vow.address)
        if dai > Rad(0):
            self.dss.vow.heal(dai).transact(gas_price=self.gas_price)

        # Call thaw and Fix outstanding supply of Dai
        self.dss.end.thaw().transact(gas_price=self.gas_price)

        # Set fix (collateral/Dai ratio) for all Ilks
        for ilk in ilks:
            self.dss.end.flow(ilk).transact(gas_price=self.gas_price)


    def get_ilks(self) -> List[Ilk]:
        """ Use Ilks as saved in https://github.com/makerdao/pymaker/tree/master/config """

        ilks = [self.dss.collaterals[key].ilk for key in self.dss.collaterals.keys()]
        ilksFiltered = list(filter(lambda l: l.name != 'SAI', ilks))
        ilks_with_debt = list(filter(lambda l: self.dss.vat.ilk(l.name).art > Wad(0), ilksFiltered))

        ilkNames = [i.name for i in ilks_with_debt]

        self.logger.info(f'Ilks to check: {ilkNames}')

        return ilks_with_debt


    def get_underwater_urns(self, ilks: List) -> List[Urn]:
        """ With all urns every frobbed, compile and return a list urns that are under-collateralized up to 100%  """

        underwater_urns = []

        for ilk in ilks:

            urn_history = UrnHistory(self.web3,
                                     self.dss,
                                     ilk,
                                     self.deployment_block,
                                     self.arguments.vulcanize_endpoint,
                                     self.arguments.vulcanize_key)

            urns = urn_history.get_urns()

            self.logger.info(f'Collected {len(urns)} from {ilk}')

            i = 0
            for urn in urns.values():
                urn.ilk = self.dss.vat.ilk(urn.ilk.name)
                mat = self.dss.spotter.mat(urn.ilk)
                usdDebt = Ray(urn.art) * urn.ilk.rate
                usdCollateral = Ray(urn.ink) * urn.ilk.spot * mat
                # Check if underwater ->  urn.art * ilk.rate > urn.ink * ilk.spot * spotter.mat[ilk]
                if usdDebt > usdCollateral:
                    underwater_urns.append(urn)
                i += 1;

                if i % 100 == 0:
                    self.logger.info(f'Processed {i} urns of {ilk.name}')

        return underwater_urns


    def all_active_auctions(self) -> dict:
        """ Aggregates active auctions that meet criteria to be called after Cage """
        flips = {}
        for collateral in self.dss.collaterals.values():
            # Each collateral has it's own flip contract; add auctions from each.
            flips[collateral.ilk.name] = self.cage_active_auctions(collateral.flipper)

        return {
            "flips": flips,
            "flaps": self.cage_active_auctions(self.dss.flapper),
            "flops": self.cage_active_auctions(self.dss.flopper)
        }


    def cage_active_auctions(self, parentObj) -> List:
        """ Returns auctions that meet the requiremenets to be called by End.skip, Flap.yank, and Flop.yank """
        active_auctions = []
        auction_count = parentObj.kicks()+1

        # flip auctions
        if isinstance(parentObj, Flipper):
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

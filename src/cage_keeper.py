# This file is part of the Maker Keeper Framework.
#
# Copyright (C) 2018-2019 reverendus, kentonprescott
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
import types
from os import path
from typing import List


from web3 import Web3, HTTPProvider


from pymaker import Address
from pymaker.gas import DefaultGasPrice, FixedGasPrice
from pymaker.auctions import Flipper, Flapper, Flopper
from pymaker.keys import register_keys
from pymaker.lifecycle import Lifecycle
from pymaker.numeric import Wad, Rad
from pymaker.token import ERC20Token
from pymaker.deployment import DssDeployment
from pymaker.dss import Ilk

class CageKeeper:
    """Keeper to facilitate Emergency Shutdown"""

    logger = logging.getLogger('cage-keeper')

    def __init__(self, args: list, **kwargs):
        """Pass in arguements assign necessary variables/objects and instantiate other Classes"""

        parser = argparse.ArgumentParser("simple-arbitrage-keeper")

        parser.add_argument("--rpc-host", type=str, default="localhost",
                            help="JSON-RPC host (default: `localhost')")

        parser.add_argument("--rpc-port", type=int, default=8545,
                            help="JSON-RPC port (default: `8545')")

        parser.add_argument("--rpc-timeout", type=int, default=10,
                            help="JSON-RPC timeout (in seconds, default: 10)")

        parser.add_argument("--network", type=str, required=True,
                            help="Network that you're running the Keeper on (options, 'mainnet', 'kovan', 'testnet')")

        parser.add_argument("--eth-from", type=str, required=True,
                            help="Ethereum address from which to send transactions; checksummed (e.g. '0x12AebC')")

        parser.add_argument("--eth-key", type=str, nargs='*',
                            help="Ethereum private key(s) to use (e.g. 'key_file=/path/to/keystore.json,pass_file=/path/to/passphrase.txt')")

        parser.add_argument("--dss-deployment-file", type=str, required=False,
                            help="Json description of all the system addresses (e.g. /Full/Path/To/configFile.json)")

        parser.add_argument("--vat-deployment-block", type=int, required=False, default=0,
                            help=" Block that the Vat from dss-deployment-file was deployed at (e.g. 8836668")

        parser.add_argument("--max-errors", type=int, default=100,
                            help="Maximum number of allowed errors before the keeper terminates (default: 100)")

        parser.add_argument("--debug", dest='debug', action='store_true',
                            help="Enable debug output")

        self.arguments = parser.parse_args(args)

        self.web3 = kwargs['web3'] if 'web3' in kwargs else Web3(HTTPProvider(endpoint_uri=f"https://{self.arguments.rpc_host}:{self.arguments.rpc_port}",
                                                                              request_kwargs={"timeout": self.arguments.rpc_timeout}))
        self.web3.eth.defaultAccount = self.arguments.eth_from
        register_keys(self.web3, self.arguments.eth_key)
        self.our_address = Address(self.arguments.eth_from)

        basepath = path.dirname(__file__)
        filepath = path.abspath(path.join(basepath, "..", "lib", "pymaker", "config", self.arguments.network+"-addresses.json"))
        pymaker_deployment_config = filepath

        if self.arguments.dss_deployment_file:
            self.dss = DssDeployment.from_json(web3=self.web3, conf=open(self.arguments.dss_deployment_file, "r").read())
        else:
            self.dss = DssDeployment.from_network(web3=self.web3, network=self.arguments.network)

        self.deployment_block = self.arguments.vat_deployment_block

        self.max_errors = self.arguments.max_errors
        self.errors = 0

        self.cage_actions = False


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
            lifecycle.on_startup(self.checkDeployment)
            lifecycle.on_block(self.process_block)


    def checkDeployment(self):
        self.logger.info('')
        self.logger.info('Please confirm the deployment details')
        self.logger.info(f'Keeper Balance: {self.web3.eth.getBalance(self.our_address.address) / (10**18)} ETH')
        self.logger.info(f'Vat: {self.dss.vat.address}')
        self.logger.info(f'Vow: {self.dss.vow.address}')
        self.logger.info(f'Flapper: {self.dss.flapper.address}')
        self.logger.info(f'Flopper: {self.dss.flopper.address}')
        self.logger.info(f'Jug: {self.dss.jug.address}')
        self.logger.info('')



    def process_block(self):
        """Callback called on each new block. If too many errors, terminate the keeper to minimize potential damage."""
        if self.errors >= self.max_errors:
            self.lifecycle.terminate()
        else:
            self.check_cage()




    def check_cage(self):
        self.logger.info(f'Checking Cage on block {self.web3.eth.blockNumber}')

        live = self.dss.end.live()

        if not live and not self.cage_actions:
            # time.sleep(180) # 12 block confirmation
            time.sleep(1) # TODO: Remove after testing on testnet

            if not live:
                self.cage_auctions = True # so that self.facilitate_cage() won't be called again
                self.facilitate_cage()



    def facilitate_cage(self):
        self.logger.info('Facilitating Cage')

        # Get End.wait in seconds (processing time)
        wait = self.dss.end.wait()

        # check ilks
        ilks = self.check_ilks()

        # Drip all ilks
        for ilk in ilks:
            self.dss.jug.drip(ilk).transact(gas_price=self.gas_price())

        # Get all auctions that can be yanked after cage
        auctions = self.all_active_auctions()

        # TODO, see if bid ids can be exposed on Bid object in pymaker
        # Yank all flap and flop auctions
        self.yank_auctions(auctions["flaps"], auctions["flops"])

        # Cage all ilks
        for ilk in ilks:
            self.dss.end.cage(ilk).transact(gas_price=self.gas_price())

        # Skip all flip auctions
        for key in auctions["flips"].keys():
            ilk = self.dss.vat.ilk(key)
            for bid in auctions["flips"][key]:
                self.dss.end.skip(ilk,bid.id).transact(gas_price=self.gas_price())

        #get all underwater urns
        urns = self.get_underwater_urns()

        #skim all underwater urns
        for i in urns:
            self.dss.end.skim(i.ilk, i.address).transact(gas_price=self.gas_price())

        # wait until processing time concludes
        print(wait)
        time.sleep(wait)

        # check if Dai is in Vow and annialate it with Heal()
        dai = self.dss.vat.dai(self.dss.vow.address)
        if dai > Rad(0):
            self.dss.vow.heal(dai).transact(gas_price=self.gas_price())

        # Call thaw and Fix outstanding supply of Dai
        self.dss.end.thaw().transact(gas_price=self.gas_price())

        # Set fix (collateral/Dai ratio) for all Ilks
        for ilk in ilks:
            self.dss.end.flow(ilk).transact(gas_price=self.gas_price())




    def get_ilks(self):
        """ From the block of Vat contract deployment, check which ilks have been frobbed  """
        current_blockNumber = self.web3.eth.blockNumber
        blocks = current_blockNumber - self.deployment_block

        frobs = self.dss.vat.past_frobs(blocks)
        ilkNames = list(dict.fromkeys([i.ilk for i in frobs]))
        ilks = [self.dss.vat.ilk(i) for i in ilkNames]

        return ilks



    def check_ilks(self):

        ilks = self.get_ilks()
        ilkNames = [i.name for i in ilks]

        deploymentIlks = [self.dss.collaterals[key].ilk for key in self.dss.collaterals.keys()]
        deploymentIlkNames = [i.name for i in deploymentIlks]

        if set(ilkNames) != set(deploymentIlkNames):
            self.logger.info('======== WARNING, Discrepancy in frobbed ilks and collaterals in deployment file ========')
            self.logger.info(f'Frobbed ilks: {ilkNames}')
            self.logger.info(f'Deployment ilks: {deploymentIlkNames}')
            self.logger.info('=========================== Will continue with deployment ilks ==========================')

        return deploymentIlks



    def get_underwater_urns(self):

        urns = self.dss.vat.urns(from_block=self.deployment_block)

        # Check if underwater, or  urn.art * ilk.rate > urn.ink * ilk.spot
        underwater_urns = []

        for ilk in urns.keys():
            for urn in urns[ilk].keys():
                urns[ilk][urn].ilk = self.dss.vat.ilk(urns[ilk][urn].ilk.name)
                if urns[ilk][urn].art * urns[ilk][urn].ilk.rate > urns[ilk][urn].ink * urns[ilk][urn].ilk.spot:
                    underwater_urns.append(urns[ilk][urn])

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


    def cage_active_auctions(self, parentObj) -> list:
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
            self.dss.flapper.yank(bid.id).transact(gas_price=self.gas_price())

        for bid in flopBids:
            self.dss.flopper.yank(bid.id).transact(gas_price=self.gas_price())



    def gas_price(self):
        """  DefaultGasPrice """
        return DefaultGasPrice()


if __name__ == '__main__':
    CageKeeper(sys.argv[1:]).main()

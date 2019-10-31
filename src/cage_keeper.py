# This file is part of the Maker Keeper Framework.
#
# Copyright (C) _______
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
from os import path

from web3 import Web3, HTTPProvider


from pymaker import Address
from pymaker.gas import DefaultGasPrice, FixedGasPrice
from pymaker.keys import register_keys
from pymaker.lifecycle import Lifecycle
from pymaker.numeric import Wad
from pymaker.token import ERC20Token
from pymaker.deployment import DssDeployment

class CageKeeper:
    """Keeper to facilitate Emergency Shutdown"""

    logger = logging.getLogger('simple-arbitrage-keeper')

    def __init__(self, args, **kwargs):
        """Pass in arguements assign necessary variables/objects and instantiate other Classes"""

        parser = argparse.ArgumentParser("simple-arbitrage-keeper")

        parser.add_argument("--rpc-host", type=str, default="localhost",
                            help="JSON-RPC host (default: `localhost')")

        parser.add_argument("--rpc-port", type=int, default=8545,
                            help="JSON-RPC port (default: `8545')")

        parser.add_argument("--rpc-timeout", type=int, default=10,
                            help="JSON-RPC timeout (in seconds, default: 10)")

        parser.add_argument("--network", type=str, default="kovan",
                            help="Network that you're running the Keeper on (options, 'mainnet', 'kovan', 'testnet')")

        parser.add_argument("--eth-from", type=str, required=True,
                            help="Ethereum address from which to send transactions; checksummed (e.g. '0x12AebC')")

        parser.add_argument("--eth-key", type=str, nargs='*', required=True,
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
            self.dss = DssDeployment.from_json(web3=self.web3, conf=open(pymaker_deployment_config, "r").read())
            
        self.deployment_block = self.arguments.vat_deployment_block

        self.max_errors = self.arguments.max_errors
        self.errors = 0


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

        #self.facilitate_cage()
        #if cage has been called in End.sol:
            #self.facilitate_cage()



    def facilitate_cage(self):
        self.logger.info('Facilitating Cage')

        # Tentative Structure
        # Ilks = get_ilks( )
        # drip_ilks(Ilks)
        # flopIds = get_flopIds( )
        # flapIds = get_flapIds( )
        # flipIds = get_flipIds(ilk)
        # yank_auctions(flopIds, flapIds)
        # cage_ilks(ilks)
        # skip_flip_auctions(Ilks, flipIds)
        # Underwater_urns = get_underwater_urns(ilks)
        # skim_urns(ilks, underwater_urns)

        ilks = self.get_ilks()

        for ilk in ilks:
            self.dss.jug.drip(ilk).transact(gas_price=self.gas_price())

        self.logger.info('Done Dripping')

        flopIds = self.dss.flopper.active_auctions()
        flapIds = self.dss.flapper.active_auctions()




        # collateral = Collateral(ilk=ilk, gem=gem,
        #                                 adapter=GemJoin(web3, Address(conf[f'MCD_JOIN_{name[0]}'])),
        #                                 flipper=Flipper(web3, Address(conf[f'MCD_FLIP_{name[0]}'])),
        #                                 pip=DSValue(web3, Address(conf[f'PIP_{name[1]}'])))




    def get_ilks(self):
        current_blockNumber = self.web3.eth.blockNumber
        blocks = current_blockNumber - self.deployment_block

        frobs = self.dss.vat.past_frob(blocks)
        ilkNames = list(dict.fromkeys([i.ilk for i in frobs]))
        ilks = [self.dss.vat.ilk(i) for i in ilkNames]

        return ilks





    def gas_price(self):
        """  DefaultGasPrice """
        return DefaultGasPrice()


if __name__ == '__main__':
    CageKeeper(sys.argv[1:]).main()

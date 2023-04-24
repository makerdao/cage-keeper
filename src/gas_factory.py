# gas.py
# Copyright (C) 2020 Maker Ecosystem Growth Holdings, INC.
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from typing import Optional

from pygasprice_client.aggregator import Aggregator
from src.gas_strategies import GasStrategy, GeometricGasPrice, FixedGasPrice, DefaultGasPrice


class SmartGasPrice(GasStrategy):
    """Simple and smart gas price scenario.

    Uses an EtherscanAPI feed. start with safe low, move to standard after 120 seconds
    then just do standard * 2. Falls back to a default scenario
    (incremental as well) if the EtherscanAPI feed unavailable for more than 10 minutes.
    """

    GWEI = 1000000000

    def __init__(self, api_key: None, blocknative_api_key=None):
        self.etherscan = Aggregator(refresh_interval=60, expiry=600,
                                      etherscan_api_key=api_key,
                                      blocknative_api_key=blocknative_api_key)

    # if etherscan retruns None 3x in a row, try the next api


    def get_gas_price(self, time_elapsed: int) -> Optional[int]:
        # start with standard price plus backup in case EtherscanAPI is down, then do fast
        if 0 <= time_elapsed <= 240:
            standard_price = self.etherscan.standard_price()
            if standard_price is not None:
                return int(standard_price*1.1)
            else:
                return self.default_gas_pricing(time_elapsed)

        # move to fast after 240 seconds
        if time_elapsed > 240:
            fast_price = self.etherscan.fast_price()
            if fast_price is not None:
                return int(fast_price*1.1)
            else:
                return self.default_gas_pricing(time_elapsed)

    # default gas pricing when EtherscanAPI feed is down
    def default_gas_pricing(self, time_elapsed: int):
        return GeometricGasPrice(initial_price=5*self.GWEI,
                                  increase_by=10*self.GWEI,
                                  every_secs=60,
                                  max_price=100*self.GWEI).get_gas_price(time_elapsed)


class GasPriceFactory:
    @staticmethod
    def create_gas_price(arguments, web3) -> GasStrategy:
        if arguments.smart_gas_price: # --smart-gas-price
            print("Executing smart_gas_price option from gas factory")
            return SmartGasPrice(arguments.etherscan_api_key)
        elif arguments.gas_price: # --gas-price
            print("Executing fixed gas price option from gas strategies")
            return FixedGasPrice(arguments.gas_price)
        else:
            print("Executing GeometricGasPrice gas price option from gas strategies")
            # returns max_price, tip for new transactions
            return GeometricGasPrice(web3, initial_price=None, initial_tip=1000000000, every_secs=60).get_gas_fees(120)

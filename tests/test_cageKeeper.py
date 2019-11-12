# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019 EdNoepel, kentonprescott
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


import pytest

from datetime import datetime, timedelta
import time
from typing import List
import logging

from web3 import Web3

from src.cage_keeper import CageKeeper

from pymaker import Address
from pymaker.approval import directly, hope_directly
from pymaker.auctions import Flapper
from pymaker.deployment import DssDeployment
from pymaker.dss import Collateral, Ilk, Urn
from pymaker.numeric import Wad, Ray, Rad
from pymaker.shutdown import ShutdownModule, End

from tests.test_auctions import create_debt, check_active_auctions, TestFlipper
from tests.test_dss import mint_mkr, wrap_eth, frob, set_collateral_price


def open_cdp(mcd: DssDeployment, collateral: Collateral, address: Address, debtMultiplier: int = 1):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(collateral, Collateral)
    assert isinstance(address, Address)

    collateral.approve(address)
    wrap_eth(mcd, address, Wad.from_number(20))
    assert collateral.adapter.join(address, Wad.from_number(20)).transact(from_address=address)
    frob(mcd, collateral, address, Wad.from_number(20), Wad.from_number(20 * debtMultiplier))

    assert mcd.vat.debt() >= Rad(Wad.from_number(20 * debtMultiplier))
    assert mcd.vat.dai(address) >= Rad.from_number(20 * debtMultiplier)


def wipe_debt(mcd: DssDeployment, collateral: Collateral, address: Address):
    urn = mcd.vat.urn(collateral.ilk, address)
    assert Rad(urn.art) >= mcd.vat.dai(address)
    dink = Ray(mcd.vat.dai(address)) / mcd.vat.ilk(collateral.ilk.name).rate
    frob(mcd, collateral, address, Wad(0), Wad(dink) * -1) #because there is residual state on the testchain
    assert mcd.vat.dai(address) <= Rad(Wad(1)) # pesky dust amount in Dai amount


def open_underwater_urn(mcd: DssDeployment, collateral: Collateral, address: Address):
    open_cdp(mcd, collateral, address, 50)
    previous_eth_price = mcd.vat.ilk(collateral.ilk.name).spot
    print(f"PREV ETH PRICE {previous_eth_price}") # this is 76.66
    set_collateral_price(mcd, collateral, Wad.from_number(49))

    urn = mcd.vat.urn(collateral.ilk, address)
    ilk = mcd.vat.ilk(collateral.ilk.name)
    assert (urn.art * ilk.rate) > (urn.ink * ilk.spot)

    return previous_eth_price


def create_surplus(mcd: DssDeployment, flapper: Flapper, deployment_address: Address):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(flapper, Flapper)
    assert isinstance(deployment_address, Address)

    joy = mcd.vat.dai(mcd.vow.address)

    if joy < mcd.vow.hump() + mcd.vow.bump():
        # Create a CDP with surplus
        print('Creating a CDP with surplus')
        collateral = mcd.collaterals['ETH-B']
        assert flapper.kicks() == 0
        wrap_eth(mcd, deployment_address, Wad.from_number(10))
        collateral.approve(deployment_address)
        assert collateral.adapter.join(deployment_address, Wad.from_number(10)).transact(
            from_address=deployment_address)
        frob(mcd, collateral, deployment_address, dink=Wad.from_number(10), dart=Wad.from_number(1000))
        assert mcd.jug.drip(collateral.ilk).transact(from_address=deployment_address)
        joy = mcd.vat.dai(mcd.vow.address)
        assert joy > mcd.vow.hump() + mcd.vow.bump()
    else:
        print(f'Surplus of {joy} already exists; skipping CDP creation')


def create_flap_auction(mcd: DssDeployment, deployment_address: Address, our_address: Address):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(deployment_address, Address)
    assert isinstance(our_address, Address)

    flapper = mcd.flapper
    print(f"Before Surplus: {mcd.vat.dai(mcd.vow.address)}")
    create_surplus(mcd, flapper, deployment_address)
    print(f"After Surplus: {mcd.vat.dai(mcd.vow.address)}")

    # Kick off the flap auction
    joy = mcd.vat.dai(mcd.vow.address)
    assert joy > mcd.vat.sin(mcd.vow.address) + mcd.vow.bump() + mcd.vow.hump()
    assert (mcd.vat.sin(mcd.vow.address) - mcd.vow.sin()) - mcd.vow.ash() == Rad(0)
    assert mcd.vow.flap().transact()
    kick = flapper.kicks()
    assert kick == 1
    assert len(flapper.active_auctions()) == 1


    mint_mkr(mcd.mkr, our_address, Wad.from_number(10))
    flapper.approve(mcd.mkr.address, directly(from_address=our_address))
    bid = Wad.from_number(0.001)
    assert mcd.mkr.balance_of(our_address) > bid
    assert flapper.tend(flapper.kicks(), mcd.vow.bump(), bid).transact(from_address=our_address)

def create_flop_auction(mcd: DssDeployment, deployment_address: Address, our_address: Address):
    assert isinstance(mcd, DssDeployment)
    assert isinstance(deployment_address, Address)
    assert isinstance(our_address, Address)

    flopper = mcd.flopper
    print(f"Before Debt: {mcd.vat.sin(mcd.vow.address)}")
    if mcd.vow.woe() <= mcd.vow.sump():
        create_debt(mcd.web3, mcd, our_address, deployment_address)
    print(f"After Debt: {mcd.vat.sin(mcd.vow.address)}")

    # Kick off the flop auction
    kicks_before = flopper.kicks()
    assert kicks_before >= 0
    assert len(flopper.active_auctions()) == 0
    assert mcd.vat.dai(mcd.vow.address) == Rad(0)
    assert mcd.vow.flop().transact()
    kicks_after = flopper.kicks()
    assert kicks_after == 1 + kicks_before
    assert len(flopper.active_auctions()) == 1
    check_active_auctions(flopper)
    current_bid = flopper.bids(kicks_after)


    bid = Wad.from_number(0.000005)
    flopper.approve(mcd.vat.address, approval_function=hope_directly(from_address=our_address))
    assert mcd.vat.can(our_address, flopper.address)
    dent(flopper, kicks_after, our_address, bid, current_bid.bid)
    current_bid = flopper.bids(kicks_after)
    assert current_bid.guy == our_address

def dent(flopper: Flopper, id: int, address: Address, lot: Wad, bid: Rad):
    assert (isinstance(id, int))
    assert (isinstance(lot, Wad))
    assert (isinstance(bid, Rad))

    assert flopper.live() == 1

    current_bid = flopper.bids(id)
    assert current_bid.guy != Address("0x0000000000000000000000000000000000000000")
    assert current_bid.tic > datetime.now().timestamp() or current_bid.tic == 0
    assert current_bid.end > datetime.now().timestamp()

    assert bid == current_bid.bid
    assert Wad(0) < lot < current_bid.lot
    assert flopper.beg() * lot <= current_bid.lot

    assert flopper.dent(id, lot, bid).transact(from_address=address)


def create_flip_auction(web3: Web3, mcd: DssDeployment, our_address: Address, deployment_address: Address):
    assert isinstance(web3, Web3)
    assert isinstance(mcd, DssDeployment)
    assert isinstance(our_address, Address)
    assert isinstance(deployment_address, Address)

    # Create a CDP
    collateral = mcd.collaterals['ETH-A']
    ilk = collateral.ilk
    wrap_eth(mcd, deployment_address, Wad.from_number(1))
    collateral.approve(deployment_address)
    assert collateral.adapter.join(deployment_address, Wad.from_number(1)).transact(
        from_address=deployment_address)
    frob(mcd, collateral, deployment_address, dink=Wad.from_number(1), dart=Wad(0))
    dart = max_dart(mcd, collateral, deployment_address) - Wad(1)
    frob(mcd, collateral, deployment_address, dink=Wad(0), dart=dart)

    # Undercollateralize and bite the CDP
    to_price = Wad(Web3.toInt(collateral.pip.read())) / Wad.from_number(2)
    set_collateral_price(mcd, collateral, to_price)
    urn = mcd.vat.urn(collateral.ilk, deployment_address)
    ilk = mcd.vat.ilk(ilk.name)
    safe = Ray(urn.art) * mcd.vat.ilk(ilk.name).rate <= Ray(urn.ink) * ilk.spot
    assert not safe
    simulate_bite(mcd, collateral, deployment_address)
    assert mcd.cat.bite(collateral.ilk, Urn(deployment_address)).transact()
    flip_kick = collateral.flipper.kicks()

    # Generate some Dai, bid on and win the flip auction without covering all the debt
    wrap_eth(mcd, our_address, Wad.from_number(10))
    collateral.approve(our_address)
    assert collateral.adapter.join(our_address, Wad.from_number(10)).transact(from_address=our_address)
    web3.eth.defaultAccount = our_address.address
    frob(mcd, collateral, our_address, dink=Wad.from_number(10), dart=Wad.from_number(200))
    collateral.flipper.approve(mcd.vat.address, approval_function=hope_directly())
    current_bid = collateral.flipper.bids(flip_kick)
    urn = mcd.vat.urn(collateral.ilk, our_address)
    assert Rad(urn.art) > current_bid.tab
    bid = Rad.from_number(6)
    TestFlipper.tend(collateral.flipper, flip_kick, our_address, current_bid.lot, bid)


def prepare_esm(mcd: DssDeployment, our_address: Address):
    assert mcd.esm is not None
    assert isinstance(mcd.esm, ShutdownModule)
    assert isinstance(mcd.esm.address, Address)
    assert mcd.esm.sum() == Wad(0)
    assert mcd.esm.min() > Wad(0)
    assert not mcd.esm.fired()

    assert mcd.mkr.approve(mcd.esm.address).transact()

    # This should have no effect yet succeed regardless
    assert mcd.esm.join(Wad(0)).transact()
    assert mcd.esm.sum() == Wad(0)
    assert mcd.esm.sum_of(our_address) == Wad(0)


    # Mint and join a min amount to call esm.fire
    mint_mkr(mcd.mkr, our_address, mcd.esm.min())
    assert mcd.esm.join(mcd.esm.min()).transact()
    assert mcd.esm.sum() == mcd.esm.min()


def fire_esm(mcd: DssDeployment):
    assert mcd.end.live()
    assert mcd.esm.fire().transact()
    assert mcd.esm.fired()
    assert not mcd.end.live()




def time_travel_by(web3: Web3, seconds: int):
    assert(isinstance(web3, Web3))
    assert(isinstance(seconds, int))

    if "parity" in web3.version.node.lower():
        print(f"time travel unsupported by parity; waiting {seconds} seconds")
        time.sleep(seconds)
        # force a block mining to have a correct timestamp in latest block
        web3.eth.sendTransaction({'from': web3.eth.accounts[0], 'to': web3.eth.accounts[1], 'value': 1})
    else:
        web3.manager.request_blocking("evm_increaseTime", [seconds])
        # force a block mining to have a correct timestamp in latest block
        web3.manager.request_blocking("evm_mine", [])


def init_state_check(mcd: DssDeployment, cage_keeper: CageKeeper):
    # Check if cage(ilk) have not been called
    deploymentIlks = [mcd.collaterals[key].ilk for key in mcd.collaterals.keys()]
    for i in deploymentIlks:
        ilk = mcd.vat.ilk(i.name)
        print("")
        print(f"Name: {ilk.name}")
        print(f"Rate: {ilk.rate}")
        print(f"Ink: {ilk.ink}")
        print(f"Art: {ilk.art}")
        print(f"Spot: {ilk.spot}")
        print(f"line: {ilk.line}")
        print(f"dust: {ilk.dust}")
        assert mcd.end.tag(ilk) == Ray(0)

    # Check if any underwater urns are present
    urns = cage_keeper.get_underwater_urns()
    assert urns[0].art >= Wad.from_number(100)
    assert urns[0].ilk.spot == Wad.from_number(1)
    assert len(urns) == 1
    print(f"Underwater urns: {len(urns)}")


    auctions = cage_keeper.all_active_auctions()
    assert "flips" in auctions
    assert "flaps" in auctions
    assert "flops" in auctions

    i = 0
    for key in auctions["flips"].keys():
        for auction in auctions["flips"][key]:
            assert mcd.flipper.bids(auction.id).lot != 0
            i = i + 1

        print(f"flips for {key}: {i} ")
        i = 0

    for auction in auctions["flaps"]:
        assert mcd.flopper.bids(auction.id).lot != 0
        i = i + 1
    print(f"flaps: {i}")
    i = 0

    for auction in auctions["flops"]:
        assert mcd.flopper.bids(auction.id).lot != 0
        i = i + 1
    print(f"flops: {i}")

    return urns, auctions




def final_state_check(mcd: DssDeployment, urns: List):
    # Check if cage(ilk) called on all ilks
    deploymentIlks = [mcd.collaterals[key].ilk for key in mcd.collaterals.keys()]
    for ilk in deploymentIlks:
        # print(mcd.vat.ilk(ilk.name).spot)
        assert mcd.end.tag(ilk) > Ray(0)

    # All underwater urns present before ES have been skimmed
    for i in urns:
        urn = mcd.vat.urn(i.ilk, i.address)
        assert urn.art == Wad(0)

    # All auctions active before cage have been yanked
    for ilk in auctions["flips"].keys():
        for auction in auctions["flips"][ilk]:
            assert mcd.flipper.bids(auction.id).lot == 0

    for auction in auctions["flaps"]:
        assert mcd.flopper.bids(auction.id).lot == 0

    for auction in auctions["flops"]:
        assert mcd.flopper.bids(auction.id).lot == 0



# def args(arguments: str) -> list:
#     return arguments.split()



nobody = Address("0x0000000000000000000000000000000000000000")


class TestCageKeeper:

    # def setup_method(self, mcd: DssDeployment, keeper_address: Address):
    #     self.keeper = CageKeeper(args=args(f"--eth-from {keeper_address} --network testnet"), web3=mcd.web3)
    #     assert isinstance(self.keeper, CageKeeper)

    @pytest.mark.skip(reason="done")
    def test_get_ilks(self, mcd: DssDeployment, keeper: CageKeeper):
        ilks = keeper.get_ilks()
        assert type(ilks) is list
        assert all(isinstance(x, Ilk) for x in ilks)
        deploymentIlks = [mcd.vat.ilk(key) for key in mcd.collaterals.keys()]
        assert all(elem in deploymentIlks for elem in ilks)

    @pytest.mark.skip(reason="done")
    def test_check_ilks(self, mcd: DssDeployment, keeper: CageKeeper):
        ilks = keeper.check_ilks()
        ilkNames = ilkNames = [i.name for i in ilks]
        assert type(ilks) is list
        assert all(isinstance(x, Ilk) for x in ilks)
        deploymentIlkNames = [mcd.collaterals[key].ilk.name for key in mcd.collaterals.keys()]
        assert set(ilkNames) == set(deploymentIlkNames)


    def test_get_underwater_urns(self, mcd: DssDeployment, keeper: CageKeeper, guy_address: Address, our_address: Address):
        wipe_debt(mcd, mcd.collaterals['ETH-A'], our_address) # Need to wipe debt from residual state of system on testchain

        previous_eth_price = open_underwater_urn(mcd, mcd.collaterals['ETH-A'], guy_address)
        open_cdp(mcd, mcd.collaterals['ETH-C'], our_address)


        urns = keeper.get_underwater_urns()
        assert type(urns) is list
        assert all(isinstance(x, Urn) for x in urns)
        assert len(urns) == 1
        assert urns[0].address.address == guy_address.address

        set_collateral_price(mcd, mcd.collaterals['ETH-A'], Wad(previous_eth_price))



    def test_active_auctions(self, mcd: DssDeployment, keeper: CageKeeper, our_address: Address, other_address: Address, deployment_address: Address):
        #TODO create some auctions
        # Ensure they are in a state that can't be pulled by this function
        assert mcd.vow.heal(mcd.vat.dai(mcd.vow.address)).transact()
        assert mcd.vat.dai(mcd.vow.address) == Rad(0)


        create_flop_auction(mcd, deployment_address, other_address)
        create_flap_auction(mcd, deployment_address, our_address)


        auctions = keeper.all_active_auctions()
        assert "flips" in auctions
        assert "flops" in auctions
        assert "flaps" in auctions

        # All auctions active before cage have been yanked
        for ilk in auctions["flips"].keys():
            for auction in auctions["flips"][ilk]:
                assert auction.id > 0
                assert auction.guy != nobody
                assert auction.bid < bid.tab

        assert len(auctions["flaps"]) == 1
        for auction in auctions["flaps"]:
            assert auction.id > 0
            assert auction.guy != nobody

        assert len(auctions["flops"]) == 1
        for auction in auctions["flops"]:
            assert auction.id > 0
            assert auction.guy != nobody



    @pytest.mark.skip(reason="possibly incomplete")
    def test_cage_keeper(self, mcd, deployment_address, our_address, guy_address, keeper_address):
        prepare_esm(mcd, our_address)

        # Annialate Dai with Sin, if Sin > Dai
        dai = mcd.vat.dai(mcd.vow.address)
        assert mcd.vow.heal(dai).transact()

        # create_flop_auction(mcd, deployment_address, our_address)
        # create_flap_auction(mcd, deployment_address, our_address)
        print(mcd.flapper.kicks())
        print(mcd.flopper.kicks())

        #To make sure CageKeeper doesn't do anything funky with initial state
        # init_state_check(mcd, keeper)

        # Two urns created
        open_underwater_urn(mcd, mcd.collaterals['ETH-A'], our_address)
        open_cdp(mcd, mcd.collaterals['ETH-C'], guy_address)


        urns = init_state_check(mcd, keeper)
        self.keeper.check_cage()

        # CageKeeper.facilitate_cage should not have been called
        assert mcd.end.tag(mcd.vat.ilk('ETH-A')) == Ray(0)

        fire_esm(mcd)

        self.keeper.check_cage()
        final_state_check(mcd, urns)




        # Ending to stop the test
        deploymentIlks = [mcd.collaterals.ilk for key in mcd.collaterals.keys()]

    @pytest.mark.skip(reason="unable to determine redemption price")
    def test_join(self, mcd, our_address):
        assert mcd.mkr.approve(mcd.esm.address).transact()

        # This should have no effect yet succeed regardless
        assert mcd.esm.join(Wad(0)).transact()
        assert mcd.esm.sum() == Wad(0)
        assert mcd.esm.sum_of(our_address) == Wad(0)

        # Ensure the appropriate amount of MKR can be joined
        mint_mkr(mcd.mkr, our_address, mcd.esm.min())
        assert mcd.esm.join(mcd.esm.min()).transact()
        assert mcd.esm.sum() == mcd.esm.min()

        # Joining extra MKR should succeed yet have no effect
        mint_mkr(mcd.mkr, our_address, Wad(153))
        assert mcd.esm.join(Wad(153)).transact()
        assert mcd.esm.sum() == mcd.esm.min() + Wad(153)
        assert mcd.esm.sum_of(our_address) == mcd.esm.sum()

    @pytest.mark.skip(reason="unable to determine redemption price")
    def test_fire(self, mcd, our_address):
        open_cdp(mcd, mcd.collaterals['ETH-A'], our_address)

        assert mcd.end.live()
        assert mcd.esm.fire().transact()
        assert mcd.esm.fired()
        assert not mcd.end.live()
#
# @pytest.mark.skip(reason="unable to determine redemption price")
# class TestEnd:
    # """This test must be run after TestShutdownModule, which calls `esm.fire`."""
    #
    # def test_init(self, mcd):
    #     assert mcd.end is not None
    #     assert isinstance(mcd.end, End)
    #     assert isinstance(mcd.esm.address, Address)
    #
    # def test_getters(self, mcd):
    #     assert not mcd.end.live()
    #     assert datetime.utcnow() - timedelta(minutes=5) < mcd.end.when() < datetime.utcnow()
    #     assert mcd.end.wait() >= 0
    #     assert mcd.end.debt() >= Rad(0)
    #
    #     for collateral in mcd.collaterals.values():
    #         ilk = collateral.ilk
    #         assert mcd.end.tag(ilk) == Ray(0)
    #         assert mcd.end.gap(ilk) == Wad(0)
    #         assert mcd.end.art(ilk) == Wad(0)
    #         assert mcd.end.fix(ilk) == Ray(0)
    #
    # def test_cage(self, mcd):
    #     collateral = mcd.collaterals['ETH-A']
    #     ilk = collateral.ilk
    #
    #     assert mcd.end.cage(ilk).transact()
    #     assert mcd.end.art(ilk) > Wad(0)
    #     assert mcd.end.tag(ilk) > Ray(0)
    #
    # def test_yank(self, mcd):
    #     last_flap = mcd.flapper.bids(mcd.flapper.kicks())
    #     last_flop = mcd.flopper.bids(mcd.flopper.kicks())
    #     if last_flap.end > 0 and last_flap.guy is not nobody:
    #         auction = mcd.flapper
    #     elif last_flop.end > 0 and last_flop.guy is not nobody:
    #         auction = mcd.flopper
    #     else:
    #         auction = None
    #
    #     if auction:
    #         print(f"active {auction} auction: {auction.bids(auction.kicks())}")
    #         assert not auction.live()
    #         kick = auction.kicks()
    #         assert auction.yank(kick).transact()
    #         assert auction.bids(kick).guy == nobody
    #
    # def test_skim(self, mcd, our_address):
    #     ilk = mcd.collaterals['ETH-A'].ilk
    #
    #     urn = mcd.vat.urn(ilk, our_address)
    #     owe = Ray(urn.art) * mcd.vat.ilk(ilk.name).rate * mcd.end.tag(ilk)
    #     assert owe > Ray(0)
    #     wad = min(Ray(urn.ink), owe)
    #     print(f"owe={owe} wad={wad}")
    #
    #     assert mcd.end.skim(ilk, our_address).transact()
    #     assert mcd.vat.urn(ilk, our_address).art == Wad(0)
    #     assert mcd.vat.urn(ilk, our_address).ink > Wad(0)
    #     assert mcd.vat.sin(mcd.vow.address) > Rad(0)
    #
    #     assert mcd.vat.debt() > Rad(0)
    #     assert mcd.vat.vice() > Rad(0)
    #
    # @pytest.mark.skip(reason="unable to determine redemption price")
    # def test_close_cdp(self, mcd, our_address):
    #     collateral = mcd.collaterals['ETH-A']
    #     ilk = collateral.ilk
    #
    #     assert mcd.end.free(ilk).transact()
    #     assert mcd.vat.urn(ilk, our_address).ink == Wad(0)
    #     assert mcd.vat.gem(ilk, our_address) > Wad(0)
    #     assert collateral.adapter.exit(our_address, mcd.vat.gem(ilk, our_address)).transact()
    #
    #     assert mcd.end.wait() == 0
    #     assert mcd.end.thaw().transact()
    #     assert mcd.end.flow(ilk).transact()
    #     # FIXME: `flow` should determine redemption price for the collateral
    #     assert mcd.end.fix(ilk) > Ray(0)
    #
    # @pytest.mark.skip(reason="unable to add dai to the `bag`")
    # def test_pack(self, mcd, our_address):
    #     assert mcd.end.bag(our_address) == Wad(0)
    #     assert mcd.end.debt() > Rad(0)
    #     assert mcd.dai.approve(mcd.end.address).transact()
    #     assert mcd.vat.dai(our_address) >= Rad.from_number(10)
    #     # FIXME: `pack` fails, possibly because we're passing 0 to `vat.flux`
    #     assert mcd.end.pack(Wad.from_number(10)).transact()
    #     assert mcd.end.bag(our_address) == Wad.from_number(10)

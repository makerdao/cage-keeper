# This file is part of Maker Keeper Framework.
#
# Copyright (C) 2019 KentonPrescott
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

from datetime import datetime, timedelta, timezone
import time
from typing import List
import logging

from web3 import Web3

from src.cage_keeper import CageKeeper

from pymaker import Address
from pymaker.approval import directly, hope_directly
from pymaker.auctions import Flapper, Flopper, Flipper
from pymaker.deployment import DssDeployment
from pymaker.dss import Collateral, Ilk, Urn
from pymaker.numeric import Wad, Ray, Rad
from pymaker.shutdown import ShutdownModule, End

from tests.test_auctions import create_debt, check_active_auctions, max_dart
from tests.test_dss import mint_mkr, wrap_eth, frob, set_collateral_price
from tests.helpers import time_travel_by


def open_vault(mcd: DssDeployment, collateral: Collateral, address: Address, debtMultiplier: int = 1):
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
    open_vault(mcd, collateral, address, 100)
    previous_eth_price = mcd.vat.ilk(collateral.ilk.name).spot * mcd.spotter.mat(collateral.ilk)
    print(f"Previous ETH Price {previous_eth_price} USD")
    set_collateral_price(mcd, collateral, Wad.from_number(49))

    urn = mcd.vat.urn(collateral.ilk, address)
    ilk = mcd.vat.ilk(collateral.ilk.name)
    mat = mcd.spotter.mat(ilk)
    assert (urn.art * ilk.rate) > (urn.ink * ilk.spot * mat)

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
    kicks = flopper.kicks()
    assert kicks == 0
    assert len(flopper.active_auctions()) == 0
    assert mcd.vat.dai(mcd.vow.address) == Rad(0)
    assert mcd.vow.flop().transact()
    kicks = flopper.kicks()
    assert kicks == 1
    assert len(flopper.active_auctions()) == 1
    check_active_auctions(flopper)
    current_bid = flopper.bids(kicks)


    bid = Wad.from_number(0.000005)
    flopper.approve(mcd.vat.address, approval_function=hope_directly(from_address=our_address))
    assert mcd.vat.can(our_address, flopper.address)
    dent(flopper, kicks, our_address, bid, current_bid.bid)
    current_bid = flopper.bids(kicks)
    assert current_bid.guy == our_address


def dent(flopper: Flopper, id: int, address: Address, lot: Wad, bid: Rad):
    assert (isinstance(flopper, Flopper))
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


def create_flip_auction(mcd: DssDeployment, deployment_address: Address, our_address: Address):
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
    to_price = Wad(mcd.web3.toInt(collateral.pip.read())) / Wad.from_number(2)
    set_collateral_price(mcd, collateral, to_price)
    urn = mcd.vat.urn(collateral.ilk, deployment_address)
    ilk = mcd.vat.ilk(ilk.name)
    safe = Ray(urn.art) * mcd.vat.ilk(ilk.name).rate <= Ray(urn.ink) * ilk.spot
    assert not safe
    assert mcd.cat.can_bite(collateral.ilk, Urn(deployment_address))
    assert mcd.cat.bite(collateral.ilk, Urn(deployment_address)).transact()
    flip_kick = collateral.flipper.kicks()

    # Generate some Dai, bid on the flip auction without covering all the debt
    wrap_eth(mcd, our_address, Wad.from_number(10))
    collateral.approve(our_address)
    assert collateral.adapter.join(our_address, Wad.from_number(10)).transact(from_address=our_address)
    mcd.web3.eth.defaultAccount = our_address.address
    frob(mcd, collateral, our_address, dink=Wad.from_number(10), dart=Wad.from_number(200))
    collateral.flipper.approve(mcd.vat.address, approval_function=hope_directly())
    current_bid = collateral.flipper.bids(flip_kick)
    urn = mcd.vat.urn(collateral.ilk, our_address)
    assert Rad(urn.art) > current_bid.tab
    bid = Rad.from_number(6)
    tend(collateral.flipper, flip_kick, our_address, current_bid.lot, bid)


def tend(flipper: Flipper, id: int, address: Address, lot: Wad, bid: Rad):
        assert (isinstance(flipper, Flipper))
        assert (isinstance(id, int))
        assert (isinstance(lot, Wad))
        assert (isinstance(bid, Rad))

        current_bid = flipper.bids(id)
        assert current_bid.guy != Address("0x0000000000000000000000000000000000000000")
        assert current_bid.tic > datetime.now().timestamp() or current_bid.tic == 0
        assert current_bid.end > datetime.now().timestamp()

        assert lot == current_bid.lot
        assert bid <= current_bid.tab
        assert bid > current_bid.bid
        assert (bid >= Rad(flipper.beg()) * current_bid.bid) or (bid == current_bid.tab)

        assert flipper.tend(id, lot, bid).transact(from_address=address)


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


def print_out(testName: str):
    print("")
    print(f"{testName}")
    print("")


pytest.global_urns = []
pytest.global_auctions = {}

class TestCageKeeper:

    def test_check_deployment(self, mcd: DssDeployment, keeper: CageKeeper):
        print_out("test_check_deployment")
        keeper.check_deployment()

    def test_get_underwater_urns(self, mcd: DssDeployment, keeper: CageKeeper, guy_address: Address, our_address: Address):
        print_out("test_get_underwater_urns")

        previous_eth_price = open_underwater_urn(mcd, mcd.collaterals['ETH-A'], guy_address)
        open_vault(mcd, mcd.collaterals['ETH-C'], our_address)

        ilks = keeper.get_ilks()

        urns = keeper.get_underwater_urns(ilks)
        assert type(urns) is list
        assert all(isinstance(x, Urn) for x in urns)
        assert len(urns) == 1
        assert urns[0].address.address == guy_address.address

        ## We've multiplied by a small Ray amount to counteract
        ## the residual dust (or lack thereof) in this step that causes
        ## create_flop_auction fail
        set_collateral_price(mcd, mcd.collaterals['ETH-A'], Wad(previous_eth_price * Ray.from_number(1.0001)))

        pytest.global_urns = urns

    def test_get_ilks(self, mcd: DssDeployment, keeper: CageKeeper):
        print_out("test_get_ilks")

        ilks = keeper.get_ilks()
        assert type(ilks) is list
        assert all(isinstance(x, Ilk) for x in ilks)
        deploymentIlks = [mcd.vat.ilk(key) for key in mcd.collaterals.keys()]

        empty_deploymentIlks = list(filter(lambda l: mcd.vat.ilk(l.name).art == Wad(0), deploymentIlks))

        assert all(elem not in empty_deploymentIlks for elem in ilks)

    def test_active_auctions(self, mcd: DssDeployment, keeper: CageKeeper, our_address: Address, other_address: Address, deployment_address: Address):
        print_out("test_active_auctions")
        print(f"Sin: {mcd.vat.sin(mcd.vow.address)}")
        print(f"Dai: {mcd.vat.dai(mcd.vow.address)}")

        create_flap_auction(mcd, deployment_address, our_address)
        create_flop_auction(mcd, deployment_address, other_address)
        # this flip auction sets the collateral back to a price that makes the guy's vault underwater again.
        # 49 to make it underwater, and create_flip_auction sets it to 33
        create_flip_auction(mcd, deployment_address, our_address)

        auctions = keeper.all_active_auctions()
        assert "flips" in auctions
        assert "flops" in auctions
        assert "flaps" in auctions

        nobody = Address("0x0000000000000000000000000000000000000000")

        # All auctions active before cage have been yanked
        for ilk in auctions["flips"].keys():
            for auction in auctions["flips"][ilk]:
                assert len(auctions["flips"][ilk]) == 1
                assert auction.id > 0
                assert auction.bid < auction.tab
                assert auction.guy != nobody
                assert auction.guy == our_address

        assert len(auctions["flaps"]) == 1
        for auction in auctions["flaps"]:
            assert auction.id > 0
            assert auction.guy != nobody
            assert auction.guy == our_address

        assert len(auctions["flops"]) == 1
        for auction in auctions["flops"]:
            assert auction.id > 0
            assert auction.guy != nobody
            assert auction.guy == other_address

        pytest.global_auctions = auctions

    def test_check_cage(self, mcd: DssDeployment, keeper: CageKeeper, our_address: Address, other_address: Address):
        print_out("test_check_cage")
        keeper.check_cage()
        assert keeper.cageFacilitated == False
        assert mcd.end.live() == 1
        prepare_esm(mcd, our_address)
        fire_esm(mcd)
        assert keeper.confirmations == 0
        for i in range(0,12):
            time_travel_by(mcd.web3, 1)
            keeper.check_cage()
        assert keeper.confirmations == 12

        keeper.check_cage() # Facilitate processing period
        assert keeper.cageFacilitated == True

        when = mcd.end.when()
        wait = mcd.end.wait()
        whenInUnix = when.replace(tzinfo=timezone.utc).timestamp()
        blockNumber = mcd.web3.eth.blockNumber
        now = mcd.web3.eth.getBlock(blockNumber).timestamp
        thawedCage = whenInUnix + wait
        assert now >= thawedCage

        time_travel_by(mcd.web3, 1)

        keeper.check_cage() # Facilitate cooldown (thawing cage)

    def test_cage_keeper(self, mcd: DssDeployment, keeper: CageKeeper, our_address: Address, other_address: Address):
        print_out("test_cage_keeper")
        ilks = keeper.get_ilks()
        urns = pytest.global_urns
        auctions = pytest.global_auctions

        for ilk in ilks:
            # Check if cage(ilk) called on all ilks
            assert mcd.end.tag(ilk) > Ray(0)

            # Check if flow(ilk) called on all ilks
            assert mcd.end.fix(ilk) > Ray(0)

        # All underwater urns present before ES have been skimmed
        for i in urns:
            urn = mcd.vat.urn(i.ilk, i.address)
            assert urn.art == Wad(0)

        # All auctions active before cage have been yanked
        for ilk in auctions["flips"].keys():
            for auction in auctions["flips"][ilk]:
                assert mcd.collaterals[ilk].flipper.bids(auction.id).lot == Wad(0)

        for auction in auctions["flaps"]:
            assert mcd.flapper.bids(auction.id).lot == Rad(0)

        for auction in auctions["flops"]:
            assert mcd.flopper.bids(auction.id).lot == Wad(0)

        # Cage has been thawed (thaw() called)
        assert mcd.end.debt() != Rad(0)

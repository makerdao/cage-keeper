# cage-keeper

The Cage Keeper is used to help facilitate [Emergency Shutdown](https://blog.makerdao.com/introduction-to-emergency-shutdown-in-multi-collateral-dai/) of the [Maker Protocol](https://github.com/makerdao/dss). Emergency shutdown is an involved, deterministic process, requiring interaction from all user types: Vault owners, Dai holders, Redemption keepers, MKR governors, and other Maker Protocol Stakeholders. A high level overview is as follows:
1. System Caged - The Emergency Security Module [(ESM)](https://github.com/makerdao/esm) calls `End.cage()` function, which freezes the USD price for each collateral type as well as many parts of the system.
2. Processing Period - Next, Vault owners interact with End to settle their Vault and withdraw excess collateral. Auctions are left to conclude or are yanked before settlement.
3. Dai Redemption  - After the processing period duration `End.wait` has elapsed, Vault settlement and all Dai generating processes (auctions) are assumed to have concluded. At this point, Dai holders can begin to claim a proportional amount of each collateral type at a fixed rate.

To prevent a race-condition for Dai holders during Step 3, it's imperative that any Vaults having a collateralization ratio of less than 100% at Step 1 must be processed during Step 2. The owner of these underwater vaults would not receive excess collateral, so they lack an incentive to `skim` their position in the `End` contract. Thus, it is the responsibility of a MakerDao Stakeholder (MKR holders, large Dai holders, etc) to ensure the system facilitates a Dai redemption phase without a time variable.

To be consistent with the Protocol's technical terminology for the rest of this description:
* `urn` = Vault
* `ilk` = Collateral Type

## Keeper Operation

<p align="center">
  <img src="operation.png">
</p>

The largest responsibility of the Cage-Keeper is the processing of under-collateralized `urns`. This accounting step is performed within `End.skim()`, and since it is surrounded by other required/important steps in the Emergency Shutdown, a first iteration of Cage Keeper will help to call most of the other public function calls within the `End` contract. As can be seen in the flowchart, the keepers operation checks if the system has been caged before attempting to `skim` all underwater urns and `skip` all flip auctions. After the processing period has been facilitated and the `End.wait` waittime has been reached, it will call transition the system into the Dai redemption phase of Emergency Shutdown by calling `End.thaw()` and `End.flow()`. This first iteration of this keeper is naive, as it assumes it's the only keeper and attempts to account for all urns, ilks, and auctions. Because of this, it's important that the Cage Keeper's address has enough ETH to cover the gas costs involved with sending numerous transactions. 



## Installation

This project uses *Python 3.6.2*.

In order to clone the project and install required third-party packages please execute:
```
git clone https://github.com/makerdao/cage-keeper.git
cd cage-keeper
git submodule update --init --recursive
./install.sh
```

For some known Ubuntu and macOS issues see the [pymaker](https://github.com/makerdao/pymaker) README.


### Sample Startup Script

Make a run-cage-keeper.sh to easily spin up the cage-keeper.

```
#!/bin/bash
/full/path/to/cage-keeper/bin/cage-keeper \
	--rpc-host 'kovan.SampleParityNode.com' \
  	--network 'kovan' \
	--eth-from '0xABCKovanAddress' \
	--eth-key 'key_file=/full/path/to/keystoreFile.json,pass_file=/full/path/to/passphrase/file.txt' \
	--vat-deployment-block 14374534
```


## Testing

Prerequisites:
* Download [docker and docker-compose](https://www.docker.com/get-started)

This project uses [pytest](https://docs.pytest.org/en/latest/) for unit testing.  Testing of Multi-collateral Dai is
performed on a Dockerized local testchain included in `tests\config`.

In order to be able to run tests, please install development dependencies first by executing:
```
pip3 install -r requirements-dev.txt
```

You can then run all tests with:
```
./test.sh
```

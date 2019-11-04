# cage-keeper
Keeper to facilitate Emergency Shutdown


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
* [docker and docker-compose](https://www.docker.com/get-started)
* [ganache-cli](https://github.com/trufflesuite/ganache-cli) 6.2.5  
  (using npm, `sudo npm install -g ganache-cli@6.2.5`)

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

#  Dockerized Cage-Keeper

# Build and Run the cage-keeper locally

## Prerequisite:
- docker installed: https://docs.docker.com/install/
- Git

## Installation
Clone the project and install required third-party packages:
```
git clone git@github.com:makerdao/cage-keeper.git
cd cage-keeper
git submodule update --init --recursive
```

## Configure, Build and Run:

## Configure
### Configure Envrionment variables
The cage-keeper requires the following environment variables in `env/envvars.sh` file.
Make a copy of the envvarstemplate.sh file, name it envvars.sh, and enter the required environment variables.

```
# DNS for ETH Parity Node, ex: myparity.node.com (default: `localhost')
SERVER_ETH_RPC_HOST=

# Ethereum blockchain to connect to, ex: (mainnet | kovan)
BLOCKCHAIN_NETWORK=

# Account used to pay for gas
ETH_FROM_ADDRESS=

# URL of Vulcanize instance to use
VULCANIZE_URL=

# ETH Gas Station API key
ETH_GASSTATION_API_KEY=

# For ease of use, do not change the location of ETH account keys, note that account files should always be placed in the secrets directory of the cage-keeper, and files named as indicated.
ETH_ACCOUNT_KEY='key_file=/opt/keeper/cage-keeper/secrets/keystore.json,pass_file=/opt/keeper/cage-keeper/secrets/password.txt'
```

### Configure ETH account keys

Place unlocked keystore and password file for the account address under *secrets* directory. The names of the keystore should be *keystore.json*, and password file should be *password.txt*. If you name your secrets files something other than indicated, you will need to update the *ETH_ACCOUNT_KEY=* value, in envvars.sh, to reflect the change.

## Build
### Build the docker image locally
From within the `cage-keeper` directory, run the following command:
```
docker build --tag cage-keeper .
```

## Run
### Run the cage-keeper
Running the cage-keeper requires you to pass the environment file to the container, and map a volume to the secrets directory to allow the cage-keeper to access your keystore files.
From within the `cage-keeper` directory, run the following command:
```
docker run \
    --env-file env/envvars.sh \
    --volume "$(pwd)"/secrets:/opt/keeper/cage-keeper/secrets \
    cage-keeper:latest
```

To run the container in the background, use the `-d` option.
```
docker run -d \
    --env-file env/envvars.sh \
    --volume "$(pwd)"/secrets:/opt/keeper/cage-keeper/secrets \
    cage-keeper:latest
```
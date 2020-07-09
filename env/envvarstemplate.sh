##-------------------------------------------------------------------##
# Template file for environment variables used for docker deployment.
# see DOCKER.md
##-------------------------------------------------------------------##

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
ETH_ACCOUNT_KEY=key_file=/opt/keeper/cage-keeper/secrets/keystore.json,pass_file=/opt/keeper/cage-keeper/secrets/password.txt

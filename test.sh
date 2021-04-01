#!/bin/bash

# Pull the docker image
docker pull makerdao/testchain-pymaker:unit-testing-2.0.0

# Start the docker image and wait for parity to initialize
pushd ./lib/pymaker
docker-compose up -d
sleep 2
popd

PYTHONPATH=$PYTHONPATH:./lib/pymaker:./lib/auction-keeper:./lib/pygasprice-client py.test -s --cov=src --cov-report=term --cov-append tests/test_cageKeeper.py $@
TEST_RESULT=$?

echo Stopping container
pushd ./lib/pymaker
docker-compose down
popd

exit $TEST_RESULT

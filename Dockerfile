FROM python:3.6.6

RUN groupadd -r keeper && useradd -d /home/keeper -m --no-log-init -r -g keeper keeper && \
    apt-get -y update && \
    apt-get -y install jq bc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/keeper

RUN git clone https://github.com/makerdao/cage-keeper.git && \
    cd cage-keeper && \
    git submodule update --init --recursive && \
    pip3 install virtualenv && \
    ./install.sh

WORKDIR /opt/keeper/cage-keeper
CMD ["./run-cage-keeper.sh"]

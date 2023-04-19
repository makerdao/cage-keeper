FROM python:3.6.6

RUN groupadd -r keeper && useradd -d /home/keeper -m --no-log-init -r -g keeper keeper && \
    apt-get -y update && \
    apt-get -y install jq bc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY bin /opt/keeper/cage-keeper/bin
COPY lib /opt/keeper/cage-keeper/lib
COPY src /opt/keeper/cage-keeper/src
COPY install.sh /opt/keeper/cage-keeper/install.sh
COPY run-cage-keeper.sh /opt/keeper/cage-keeper/run-cage-keeper.sh
COPY requirements.txt /opt/keeper/cage-keeper/requirements.txt

WORKDIR /opt/keeper/cage-keeper
RUN pip3 install virtualenv && \
    ./install.sh


CMD ["./run-cage-keeper.sh"]

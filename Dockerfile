FROM python:3.9-slim-bullseye as base

#
# Prepare environment
#

# Setup env
ENV PATH=/home/bot/.local/bin:$PATH

# Install OS packages
RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get -y install sudo git build-essential black \
    && apt-get clean \
    && pip install --upgrade pip \
    && useradd -u 1000 -G sudo -U -m -s /bin/bash bot \
    && echo "bot ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

WORKDIR /home/bot/telegram-bot

USER bot

# Install development tools
RUN pip install python-telegram-bot==v20.0a4 && \
    pip install requests && \
    pip install web3 && \
    pip install aiofiles && \
    pip install black

CMD ["python", "./scripts/main.py"]

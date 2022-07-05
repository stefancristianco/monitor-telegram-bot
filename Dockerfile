FROM python:3.10.5-slim-bullseye as base

#
# Prepare environment
#

# Setup env
ENV PATH=/home/crst/.local/bin:$PATH

# Install OS packages
RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get -y install sudo git build-essential black \
    && apt-get clean \
    && pip install --upgrade pip \
    && useradd -u 1000 -G sudo -U -m -s /bin/bash crst \
    && echo "crst ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

WORKDIR /home/crst/bot

USER crst

# Install development tools
RUN pip install python-telegram-bot --pre && \
    pip install requests && \
    pip install black

CMD ["python", "./scripts/main.py"]
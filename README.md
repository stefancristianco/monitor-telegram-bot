# Forta monitor telegram bot

A telegram bot that monitors Forta Network scanners and sends message alerts when SLA drops below configured threshold.

Additionally the bot can subscribe to FORT token Transfer events and alert when new tokens are distributed to the configured wallets. As an example, it can be used to get notified when new rewards are distributed.

## Environment setup

### VPS

You will need to install and run the bot 24/7, so my recommended method is to acquire a cheap VPS. There are many providers online, so just find one that is convenient for you, or simply run it alongside one of your scanner nodes.

### Creating a Telegram Bot

You will need your own telegram bot id. Ask [BotFather](https://core.telegram.org/bots) to create one for you.

### Required software

The bot is configured to run within Docker. So all you need now is to install [Docker Engine](https://docs.docker.com/engine/install/ubuntu/).

## Configuring the bot

### Building the Docker image

You need to do this steps only once.

Clone this repo into your workspace (install git if you don't have it already):

```sh
git clone https://github.com/stefancristianco/monitor-telegram-bot.git
```

Build Docker image (TIP: use docker with sudo if you have permission errors):

```sh
cd monitor-telegram-bot
docker build -t docker-telegram-bot .
```

Some configuration is necessary at this step before actually running the bot. A python script will generate a template for you to start with. Start the container in interactive mode and run the script using python from within the container:

```sh
docker run --rm -it -v`pwd`:/home/bot/telegram-bot docker-telegram-bot /bin/bash
(container) $ python ./scripts/gen_config.py
(container) $ exit
```

Open config file with your favorite editor and add the missing information:

```sh
nano config.json
```

```json
{
    "bot": {
        "token": "bot_token",
        "allowed_users": ["000000000"],
    },
    "extensions": {
        "forta": {
            "scanner_pool_interval": "300",
            "wallet_pool_interval": "30",
            "db_path": "forta.json",
            "url": "https://api.forta.network/stats/sla/scanner/",
            "chains": {
                "eth": {
                    "url": "wss://...",
                    "token": "0x41545f8b9472D758bB669ed8EaEEEcD7a9C4Ec29"
                },
                "matic": {
                    "url": "wss://...",
                    "token": "0x9ff62d1FC52A907B6DCbA8077c2DDCA6E6a9d3e1"
                },
            },
            "description": "Scanner node monitoring and alerts extension."
        }
    }
}
```

You will need to edit the following entries:

- Secret Bot token that was provided to you by BotFather. This token controls your bot.
- Your chatid. Your bot is public, so anyone can find it and interact with it. This id is used to make sure nobody else can send commands to your bot, except you. We will get back to this step a bit later.

```json
"bot": {
    "token": "bot_token",
    "allowed_users": ["000000000"],
},
```

- The bot also notifies you when FORT tokens are sent to your wallet address. This can be useful to know when rewards have been distributed. Go to your favorite provider and get two urls, one for Ethereum mainnet and one for Polygon mainnet. Attention that the endpoint MUST start with "wss://" and MUST support "eth_subscribe". Most providers do support these features, but just in case, I tested using a free plan (NOT the public one) from [Blast](https://blastapi.io/):

```json
"eth": {
    "url": "wss://YOUR-ETH-URL-HERE",
    "token": "0x41545f8b9472D758bB669ed8EaEEEcD7a9C4Ec29"
},
"matic": {
    "url": "wss://YOUR-POLYGON-URL-HERE",
    "token": "0x9ff62d1FC52A907B6DCbA8077c2DDCA6E6a9d3e1"
},
```

## Start the bot

To start the bot you simply need to run the docker container as before, but without the interactive mode:

```sh
docker run --rm -d -v`pwd`:/home/bot/telegram-bot docker-telegram-bot
```

## Find your chat id

To finalize setup you need to fill in the chat id. The bot has two public commands (can be executed by anyone, unrestricted) and one of them is "/chatid". Just type it in, get the number that was outputed and fill it in the configuration file under "allowed_users".

## Finalize setup

Now restart your bot one last time to read this configuration. Replace "YOUR-CONTAINER-ID" with the real container id exposed by the first command:

```sh
docker ps
docker stop YOUR-CONTAINER-ID
docker run --rm -d -v`pwd`:/home/bot/telegram-bot docker-telegram-bot
```

## Usage example

The bot is now ready to accept commands. Start with "/help" and "/forta help" to get a good idea of what is available.

For example, to add a new scanner node you can do (replace with your real scan node public address):

```sh
/forta scanner add my-scanner-name 0x715F69D034378a220C04d343F8a84F47C79C03d8
```

You can ask for the current SLA value for all your registered scanner nodes:

```sh
/forta scanner status
```

To add your wallet and monitor FORT token distribution you can do (replace with your real wallet public address):

```sh
/forta wallet add my-account-name 0x715F69D034378a220C04d343F8a84F47C79C03d8
```

The monitoring job is not started by default, you have start/stop commands for that:

```sh
/forta start
```

Have a look at all the options you have available:

```sh
/forta help
```

## In the end

This software is still work in progress. I am using it myself and I try to fix everything I find, so it will get more robust with time.

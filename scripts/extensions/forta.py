"""
Forta is the extension used to monitor forta-network scanner nodes.
"""
from ast import excepthandler
import logging
import json
import asyncio
import copy
import aiofiles

from typing import Any, List, Tuple
from aiohttp import ClientSession
from telegram import Update
from telegram.ext import ContextTypes, Application
from web3 import Web3

from helpers.utils import (
    job_exist,
    validate_address,
    remove_job_if_exists,
    validate_name,
)
from extensions.extension_base import ExtensionBase

logger = logging.getLogger(__name__)

HELP = """HELP

AVAILABLE ACTIONS
[/forta help]
    Print this help message.
[/forta scanner add :friendly-name: :address:]
    Add new scanner address to monitor.
    :param friendly-name: Friendly name for the scanner.
    :param address: Scanner address.
[/forta scanner alert :sla-threshold:]
    Set SLA threshold value for generating alerts (default: 0.90).
    :param sla-threshold: SLA threshold to produce alerts.
[/forta scanner remove :friendly-name:]
    Remove a given scanner from monitoring list.
    :param friendly-name: Friendly name for the scanner.
[/forta scanner status]
    Query SLA for all registered scanner nodes.
[/forta scanner list]
    Show all registered scanner nodes.
[/forta wallet add :friendly-name: :address:]
    Add new wallet address to monitor for FORT balance updates.
    :param friendly-name: Friendly name for the wallet.
    :param address: Wallet address.
[/forta wallet remove :friendly-name:]
    Add new wallet address to monitor for FORT balance updates.
    :param friendly-name: Friendly name for the wallet.
[/forta wallet balance :friendly-name:]
    Show current balance for wallet.
    :param friendly-name: Friendly name for the wallet.
[/forta wallet list]
    Show all regitered wallets.
[/forta chain list]
    Show all configured chains.
[/forta start]
    Start monitoring wallet and scanner nodes.
[/forta stop]
    Stop monitoring wallet and scanner nodes.
"""


class Forta(ExtensionBase):
    """
    Forta monitor extension logic.
    """

    def __init__(self, config: Any, app: Application) -> None:
        """
        Init all variables and objects the bot needs to work.
        :param forta_config: forta specific configuration.
        """
        self.config = config
        try:
            self.user_config = {"scanners": {}, "wallets": {}, "threshold": "0.90"}
            with open(self.config["db_path"], "r") as infile:
                self.user_config = json.load(infile)
        except FileNotFoundError:
            # Non critical error, as first time run it is expected
            # that this file is missing
            pass

        self.ERC20_ABI = {}
        with open("./scripts/extensions/abis/ERC20.json", "r") as infile:
            self.ERC20_ABI = json.load(infile)

        self.request_id = 0
        self.wallet_updated = False

        self.scanner_current_sla = {}
        self.scanner_prev_sla = {}

        self.pending_signals = {}
        self.final_signals = {}

        for chain_name in self.config["chains"]:
            self.pending_signals[chain_name] = {}

        self.start_global_jobs(app)

    async def forta_fetch_sla(
        self, session: ClientSession, address: str, name: str = None
    ):
        """
        Performs a get request to forta explorer service to obtain SLA.
        :param address: scanner node address to query.
        :return: tuple[name, http response as string].
        """
        async with session.get(url=f"{self.config['url']}{address}") as response:
            response.raise_for_status()
            return name, await response.json()

    def scanner_job_name(self) -> str:
        """
        Creates an unique job name for scanner monitoring job.
        :return: job name as string.
        """
        return "FORTA#1"

    def scanner_reader_job_name(self, update: Update) -> str:
        """
        Creates an unique job name for scanner monitoring job. One such job
        is created per chat id, so each user can receive notifications.
        :return: job name as string.
        """
        return f"FORTA#1#{update.message.chat_id}"

    def wallet_job_name(self) -> str:
        """
        Creates an unique job name for wallet monitoring job.
        :return: job name as string.
        """
        return "FORTA#2"

    def wallet_reader_job_name(self, update: Update) -> str:
        """
        Creates an unique job name for wallet monitoring job. One such job
        is created per chat id, so each user can receive notifications.
        :return: job name as string.
        """
        return f"FORTA#2{update.message.chat_id}"

    def get_block_confirmations(self, chain_name: str) -> int:
        """
        Get required block confirmations (backwards compatible with old configs).
        :param chain_name: name of chain to query.
        :return: nr block confirmations from config, or a default value if not available.
        """
        if "confirmations" in self.config["chains"][chain_name]:
            return int(self.config["chains"][chain_name]["confirmations"])
        return 10

    def wallet_address_to_name(self, address: str) -> str:
        """
        Find friendly name from wallet address.
        :param address: the wallet address to match.
        :return: wallet friendly name, or None if wallet address in not known.
        """
        for friendly_name in self.user_config["wallets"]:
            wallet_address = self.user_config["wallets"][friendly_name]
            if address == wallet_address:
                return friendly_name
        return None

    def start_global_jobs(self, app: Application) -> None:
        """
        Add jobs to monitor scanner nodes and wallet transfers.
        :return: None
        """

        # Prepare scanner monitor jobs
        pooling_interval = float(self.config["scanner_pool_interval"])
        app.job_queue.run_repeating(
            callback=self.read_scanner_sla,
            interval=pooling_interval,
            name=self.scanner_job_name(),
        )
        # Prepare wallet monitor jobs
        app.job_queue.run_once(
            callback=self.wallet_update_signals,
            when=0,
            name=self.wallet_job_name(),
        )

    def query_token_details_for_chain(self, chain_name: str) -> Tuple[str, int]:
        """
        Retrieve token symbol and precision for chain/token.
        :param chain_name: chain to query.
        :return: Tuple[symbol, devimals]
        """
        provider = Web3(
            Web3.WebsocketProvider(self.config["chains"][chain_name]["url"])
        )
        contract = provider.eth.contract(
            self.config["chains"][chain_name]["token"],
            abi=self.ERC20_ABI,
        )
        symbol = contract.functions.symbol().call()
        decimals = contract.functions.decimals().call()

        return symbol, decimals

    def query_account_balance_for_chain(self, chain_name: str, wallet_name: str):
        """
        Retrieve account balance for chain/token/wallet.
        :param chain_name: chain to query.
        :param wallet_name: wallet to query.
        :return: wallet balance.
        """
        provider = Web3(
            Web3.WebsocketProvider(self.config["chains"][chain_name]["url"])
        )
        contract = provider.eth.contract(
            self.config["chains"][chain_name]["token"],
            abi=self.ERC20_ABI,
        )
        wallet = self.user_config["wallets"][wallet_name]

        return contract.functions.balanceOf(wallet).call()

    def query_block_number_for_chain_noexcept(self, chain_name: str) -> int:
        """
        Retrieve latest block number for chain.
        :param chain_name: chain to query.
        :return: block number.
        """
        try:
            provider = Web3(
                Web3.WebsocketProvider(self.config["chains"][chain_name]["url"])
            )
            return provider.eth.get_block_number()
        except:
            logger.exception("Get block number failed")
        return 0

    async def subscribe_to_chain(self, connection, chain_name: str) -> str:
        """
        Subscribe for Transfer events on given chain.
        :param connection: connection instance to use for ws communication.
        :param chain_name: chain to query.
        :return: subscription id.
        """

        def address_to_topic(address: str) -> str:
            return f"0x000000000000000000000000{address[2:]}"

        wallets = [
            address_to_topic(self.user_config["wallets"][arg])
            for arg in self.user_config["wallets"]
        ]

        self.request_id += 1
        await connection.send_json(
            {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": "eth_subscribe",
                "params": [
                    "logs",
                    {
                        "address": self.config["chains"][chain_name]["token"],
                        "topics": [
                            "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                            None,
                            wallets,
                        ],
                    },
                ],
            }
        )
        response = await connection.receive_json(timeout=5)
        return response["result"]

    async def unsubscribe_from_chain_noexcept(
        self, connection, subscription: str
    ) -> None:
        """
        Unsubscribe from chain events.
        :param chain_name: chain to unsubscribe from.
        :return: None
        """
        self.request_id += 1
        try:
            await connection.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": self.request_id,
                    "method": "eth_unsubscribe",
                    "params": [subscription],
                }
            )
            await connection.recv()
        except:
            # Non critical, best effort
            pass

    def process_pending_signals_for_chain(self, chain_name: str) -> None:
        """
        Check for signals with enough block confirmations and move to final list.
        :param chain_name: chain name to process.
        :return: None
        """
        if len(self.pending_signals[chain_name]):
            block_number = self.query_block_number_for_chain_noexcept(chain_name)
            required_confirmations = self.get_block_confirmations(chain_name)
            for tx_hash in dict(self.pending_signals[chain_name]):
                message = self.pending_signals[chain_name][tx_hash]
                result = message["params"]["result"]
                message_block_number = int(result["blockNumber"], base=16)
                if block_number - message_block_number >= required_confirmations:
                    # Message is old enough to be moved to final list
                    for chat_id in self.final_signals:
                        messages = []
                        if chain_name in self.final_signals[chat_id]:
                            messages = self.final_signals[chat_id][chain_name]
                        messages.append(message)
                        self.final_signals[chat_id][chain_name] = messages
                    # Remove from processing queue
                    del self.pending_signals[chain_name][tx_hash]

    async def wallet_update_signals_for_chain(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        connection: Any,
        chain_name: str,
    ) -> None:
        """
        Monitor event signals for given chain.
        :param connection: connection instance to use.
        :param chain_name: chain to monitor.
        :return: None
        """
        subscription = await self.subscribe_to_chain(connection, chain_name)
        while context.application.running:
            try:
                message = await connection.receive_json(timeout=5)
            except asyncio.TimeoutError:
                # Ignore exceptions from timeout
                # This means there was nothing available to read from the socket
                continue
            finally:
                self.process_pending_signals_for_chain(chain_name)

            try:
                result = message["params"]["result"]
                if result["removed"]:
                    if result["transactionHash"] in self.pending_signals[chain_name]:
                        del self.pending_signals[chain_name][result["transactionHash"]]
                else:
                    self.pending_signals[chain_name][
                        result["transactionHash"]
                    ] = message
            except KeyError:
                # Message is not valid, possibly an error condition from server
                logger.exception(message)

            # Update subscriptions if new wallet was added or removed
            if self.wallet_updated:
                self.wallet_updated = False
                return await self.unsubscribe_from_chain_noexcept(
                    connection, subscription
                )

    async def wallet_update_signals_for_chain_loop(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        session: ClientSession,
        chain_name: str,
    ) -> None:
        """
        Check for ERC20 Transfer events on given chain.
        :param chain_name: chain to query for events.
        :return: None
        """
        while context.application.running:
            try:
                async with session.ws_connect(
                    self.config["chains"][chain_name]["url"]
                ) as connection:
                    await self.wallet_update_signals_for_chain(
                        context, connection, chain_name
                    )
            except:
                logger.exception("Connection exception")
                # Sleep before retry
                await asyncio.sleep(delay=5)

    async def wallet_update_signals(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Check for ERC20 Transfer events.
        :return: None
        """
        async with ClientSession() as session:
            tasks = []
            for chain_name in self.config["chains"]:
                tasks.append(
                    asyncio.create_task(
                        self.wallet_update_signals_for_chain_loop(
                            context,
                            session,
                            chain_name,
                        )
                    )
                )
            await asyncio.gather(*tasks)

    async def wallet_display_signals(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Parse final signals and show to user.
        :return: None
        """

        def address_from_topic(topic: str) -> str:
            return f"0x{topic[26:]}"

        alerts = []
        for chain_name in self.final_signals[context.job.chat_id]:
            symbol, decimals = self.query_token_details_for_chain(chain_name)
            for message in self.final_signals[context.job.chat_id][chain_name]:
                result = message["params"]["result"]
                wallet_address = Web3.toChecksumAddress(
                    address_from_topic(result["topics"][2])
                )
                wallet_name = self.wallet_address_to_name(wallet_address)
                amount = Web3.toInt(hexstr=result["data"])
                alert = (
                    f"WALLET ALERT\n"
                    f"{wallet_name}({chain_name}): {Web3.fromWei(amount * 10 ** (18 - decimals), 'ether')} {symbol}"
                )
                alerts.append(alert)

        # Remove processed signals
        self.final_signals[context.job.chat_id] = {}

        for alert in alerts:
            await context.bot.send_message(chat_id=context.job.chat_id, text=alert)

    async def read_scanner_sla(self, *args, **kwargs) -> None:
        """
        Read scanner nodes SLA.
        :return: None
        """
        tasks = []
        scanner_next_sla = {}
        async with ClientSession() as session:
            for friendly_name in self.user_config["scanners"]:
                tasks.append(
                    asyncio.create_task(
                        self.forta_fetch_sla(
                            session,
                            self.user_config["scanners"][friendly_name],
                            friendly_name,
                        )
                    )
                )
            for task in asyncio.as_completed(tasks):
                try:
                    friendly_name, sla = await task
                except:
                    logger.exception(f"Request failed")
                else:
                    scanner_next_sla[friendly_name] = float(sla["statistics"]["avg"])
            self.scanner_current_sla = scanner_next_sla

    async def scanner_check_alerts(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Check cached scanner SLA and produce alerts.
        :return: None
        """
        config_threshold = float(self.user_config["threshold"])

        alerts = []
        for friendly_name in self.scanner_current_sla:
            if (
                context.job.chat_id in self.scanner_prev_sla
                and friendly_name in self.scanner_prev_sla[context.job.chat_id]
            ):
                threshold = min(
                    config_threshold,
                    self.scanner_prev_sla[context.job.chat_id][friendly_name],
                )
            else:
                threshold = config_threshold

            if self.scanner_current_sla[friendly_name] < threshold:
                alert = (
                    f"SCANNER ALERT\n"
                    f"{friendly_name}: {self.scanner_current_sla[friendly_name]}"
                )
                alerts.append(alert)

        # Record prev SLA in order to produce alerts only if conditions degrade
        self.scanner_prev_sla[context.job.chat_id] = copy.deepcopy(
            self.scanner_current_sla
        )

        for alert in alerts:
            await context.bot.send_message(chat_id=context.job.chat_id, text=alert)

    async def parse_action_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Add a job to monitor scanner nodes and wallet transfers.
        :return: None
        """

        # Prepare scanner monitor jobs
        remove_job_if_exists(context, self.scanner_reader_job_name(update))
        pooling_interval = float(self.config["scanner_pool_interval"])
        context.job_queue.run_repeating(
            callback=self.scanner_check_alerts,
            interval=pooling_interval // 2,
            chat_id=update.message.chat_id,
            name=self.scanner_reader_job_name(update),
        )

        # Prepare wallet monitor jobs
        remove_job_if_exists(context, self.wallet_reader_job_name(update))
        pooling_interval = float(self.config["wallet_pool_interval"])
        context.job_queue.run_repeating(
            callback=self.wallet_display_signals,
            interval=pooling_interval // 2,
            chat_id=update.message.chat_id,
            name=self.wallet_reader_job_name(update),
        )
        self.final_signals[update.message.chat_id] = {}

        await update.message.reply_text("Monitoring started")

    async def parse_action_stop(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Stop monitoring scanner nodes and wallet transfers.
        :return: None
        """
        remove_job_if_exists(context, self.scanner_reader_job_name(update))

        remove_job_if_exists(context, self.wallet_reader_job_name(update))
        del self.final_signals[update.message.chat_id]

        await update.message.reply_text("Monitoring stopped")

    async def parse_action_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Print usage.
        :return: None
        """
        await update.message.reply_text(text=HELP)

    async def do_actions(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        actions: Any,
        args: List[str],
    ) -> None:
        if args:
            try:
                await actions[args[0]](update, context, args[1:])
            except KeyError:
                logger.exception(f"Unknown action: {args[0]}")
                await update.message.reply_text(
                    text=f"Unknown action: {args[0]}\n{actions.keys()}"
                )
            except:
                logger.exception("Operation failed")
                await update.message.reply_text(text="Operation failed")
        else:
            await update.message.reply_text(
                text=f"Missing 'action' parameter\n{actions.keys()}"
            )

    async def parse_action_scanner_add(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Add/Update scanner.
        :param args: options list, syntax "scanner add :friendly-name: :address:".
        :return: None.
        """
        try:
            friendly_name = args[0]
            address = args[1]
        except IndexError:
            await update.message.reply_text(
                text="Invalid action 'scanner add' arguments"
            )
        else:
            if not validate_name(friendly_name):
                await update.message.reply_text(text="Friendly name not valid")
            elif not validate_address(address):
                await update.message.reply_text(text="Scanner address format not valid")
            else:
                try:
                    async with ClientSession() as session:
                        await self.forta_fetch_sla(session, address)
                except:
                    await update.message.reply_text(text="Scanner address not valid")
                else:
                    self.user_config["scanners"][friendly_name] = address
                    async with aiofiles.open(self.config["db_path"], "w") as outfile:
                        await outfile.write(json.dumps(self.user_config))

                    await update.message.reply_text(
                        text=f"SCANNER UPDATED\n{friendly_name}: {address}"
                    )

    async def parse_action_scanner_remove(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Remove scanner.
        :param args: options list, syntax "scanner remove :friendly-name:".
        :return: None.
        """
        try:
            friendly_name = args[0]
        except IndexError:
            await update.message.reply_text(
                text="Invalid action 'scanner remove' arguments"
            )
        else:
            if not validate_name(friendly_name):
                await update.message.reply_text(text="Friendly name not valid")
            elif not friendly_name in self.user_config["scanners"]:
                await update.message.reply_text(text="Unknown scanner name")
            else:
                del self.user_config["scanners"][friendly_name]
                async with aiofiles.open(self.config["db_path"], "w") as outfile:
                    await outfile.write(json.dumps(self.user_config))

                await update.message.reply_text(
                    text=f"SCANNER REMOVED\n{friendly_name}"
                )

    async def parse_action_scanner_alert(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Set SLA alert threshold.
        :param args: options list, syntax "scanner alert :sla-threshold:".
        :return: None.
        """
        try:
            threshold = float(args[0])
        except IndexError:
            await update.message.reply_text(
                text="Invalid action 'scanner alert' arguments"
            )
        except ValueError:
            await update.message.reply_text(text="Invalid number format")
        else:
            if threshold <= 0 or threshold >= 1:
                await update.message.reply_text(text="Threshold interval is (0..1)")
            else:
                # Clear saved SLA to produce fresh alerts
                self.scanner_prev_sla.clear()

                self.user_config["threshold"] = threshold
                async with aiofiles.open(self.config["db_path"], "w") as outfile:
                    await outfile.write(json.dumps(self.user_config))

                await update.message.reply_text(
                    text=f"ALERT UPDATED\nsla-threshold: {threshold}"
                )

    async def parse_action_scanner_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Dump SLA for all scanner nodes.
        """
        status = (
            "ACTIVE"
            if job_exist(context, self.scanner_reader_job_name(update))
            else "INACTIVE"
        )
        if not len(self.scanner_current_sla):
            await self.read_scanner_sla()

        result = f"SCANNER STATUS ({status})\n"
        for friendly_name in self.scanner_current_sla:
            result = (
                f"{result}\n{friendly_name}: {self.scanner_current_sla[friendly_name]}"
            )
        result = f"{result}\nCOUNT: {len(self.scanner_current_sla)}"

        await update.message.reply_text(text=result)

    async def parse_action_scanner_list(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Dump scanner nodes config information.
        """
        result = f"SCANNER CONFIG (SLA-THRESHOLD: {self.user_config['threshold']})\n"
        for friendly_name in self.user_config["scanners"]:
            result = f"{result}\n{friendly_name}:\n  * {self.user_config['scanners'][friendly_name]}"
        result = f"{result}\nCOUNT: {len(self.user_config['scanners'])}"
        await update.message.reply_text(text=result)

    async def parse_action_scanner(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Parse 'scanner' action.
        :return: None
        """
        forta_actions_scanner = {
            "add": self.parse_action_scanner_add,
            "remove": self.parse_action_scanner_remove,
            "alert": self.parse_action_scanner_alert,
            "status": self.parse_action_scanner_status,
            "list": self.parse_action_scanner_list,
        }
        await self.do_actions(update, context, forta_actions_scanner, args)

    async def parse_action_wallet_add(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Add/Update user wallet.
        :param args: options list, syntax "wallet add :friendly-name: :address:".
        :return: None.
        """
        try:
            friendly_name = args[0]
            address = args[1]
        except IndexError:
            await update.message.reply_text(
                text="Invalid action 'wallet add' arguments"
            )
        else:
            if not validate_name(friendly_name):
                await update.message.reply_text(text="Friendly name not valid")
            elif not validate_address(address):
                await update.message.reply_text(text="Wallet address format not valid")
            else:
                # Trigger subscription reset
                self.wallet_updated = True

                self.user_config["wallets"][friendly_name] = address
                async with aiofiles.open(self.config["db_path"], "w") as outfile:
                    await outfile.write(json.dumps(self.user_config))

                await update.message.reply_text(
                    text=f"WALLET UPDATED\n{friendly_name}: {address}"
                )

    async def parse_action_wallet_remove(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Remove user wallet.
        :param args: options list, syntax "wallet remove :friendly-name:".
        :return: None.
        """
        try:
            friendly_name = args[0]
        except IndexError:
            await update.message.reply_text(
                text="Invalid action 'wallet remove' arguments"
            )
        else:
            if not friendly_name in self.user_config["wallets"]:
                await update.message.reply_text(text="Unknown wallet name")
            else:
                # Trigger subscription reset
                self.wallet_updated = True

                del self.user_config["wallets"][friendly_name]
                async with aiofiles.open(self.config["db_path"], "w") as outfile:
                    await outfile.write(json.dumps(self.user_config))

                await update.message.reply_text(text=f"WALLET REMOVED\n{friendly_name}")

    async def parse_action_wallet_balance(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Show wallet balance.
        :param args: options list, syntax "wallet balance :friendly-name:".
        :return: None.
        """
        try:
            friendly_name = args[0]
        except IndexError:
            await update.message.reply_text(
                text="Invalid action 'wallet balance' arguments"
            )
        else:
            if not friendly_name in self.user_config["wallets"]:
                await update.message.reply_text(text="Unknown wallet name")
            else:
                result = f"WALLET BALANCE ({friendly_name}):\n"
                for chain_name in self.config["chains"]:
                    symbol, decimals = self.query_token_details_for_chain(chain_name)
                    balance = self.query_account_balance_for_chain(
                        chain_name, friendly_name
                    )

                    result = f"{result}\n{chain_name}: {Web3.fromWei(balance * 10 ** (18 - decimals), 'ether')} {symbol}"

                await update.message.reply_text(text=result)

    async def parse_action_wallet_list(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Show all configured wallets.
        :return: None
        """
        result = "WALLET CONFIG\n"
        for wallet_name in self.user_config["wallets"]:
            result = (
                f"{result}\n{wallet_name}: {self.user_config['wallets'][wallet_name]}"
            )
        await update.message.reply_text(text=result)

    async def parse_action_wallet(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Parse 'wallet' action.
        :return: None
        """
        forta_actions_wallet = {
            "add": self.parse_action_wallet_add,
            "remove": self.parse_action_wallet_remove,
            "balance": self.parse_action_wallet_balance,
            "list": self.parse_action_wallet_list,
        }
        await self.do_actions(update, context, forta_actions_wallet, args)

    async def parse_action_chain_list(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Show all configured chains.
        :return: None
        """
        result = "CHAIN CONFIG\n"
        for chain_name in self.config["chains"]:
            result = (
                f"{result}\n{chain_name}:\n"
                f"    * url: {self.config['chains'][chain_name]['url']}\n"
                f"    * token: {self.config['chains'][chain_name]['token']}"
            )
        await update.message.reply_text(text=result)

    async def parse_action_chain(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Parse 'chain' action.
        :return: None
        """
        forta_actions_chain = {"list": self.parse_action_chain_list}
        await self.do_actions(update, context, forta_actions_chain, args)

    async def execute_action(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Entry point for forta extension. Overrides 'ExtensionBase.execute_action'.
        :return: None
        """
        forta_actions = {
            "scanner": self.parse_action_scanner,
            "wallet": self.parse_action_wallet,
            "chain": self.parse_action_chain,
            "start": self.parse_action_start,
            "stop": self.parse_action_stop,
            "help": self.parse_action_help,
        }
        await self.do_actions(update, context, forta_actions, context.args)

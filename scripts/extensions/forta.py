"""
Forta is the extension used to monitor forta-network scanner nodes.
"""
import logging
import json
import requests

from typing import Any, List

from telegram import Update
from telegram.ext import ContextTypes
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
    Set SLA threshold value for generating alerts (default: 0.95).
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

    def __init__(self, forta_config) -> None:
        """
        Init all variables and objects the bot needs to work.
        :param forta_config: forta specific configuration.
        """
        self.config = forta_config
        try:
            self.scanner_status = {}
            self.user_config = {"scanners": {}, "wallets": {}, "threshold": "0.95"}
            with open(self.config["db_path"], "r") as infile:
                self.user_config = json.load(infile)
        except:
            # Non critical error, as first time run it is expected
            # that this file is missing
            logger.exception(f"Missing {self.config['db_path']}")

        self.ERC20_ABI = {}
        with open("./scripts/extensions/abis/ERC20.json", "r") as infile:
            self.ERC20_ABI = json.load(infile)

    def execute_request(self, address: str) -> str:
        """
        Performs a get request to forta explorer service to obtain SLA.
        :param address: scanner node address to query.
        :return: http response as string.
        """
        return requests.get(f"{self.config['url']}{address}")

    def job_name(self) -> str:
        """
        Creates an unique job name for this extension.
        :return: job name as string.
        """
        return "FORTA"

    async def execute_pooling(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Pool on forta SLA.
        :return: None
        """
        job = context.job
        for friendly_name in self.user_config["scanners"]:
            address = self.user_config["scanners"][friendly_name]
            sla = self.execute_request(address)
            if sla.status_code == 200:
                json_sla = json.loads(sla.text)
                if friendly_name in self.scanner_status:
                    if float(self.scanner_status[friendly_name]) <= float(
                        json_sla["statistics"]["avg"]
                    ):
                        # Only produce alerts if conditions degrade
                        self.scanner_status[friendly_name] = json_sla["statistics"][
                            "avg"
                        ]
                        continue

                if float(json_sla["statistics"]["avg"]) <= float(
                    self.user_config["threshold"]
                ):
                    alert = (
                        f"SCANNER ALERT\n"
                        f"{friendly_name}: {json_sla['statistics']['avg']}"
                    )
                    logger.info(f"New alert: {alert}")
                    await context.bot.send_message(chat_id=job.chat_id, text=alert)
                # Remember this value so we produce new allerts only if SLA degrades
                self.scanner_status[friendly_name] = json_sla["statistics"]["avg"]
            else:
                logger.error(f"Request failed: {friendly_name} {sla}")
                await context.bot.send_message(
                    chat_id=job.chat_id,
                    text=(f"SCANNER ALERT\n{friendly_name}: request failed"),
                )

    def remove_job_if_exists(self, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        Remove forta monitor job.
        :return: True if job was found and removed, False otherwise.
        """
        return remove_job_if_exists(context, self.job_name())

    async def parse_action_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Add a job to monitor scanner nodes.
        :return: None
        """
        job_removed = self.remove_job_if_exists(context)
        logger.info(f"Monitor job removed (result:{job_removed})")

        pooling_interval = float(self.config["pooling_interval"])
        context.job_queue.run_repeating(
            callback=self.execute_pooling,
            interval=pooling_interval,
            chat_id=update.message.chat_id,
            name=self.job_name(),
        )
        await update.message.reply_text("Monitoring started")

    async def parse_action_stop(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Stop monitoring scanner nodes.
        :return: None
        """
        job_removed = self.remove_job_if_exists(context)
        logger.info(f"Monitor job removed (result:{job_removed})")

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
            if not validate_name(friendly_name):
                await update.message.reply_text(text="Friendly name not valid")
            elif not validate_address(address):
                await update.message.reply_text(text="Scanner address format not valid")
            else:
                sla = self.execute_request(address)
                if sla.status_code != 200:
                    await update.message.reply_text(text="Scanner address not valid")
                else:
                    self.user_config["scanners"][friendly_name] = address
                    with open(self.config["db_path"], "w") as outfile:
                        json.dump(self.user_config, outfile)

                    await update.message.reply_text(
                        text=f"SCANNER UPDATED\n{friendly_name}: {address}"
                    )
        except IndexError:
            logger.exception("Invalid action 'scanner add' arguments")
            await update.message.reply_text(
                text="Invalid action 'scanner add' arguments"
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
            if not validate_name(friendly_name):
                await update.message.reply_text(text="Friendly name not valid")
            elif not friendly_name in self.user_config["scanners"]:
                await update.message.reply_text(text="Unknown scanner name")
            else:
                del self.user_config["scanners"][friendly_name]
                if friendly_name in self.scanner_status:
                    del self.scanner_status[friendly_name]
                with open(self.config["db_path"], "w") as outfile:
                    json.dump(self.user_config, outfile)

                await update.message.reply_text(
                    text=f"SCANNER REMOVED\n{friendly_name}"
                )
        except IndexError:
            logger.exception("Invalid action 'scanner remove' arguments")
            await update.message.reply_text(
                text="Invalid action 'scanner remove' arguments"
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
            if threshold <= 0 or threshold >= 1:
                await update.message.reply_text(text="Threshold interval is (0..1)")
            self.user_config["threshold"] = threshold
            with open(self.config["db_path"], "w") as outfile:
                json.dump(self.user_config, outfile)
            self.scanner_status.clear()
            await update.message.reply_text(
                text=f"ALERT UPDATED\nsla-threshold: {threshold}"
            )
        except IndexError:
            logger.exception("Invalid action 'scanner alert' arguments")
            await update.message.reply_text(
                text="Invalid action 'scanner alert' arguments"
            )
        except ValueError:
            logger.exception("Invalid number value")
            await update.message.reply_text(text="Invalid number value")

    async def parse_action_scanner_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Dump SLA for all scanner nodes.
        """
        status = "ACTIVE" if job_exist(context, self.job_name()) else "INACTIVE"
        result = f"SCANNER STATUS ({status})\n"
        for friendly_name in self.user_config["scanners"]:
            sla = self.execute_request(self.user_config["scanners"][friendly_name])
            if sla.status_code == 200:
                json_sla = json.loads(sla.text)
                result = f"{result}\n{friendly_name}: {json_sla['statistics']['avg']}"
            else:
                logger.error(f"Failed request for: {friendly_name} {sla}")
                result = f"{result}\n{friendly_name}: FAILED"
        result = f"{result}\nCOUNT: {len(self.user_config['scanners'])}"
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
            if not validate_name(friendly_name):
                await update.message.reply_text(text="Friendly name not valid")
            elif not validate_address(address):
                await update.message.reply_text(text="Wallet address format not valid")
            else:
                self.user_config["wallets"][friendly_name] = address
                with open(self.config["db_path"], "w") as outfile:
                    json.dump(self.user_config, outfile)

                await update.message.reply_text(
                    text=f"WALLET UPDATED\n{friendly_name}: {address}"
                )
        except IndexError:
            logger.exception("Invalid action 'wallet add' arguments")
            await update.message.reply_text(
                text="Invalid action 'wallet add' arguments"
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
            if not friendly_name in self.user_config["wallets"]:
                await update.message.reply_text(text="Unknown wallet name")
            else:
                del self.user_config["wallets"][friendly_name]
                with open(self.config["db_path"], "w") as outfile:
                    json.dump(self.user_config, outfile)

                await update.message.reply_text(text=f"WALLET REMOVED\n{friendly_name}")
        except IndexError:
            logger.exception("Invalid action 'wallet remove' arguments")
            await update.message.reply_text(
                text="Invalid action 'wallet remove' arguments"
            )

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
            if not friendly_name in self.user_config["wallets"]:
                await update.message.reply_text(text="Unknown wallet name")
            else:
                result = f"WALLET BALANCE ({friendly_name}):\n"
                for chain_name in self.config["chains"]:
                    provider = Web3(
                        Web3.WebsocketProvider(self.config["chains"][chain_name]["url"])
                    )
                    if not provider.isConnected():
                        result = f"{result}\n{chain_name}: connection failed"
                    else:
                        # Query balanceOf for wallet-token pair
                        contract = provider.eth.contract(
                            self.config["chains"][chain_name]["token"],
                            abi=self.ERC20_ABI,
                        )
                        symbol = contract.functions.symbol().call()
                        decimals = contract.functions.decimals().call()

                        wallet = self.user_config["wallets"][friendly_name]
                        balance = contract.functions.balanceOf(wallet).call()

                        result = f"{result}\n{chain_name}: {Web3.fromWei(balance * 10 ** (18 - decimals), 'ether')} {symbol}"

                await update.message.reply_text(text=result)
        except IndexError:
            logger.exception("Invalid action 'wallet balance' arguments")
            await update.message.reply_text(
                text="Invalid action 'wallet balance' arguments"
            )

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

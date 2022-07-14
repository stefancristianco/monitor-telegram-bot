"""
[WIP]
Extension to monitor ERC20 SC. Provides allerts when amount of funds have changed.
"""
import logging
import json

from typing import Any, List

from telegram import Update
from telegram.ext import ContextTypes

from web3 import HTTPProvider, Web3

from extensions.extension_base import ExtensionBase
from helpers.utils import (
    validate_address,
    validate_name,
    validate_url,
    remove_job_if_exists,
)

logger = logging.getLogger(__name__)


class Erc20(ExtensionBase):
    """
    ERC20 extension.
    Will send alerts when new transfers occur to given wallet.
    """

    def make_erc20_entries(
        self, provider: HTTPProvider, wallet: str, contract: str
    ) -> Any:
        contract = provider.eth.contract(
            contract,
            abi=self.ERC20_ABI,
        )
        symbol = contract.functions.symbol().call()
        decimals = contract.functions.decimals().call()
        incoming_filter = contract.events.Transfer.createFilter(
            fromBlock="latest", argument_filters={"to": wallet}
        )
        outgoing_filter = contract.events.Transfer.createFilter(
            fromBlock="latest", argument_filters={"from": wallet}
        )
        return {
            "contract": contract,
            "symbol": symbol,
            "decimals": decimals,
            "incoming_filter": incoming_filter,
            "outgoing_filter": outgoing_filter,
        }

    def update_chain(self, chain_name: str, chain_info: Any) -> None:
        """
        Update chain information.
        :param chain_name: new chain name.
        :param chain_info: chain information.
        """
        provider = Web3(Web3.HTTPProvider(chain_info["url"]))
        if not provider.isConnected():
            raise Exception("Invalid chain url")
        tmp = {"provider": provider, "monitor": {}}
        for wt_name in chain_info["monitor"]:
            contract = chain_info["monitor"][wt_name]["contract"]
            wallet = chain_info["monitor"][wt_name]["wallet"]
            tmp["monitor"][wt_name] = self.make_erc20_entries(
                provider, wallet, contract
            )
        self.chains[chain_name] = tmp

    def __init__(self, erc20_config) -> None:
        """
        Init all variables and objects.
        """
        self.config = erc20_config
        try:
            self.erc20_info = {"chains": {}}
            with open(self.config["db_path"], "r") as infile:
                self.erc20_info = json.load(infile)
        except:
            # Non critical error, as first time run it is expected
            # that this file is missing
            logger.exception(f"Missing {self.config['db_path']}")

        self.ERC20_ABI = {}
        with open("./scripts/extensions/abis/ERC20.json", "r") as infile:
            self.ERC20_ABI = json.load(infile)

        self.chains = {}
        for chain_name in self.erc20_info["chains"]:
            self.update_chain(chain_name, self.erc20_info["chains"][chain_name])

    def parse_action_chain_connect_validate_options(self, opt: Any) -> bool:
        """
        Validate all options for action "connect".
        :param opt: dictionary of options to check.
        :return: True if all options are valid, False otherwise.
        """
        try:
            if not validate_name(opt["name"]):
                logger.error("Name not valid")
                return False
            if not validate_url(opt["url"]):
                logger.error("Invalid chain url")
                return False
            return True
        except:
            logger.exception("Error during 'connect' options validation")
        return False

    async def parse_action_chain_connect(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Connect to a new chain.
        If the chain already exists, old connection will be killed and new connection will be established.
        :param args: list of options for action "connect".
        :return: None
        """
        if args:
            try:
                opt = {arg.split("=")[0]: arg.split("=")[1] for arg in args}
                if self.parse_action_chain_connect_validate_options(opt):
                    # Close old connection (if any) and open new one
                    chain_info = {"url": opt["url"], "monitor": {}}
                    if opt["name"] in self.erc20_info["chains"]:
                        chain_info["monitor"] = self.erc20_info["chains"][opt["name"]][
                            "monitor"
                        ]
                    self.update_chain(opt["name"], chain_info)
                    self.erc20_info["chains"][opt["name"]] = chain_info

                    # Save the new chain
                    with open(self.config["db_path"], "w") as outfile:
                        json.dump(self.erc20_info, outfile)
                    await update.message.reply_text(
                        text=f"CHAIN UPDATED:\n{opt['name']}: {opt['url']}"
                    )
                else:
                    await update.message.reply_text(text="Invalid connect arguments")
            except IndexError:
                await update.message.reply_text(
                    text="Invalid connect 'action' arguments"
                )
            except:
                logger.exception("Failed to connect chain")
                await update.message.reply_text(text="Operation failed")
        else:
            await update.message.reply_text(text="Missing connect 'action' arguments")

    async def parse_action_chain_disconnect(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Disconnect from chain.
        :param args: chain name to disconnect.
        :return: None
        """
        if args:
            if args[0] in self.chains:
                del self.chains[args[0]]
                del self.erc20_info["chains"][args[0]]
                # Save new configuration
                with open(self.config["db_path"], "w") as outfile:
                    json.dump(self.erc20_info, outfile)
                await update.message.reply_text(text=f"CHAIN REMOVED:\n{args[0]}")
            else:
                await update.message.reply_text(text="Missing chain")
        else:
            await update.message.reply_text(
                text="Missing disconnect 'action' arguments"
            )

    async def parse_action_chain_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Check connection to endpoints.
        :return: None
        """
        result = "CHAIN STATUS:\n"
        for chain_name in self.chains:
            status = (
                "active"
                if self.chains[chain_name]["provider"].isConnected()
                else "inactive"
            )
            result = f"{result}\n{chain_name}: {status}"
        await update.message.reply_text(text=result)

    async def parse_action_chain_list(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Dump configured chains.
        :return: None
        """
        result = "CHAIN LIST:\n"
        for chain_name in self.erc20_info["chains"]:
            result = f"{result}\n{chain_name}: {self.erc20_info['chains'][chain_name]['url']}"
        await update.message.reply_text(text=result)

    async def parse_action_chain(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Manage chains.
        :param args: action arguments.
        :return: None
        """
        if args:
            chain_actions = {
                "connect": {"func": self.parse_action_chain_connect},
                "disconnect": {"func": self.parse_action_chain_disconnect},
                "status": {"func": self.parse_action_chain_status},
                "list": {"func": self.parse_action_chain_list},
            }
            try:
                await chain_actions[args[0]]["func"](update, context, args[1:])
            except:
                logger.exception("Failed to perform 'chain' action")
                await update.message.reply_text(text="Unknown chain 'action' parameter")
        else:
            await update.message.reply_text(text="Missing chain 'action' arguments")

    def parse_action_token_add_validate_options(self, opt) -> bool:
        """
        Validate all options for action token "add".
        :param opt: dictionary of options to check.
        :return: True if all options are valid, False otherwise.
        """
        try:
            if not validate_address(opt["contract"]):
                logger.error("Contract address not valid")
                return False
            if not validate_address(opt["wallet"]):
                logger.error("Wallet address not valid")
                return False
            if not validate_name(opt["name"]):
                logger.error("Name not valid")
                return False
            if not validate_name(opt["chain"]):
                logger.error("Chain name not valid")
                return False
            if not opt["chain"] in self.erc20_info["chains"]:
                logger.error("Unknown chain name")
                return False
            return True
        except:
            logger.exception("Error during options validation")
        return False

    async def parse_action_token_add(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Add new wallet-token pair for monitoring.
        :param args: list of options for action "add".
        :return: None
        """
        if args:
            try:
                opt = {arg.split("=")[0]: arg.split("=")[1] for arg in args}
                if self.parse_action_token_add_validate_options(opt):
                    provider = self.chains[opt["chain"]]["provider"]
                    contract = opt["contract"]
                    wallet = opt["wallet"]

                    self.chains[opt["chain"]]["monitor"][
                        opt["name"]
                    ] = self.make_erc20_entries(provider, wallet, contract)

                    # Save the new token-wallet pair
                    self.erc20_info["chains"][opt["chain"]]["monitor"][opt["name"]] = {
                        "wallet": opt["wallet"],
                        "contract": opt["contract"],
                    }
                    with open(self.config["db_path"], "w") as outfile:
                        json.dump(self.erc20_info, outfile)

                    # Send message to user
                    result = f"MONITOR UPDATED:\n"
                    result = f"{result}\n{opt['chain']} ({self.erc20_info['chains'][opt['chain']]['url']}):"
                    result = f"{result}\n  * {opt['name']}"
                    result = f"{result}\n     * wallet: {self.erc20_info['chains'][opt['chain']]['monitor'][opt['name']]['wallet']}"
                    result = f"{result}\n     * contract: {self.erc20_info['chains'][opt['chain']]['monitor'][opt['name']]['contract']}"
                    await update.message.reply_text(text=result)
                else:
                    await update.message.reply_text(text="Invalid token add arguments")
            except IndexError:
                await update.message.reply_text(
                    text="Invalid token add 'action' arguments"
                )
            except:
                logger.exception("Failed to add new monitor wallet-token pair")
                await update.message.reply_text(text="Operation failed")
        else:
            await update.message.reply_text(text="Missing token add 'action' arguments")

    def parse_action_token_pair_validate_options(self, opt) -> bool:
        """
        Validate all options for action token "remove".
        :param opt: dictionary of options to check.
        :return: True if all options are valid, False otherwise.
        """
        try:
            if not validate_name(opt["name"]):
                logger.error("Name not valid")
                return False
            if not validate_name(opt["chain"]):
                logger.error("Chain name not valid")
                return False
            if not opt["chain"] in self.erc20_info["chains"]:
                logger.error("Unknown chain name")
                return False
            if not opt["name"] in self.erc20_info["chains"][opt["chain"]]["monitor"]:
                logger.error("Unknown wallet-token name")
                return False
            return True
        except:
            logger.exception("Error during options validation")
        return False

    async def parse_action_token_remove(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Remove wallet-token pair and stop monitoring it.
        :param args: list of options for action "remove".
        :return: None
        """
        if args:
            try:
                opt = {arg.split("=")[0]: arg.split("=")[1] for arg in args}
                if self.parse_action_token_pair_validate_options(opt):
                    # Remove wallet-token pair from db
                    del self.erc20_info["chains"][opt["chain"]]["monitor"][opt["name"]]
                    with open(self.config["db_path"], "w") as outfile:
                        json.dump(self.erc20_info, outfile)

                    result = f"MONITOR REMOVED:\n{opt['chain']}: {opt['name']}"
                    await update.message.reply_text(text=result)
                else:
                    await update.message.reply_text(
                        text="Invalid token remove arguments"
                    )
            except IndexError:
                await update.message.reply_text(
                    text="Invalid token remove 'action' arguments"
                )
            except:
                logger.exception("Failed to remove wallet-token pair")
                await update.message.reply_text(text="Operation failed")
        else:
            await update.message.reply_text(
                text="Missing token remove 'action' arguments"
            )

    async def parse_action_token_balance(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Query balance for wallet-token pair.
        :param args: list of options for action "balance".
        :return: None
        """
        if args:
            try:
                opt = {arg.split("=")[0]: arg.split("=")[1] for arg in args}
                if self.parse_action_token_pair_validate_options(opt):
                    contract = self.chains[opt["chain"]]["monitor"][opt["name"]][
                        "contract"
                    ]
                    symbol = self.chains[opt["chain"]]["monitor"][opt["name"]]["symbol"]
                    decimals = self.chains[opt["chain"]]["monitor"][opt["name"]][
                        "decimals"
                    ]
                    wallet = self.erc20_info["chains"][opt["chain"]]["monitor"][
                        opt["name"]
                    ]["wallet"]

                    # Query balanceOf for wallet-token pair
                    balance = contract.functions.balanceOf(wallet).call()
                    result = f"BALANCE_OF:\n{opt['chain']} - {opt['name']}: {Web3.fromWei(balance * 10 ** (18 - decimals), 'ether')} {symbol}"
                    await update.message.reply_text(text=result)
                else:
                    await update.message.reply_text(
                        text="Invalid token balance arguments"
                    )
            except IndexError:
                await update.message.reply_text(
                    text="Invalid token balance 'action' arguments"
                )
            except:
                logger.exception("Failed query wallet-token balance")
                await update.message.reply_text(text="Operation failed")
        else:
            await update.message.reply_text(
                text="Missing token balance 'action' arguments"
            )

    async def parse_action_token_list(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Dump wallet-token pairs.
        :return: None
        """
        result = "MONITOR LIST:\n"
        for chain_name in self.erc20_info["chains"]:
            result = f"{result}\n{chain_name} ({self.erc20_info['chains'][chain_name]['url']}):"
            for wt_name in self.erc20_info["chains"][chain_name]["monitor"]:
                result = f"{result}\n  * {wt_name}:"
                result = f"{result}\n     * wallet({self.erc20_info['chains'][chain_name]['monitor'][wt_name]['wallet']})"
                result = f"{result}\n     * contract({self.erc20_info['chains'][chain_name]['monitor'][wt_name]['contract']})"

        await update.message.reply_text(text=result)

    async def parse_action_token(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        """
        Manage token commands.
        :param args: action arguments.
        :return: None
        """
        if args:
            token_actions = {
                "add": {"func": self.parse_action_token_add},
                "remove": {"func": self.parse_action_token_remove},
                "balance": {"func": self.parse_action_token_balance},
                "list": {"func": self.parse_action_token_list},
            }
            try:
                await token_actions[args[0]]["func"](update, context, args[1:])
            except:
                logger.exception("Failed to perform token action")
                await update.message.reply_text(text="Unknown token 'action' parameter")
        else:
            await update.message.reply_text(text="Missing token 'action' arguments")

    def job_name(self, update: Update) -> str:
        """
        Creates an unique job name for this extension.
        :return: job name as string.
        """
        chat_id = update.message.chat_id
        return f"ERC20:{chat_id}"

    def remove_job_if_exists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        Remove ERC20 monitor job.
        :return: True if job was found and removed, False otherwise.
        """
        return remove_job_if_exists(context, self.job_name(update))

    async def execute_pooling(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Pool on ERC20 transfers.
        TODO take into account for block reorg
        TODO change to eth_subscribe()
        """
        for chain_name in self.chains:
            for wt_name in self.chains[chain_name]["monitor"]:
                incoming_filter = self.chains[chain_name]["monitor"][wt_name][
                    "incoming_filter"
                ]
                outgoing_filter = self.chains[chain_name]["monitor"][wt_name][
                    "outgoing_filter"
                ]

                async def handle_event(
                    in_out: str,
                    event: Any,
                ) -> None:
                    symbol = self.chains[chain_name]["monitor"][wt_name]["symbol"]
                    decimals = self.chains[chain_name]["monitor"][wt_name]["decimals"]
                    amount = event["args"]["value"]

                    alert = f"TRANSFER ALERT\n{chain_name} - {wt_name}: {in_out}{Web3.fromWei(amount * 10 ** (18 - decimals), 'ether')} {symbol}"

                    logger.info(f"New alert: {alert}")
                    await context.bot.send_message(
                        chat_id=context.job.chat_id, text=alert
                    )

                for event in incoming_filter.get_new_entries():
                    await handle_event("+", event)
                for event in outgoing_filter.get_new_entries():
                    await handle_event("-", event)

    async def parse_action_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Add a job to monitor ERC20 transfers.
        :return: None
        """
        job_removed = self.remove_job_if_exists(update, context)
        logger.info(f"Monitor job removed (result:{job_removed})")

        pooling_interval = float(self.config["pooling_interval"])
        context.job_queue.run_repeating(
            callback=self.execute_pooling,
            interval=pooling_interval,
            chat_id=update.message.chat_id,
            name=self.job_name(update),
        )
        await update.message.reply_text("Monitoring started")

    async def parse_action_stop(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Stop monitoring ERC20 transfers.
        :return: None
        """
        job_removed = self.remove_job_if_exists(update, context)
        logger.info(f"Monitor job removed (result:{job_removed})")

        await update.message.reply_text("Monitoring stopped")

    async def parse_action_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Print usage.
        :return: None
        """
        await update.message.reply_text("TODO")

    async def execute_action(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Entry point for erc20 extension. Overrides 'ExtensionBase.execute_action'.
        :return: None
        """
        eth20_actions = {
            "chain": {"func": self.parse_action_chain},
            "token": {"func": self.parse_action_token},
            "start": {"func": self.parse_action_start},
            "stop": {"func": self.parse_action_stop},
            "help": {"func": self.parse_action_help},
        }

        if context.args:
            try:
                await eth20_actions[context.args[0]]["func"](
                    update, context, context.args[1:]
                )
            except:
                logger.exception("Failed to perform action")
                await update.message.reply_text(text="Unknown 'action' parameter")
        else:
            await update.message.reply_text(text="Missing 'action' parameter")

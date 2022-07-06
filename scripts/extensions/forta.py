"""
Forta is the extension used to monitor forta-network scanner nodes.
"""
import logging
import json
import requests

from typing import List

from telegram import Update
from telegram.ext import ContextTypes

from helpers.utils import validate_address, remove_job_if_exists
from extensions.extension_base import ExtensionBase

logger = logging.getLogger(__name__)


class Forta(ExtensionBase):
    """
    Forta monitor extension logic.
    """

    def __init__(self, forta_config) -> None:
        """
        Init all variables and objects the bot needs to work.
        """
        self.config = forta_config
        try:
            self.agent_status = {}
            self.agent_info = {}
            with open(self.config["db_path"], "r") as infile:
                self.agent_info = json.load(infile)
        except:
            # Non critical error, as first time run it is expected
            # that this file is missing
            logger.exception(f"Missing {self.config['db_path']}")

    def execute_request(self, address: str) -> str:
        return requests.get(f"{self.config['url']}{address}")

    def validate_address(self, address: str) -> bool:
        if not validate_address(address):
            logger.error("Address not valid")
            return False
        sla = self.execute_request(address)
        if sla.status_code != 200:
            logger.error(f"Response: {sla} - {sla.text}")
            return False
        return True

    def job_name(self, update: Update) -> str:
        chat_id = update.message.chat_id
        return f"FORTA:{chat_id}"

    def parse_action_add_validate_options(self, opt) -> bool:
        try:
            if len(opt["name"]) > 100 or len(opt["name"]) == 0:
                logger.error("Name not valid")
                return False
            if float(opt["sla"]) < 0 or float(opt["sla"]) >= 1:
                logger.error("SLA threshold not valid")
                return False
            return self.validate_address(opt["address"])
        except:
            logger.exception("Error during options validation")
        return False

    async def parse_action_add(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        if args:
            try:
                opt = {arg.split("=")[0]: arg.split("=")[1] for arg in args}
                if self.parse_action_add_validate_options(opt):
                    self.agent_info[opt["address"]] = {
                        "name": opt["name"],
                        "sla": opt["sla"],
                    }
                    if opt["address"] in self.agent_status:
                        del self.agent_status[opt["address"]]
                    with open(self.config["db_path"], "w") as outfile:
                        json.dump(self.agent_info, outfile)
                    await update.message.reply_text(
                        text=f"SCANNER UPDATED:\n{opt['address']}"
                    )
                else:
                    await update.message.reply_text(text="Invalid arguments")
            except IndexError:
                await update.message.reply_text(text="Invalid 'action' arguments")
        else:
            await update.message.reply_text(text="Missing 'action' arguments")

    async def parse_action_remove(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
    ) -> None:
        if args:
            try:
                if validate_address(args[0]):
                    if args[0] in self.agent_status:
                        del self.agent_status[args[0]]
                    del self.agent_info[args[0]]
                    with open(self.config["db_path"], "w") as outfile:
                        json.dump(self.agent_info, outfile)
                    await update.message.reply_text(text=f"SCANNER REMOVED:\n{args[0]}")
                else:
                    await update.message.reply_text(text="Address not valid")
            except:
                logger.exception(f"Failed to remove key: {args[0]}")
                await update.message.reply_text(text="Operation failed")
        else:
            await update.message.reply_text(text="Missing 'action' arguments")

    async def parse_action_status(self, update: Update, *args, **kwargs) -> None:
        """
        Dump scanner SLA.
        """
        result = "SCANNER STATUS:\n"
        for address in self.agent_info:
            sla = self.execute_request(address)
            if sla.status_code == 200:
                json_sla = json.loads(sla.text)
                result = f"{result}\n{self.agent_info[address]['name']}: {json_sla['statistics']['avg']}"
            else:
                logger.error(f"Failed request for address: {address} {sla}")
                result = f"{result}\n{self.agent_info[address]['name']}: FAILED"
        await update.message.reply_text(text=result)

    async def parse_action_list(self, update: Update, *args, **kwargs) -> None:
        """
        Dump scanner config information.
        """
        result = "SCANNER CONFIG:\n"
        for address in self.agent_info:
            result = (
                f"{result}\n{self.agent_info[address]['name']}:\n"
                f"    * address: {address}\n"
                f"    * threashold sla: {self.agent_info[address]['sla']}"
            )
        await update.message.reply_text(text=result)

    async def execute_pooling(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Pool on forta SLA.
        """
        job = context.job
        for address in self.agent_info:
            sla = self.execute_request(address)
            if sla.status_code == 200:
                json_sla = json.loads(sla.text)
                if address in self.agent_status:
                    if float(self.agent_status[address]) <= float(
                        json_sla["statistics"]["avg"]
                    ):
                        # Only produce alerts if conditions degrade
                        self.agent_status[address] = json_sla["statistics"]["avg"]
                        continue

                if float(json_sla["statistics"]["avg"]) <= float(
                    self.agent_info[address]["sla"]
                ):
                    alert = (
                        f"SCANNER ALERT\n"
                        f"{self.agent_info[address]['name']}: {json_sla['statistics']['avg']}"
                    )
                    logger.info(f"New alert: {alert}")
                    await context.bot.send_message(chat_id=job.chat_id, text=alert)
                # Remember this value so we produce new allerts only if SLA degrades
                self.agent_status[address] = json_sla["statistics"]["avg"]
            else:
                logger.error(f"Request failed: {address} {sla}")
                await context.bot.send_message(
                    chat_id=job.chat_id,
                    text=(
                        f"SCANNER ALERT:\n"
                        f"{self.agent_info[address]['name']}: request failed"
                    ),
                )

    def remove_job_if_exists(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        Remove forta monitor job.
        :return: True if job was found and removed, False otherwise.
        """
        return remove_job_if_exists(context, self.job_name(update))

    async def parse_action_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
    ) -> None:
        """
        Add a job to monitor scanner nodes.
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
        Stop monitoring scanner nodes.
        :return: None
        """
        job_removed = self.remove_job_if_exists(update, context)
        logger.info(f"Monitor job removed (result:{job_removed})")

        await update.message.reply_text("Monitoring stopped")

    async def execute_action(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Entry point for forta extension. Overrides 'ExtensionBase.execute_action'.
        :return: None
        """
        forta_actions = {
            "add": {"func": self.parse_action_add},
            "remove": {"func": self.parse_action_remove},
            "status": {"func": self.parse_action_status},
            "list": {"func": self.parse_action_list},
            "start": {"func": self.parse_action_start},
            "stop": {"func": self.parse_action_stop},
        }

        if context.args:
            try:
                await forta_actions[context.args[0]]["func"](
                    update, context, context.args[1:]
                )
            except:
                logger.exception("Failed to perform action")
                await update.message.reply_text(text="Unknown 'action' parameter")
        else:
            await update.message.reply_text(text="Missing 'action' parameter")

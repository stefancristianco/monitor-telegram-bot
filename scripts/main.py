import logging

from telegram import __version__ as TG_VER

try:
    from telegram import __version_info__
except ImportError:
    __version_info__ = (0, 0, 0, 0, 0)  # type: ignore[assignment]

if __version_info__ < (20, 0, 0, "alpha", 1):
    raise RuntimeError(
        f"This code is not compatible with your current python-telegram-bot {TG_VER}"
    )

import requests
import re
import json

from typing import Any, List

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.ext import filters

from constants import FORTA_DB, FORTA_BASE_URL, CONFIG_DB

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

agent_status = {}
agent_info = {}
try:
    with open(FORTA_DB, "r") as infile:
        agent_info = json.load(infile)
except:
    logger.exception(f"Error reading '{FORTA_DB}'")


config = {}
with open(CONFIG_DB, "r") as infile:
    config = json.load(infile)


def validate_address(address: str) -> bool:
    regex = re.compile("0x[0-9a-fA-F]{40}\Z", re.I)
    if not regex.match(address):
        logger.error("Address not valid")
        return False
    return True


def forta_execute_request(address: str) -> str:
    return requests.get(f"{FORTA_BASE_URL}{address}")


def forta_validate_address(address: str) -> bool:
    if not validate_address(address):
        return False
    sla = forta_execute_request(address)
    if sla.status_code != 200:
        logger.error(f"Response: {sla} - {sla.text}")
        return False
    return True


def forta_job_name(update: Update) -> str:
    chat_id = update.message.chat_id
    return f"FORTA:{chat_id}"


def forta_parse_action_add_validate_options(opt: Any) -> bool:
    try:
        if len(opt["name"]) > 100 or len(opt["name"]) == 0:
            logger.error("Name not valid")
            return False
        if float(opt["sla"]) < 0 or float(opt["sla"]) >= 1:
            logger.error("SLA threshold not valid")
            return False
        return forta_validate_address(opt["address"])
    except:
        logger.exception("Error during options validation")

    return False


async def forta_parse_action_add(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
) -> None:
    if args:
        try:
            opt = {arg.split("=")[0]: arg.split("=")[1] for arg in args}
            if not forta_parse_action_add_validate_options(opt):
                await update.message.reply_text(text="Invalid arguments")
            agent_info[opt["address"]] = {"name": opt["name"], "sla": opt["sla"]}
            if opt["address"] in agent_status:
                del agent_status[opt["address"]]
            with open(FORTA_DB, "w") as outfile:
                json.dump(agent_info, outfile)
            await update.message.reply_text(text=f"SCANNER UPDATED:\n{opt['address']}")
        except IndexError:
            await update.message.reply_text(text="Invalid 'action' arguments")
    else:
        await update.message.reply_text(text="Missing 'action' arguments")


async def forta_parse_action_remove(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
) -> None:
    if args:
        try:
            if validate_address(args[0]):
                if args[0] in agent_status:
                    del agent_status[args[0]]
                del agent_info[args[0]]
                with open(FORTA_DB, "w") as outfile:
                    json.dump(agent_info, outfile)
                await update.message.reply_text(text=f"SCANNER REMOVED:\n{args[0]}")
            else:
                await update.message.reply_text(text="Address not valid")
        except:
            logger.exception(f"Failed to remove key: {args[0]}")
            await update.message.reply_text(text="Operation failed")
    else:
        await update.message.reply_text(text="Missing 'action' arguments")


async def forta_parse_action_status(update: Update, *args, **kwargs) -> None:
    """Dump scanner SLA."""
    result = "SCANNER STATUS:\n"
    for address in agent_info:
        sla = forta_execute_request(address)
        if sla.status_code == 200:
            json_sla = json.loads(sla.text)
            result = f"{result}\n{agent_info[address]['name']}: {json_sla['statistics']['avg']}"
        else:
            logger.error(f"Failed request for address: {address} {sla}")
            result = f"{result}\n{agent_info[address]['name']}: FAILED"
    await update.message.reply_text(text=result)


async def forta_parse_action_list(update: Update, *args, **kwargs) -> None:
    """Dump scanner config information."""
    result = "SCANNER CONFIG:\n"
    for address in agent_info:
        result = f"{result}\n{agent_info[address]['name']}:\n    * address: {address}\n    * threashold sla: {agent_info[address]['sla']}"
    await update.message.reply_text(text=result)


async def forta_execute_pooling(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pool on forta SLA."""
    job = context.job
    for address in agent_info:
        sla = forta_execute_request(address)
        if sla.status_code == 200:
            json_sla = json.loads(sla.text)
            if address in agent_status:
                if float(agent_status[address]) <= float(json_sla["statistics"]["avg"]):
                    # Only produce alerts if conditions degrade
                    agent_status[address] = json_sla["statistics"]["avg"]
                    continue

            if float(json_sla["statistics"]["avg"]) <= float(
                agent_info[address]["sla"]
            ):
                alert = f"SCANNER ALERT\n{agent_info[address]['name']}: {json_sla['statistics']['avg']}"
                logger.info(alert)
                await context.bot.send_message(chat_id=job.chat_id, text=alert)

            agent_status[address] = json_sla["statistics"]["avg"]
        else:
            logger.error(f"Failed request for address: {address} {sla}")
            await context.bot.send_message(
                chat_id=job.chat_id,
                text=f"Failed request for agent: {agent_info[address]['name']}",
            )


def forta_remove_job_if_exists(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Remove forta monitor job. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(forta_job_name(update))
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


async def forta_parse_action_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
) -> None:
    """Add a job to monitor scanner nodes."""
    job_removed = forta_remove_job_if_exists(update, context)
    logger.info(f"Monitor job removed (result:{job_removed})")

    context.job_queue.run_repeating(
        forta_execute_pooling,
        60,
        chat_id=update.message.chat_id,
        name=forta_job_name(update),
    )
    await update.message.reply_text("Monitoring started")


async def forta_parse_action_stop(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs
) -> None:
    """Stop monitoring scanner nodes."""
    job_removed = forta_remove_job_if_exists(update, context)
    logger.info(f"Monitor job removed (result:{job_removed})")
    await update.message.reply_text("Monitoring stopped")


async def forta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for forta plugin"""
    forta_actions = {
        "add": {"func": forta_parse_action_add},
        "remove": {"func": forta_parse_action_remove},
        "status": {"func": forta_parse_action_status},
        "list": {"func": forta_parse_action_list},
        "start": {"func": forta_parse_action_start},
        "stop": {"func": forta_parse_action_stop},
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


def main() -> None:
    """Run the bot."""
    builder = Application.builder()
    application = builder.token(token=config["token"]).build()

    restrict_access_filter = filters.User(
        user_id=[int(arg) for arg in config["allowed_users"]]
    )

    application.add_handler(CommandHandler("forta", forta, restrict_access_filter))

    application.run_polling()


if __name__ == "__main__":
    main()

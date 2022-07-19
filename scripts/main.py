#!/usr/bin/env python3

"""
Main bot script.
"""
import gc
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

import json

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.ext import filters

from helpers.utils import get_extension_by_name
from data.constants import CONFIG_DB

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


config = {}
with open(CONFIG_DB, "r") as infile:
    config = json.load(infile)

HELP = """HELP

PUBLIC COMMANDS
    Anyone can call these commands if they start a conversation with this bot.
[/help]
    Print this help message.
[/chatid]
    Display telegram chat id.

RESTRICTED COMMANDS
    These commands are restricted to the configured chat id's. Check online documentation for more details on how to gain access to these commands.
"""
for ext_name in config["extensions"]:
    HELP = f"{HELP}[/{ext_name}]\n    {config['extensions'][ext_name]['description']}\n"
HELP = f"{HELP}\nTIP: use '/cmd help' to see additional help instructions."


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Print chatid. This is needed to secure bot chat.
    :return: None
    """
    await update.message.reply_text(text=f"CHAT ID: {update.message.chat_id}")


async def help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Print help.
    :return: None
    """
    await update.message.reply_text(text=HELP)


def main() -> None:
    """
    This function will initiate and start the bot.
    :return: None
    """
    builder = Application.builder()
    application = builder.token(token=config["bot"]["token"]).build()

    # restrict access to configured chat id's
    restrict_access_filter = filters.User(
        user_id=[int(arg) for arg in config["bot"]["allowed_users"]]
    )

    extensions = {
        ext_name: get_extension_by_name(ext_name)(config["extensions"][ext_name])
        for ext_name in config["extensions"]
    }
    for ext_name in extensions:
        application.add_handler(
            CommandHandler(
                ext_name,
                extensions[ext_name].execute_action,
                restrict_access_filter,
            )
        )

    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("chatid", chatid))

    application.run_polling()

    # Prevent some exceptions during shutdown
    gc.collect()


if __name__ == "__main__":
    main()

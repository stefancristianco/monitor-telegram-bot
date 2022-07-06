#!/usr/bin/env python3

"""
Main bot script.
"""
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


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Print chatid. This is needed to secure bot chat.
    :return: None
    """
    await update.message.reply_text(text=f"CHAT ID: {update.message.chat_id}")


def main() -> None:
    """
    This function will initiate and start the bot.
    :return: None
    """
    config = {}
    with open(CONFIG_DB, "r") as infile:
        config = json.load(infile)

    builder = Application.builder()
    application = builder.token(token=config["bot"]["token"]).build()

    restrict_access_filter = filters.User(
        user_id=[int(arg) for arg in config["bot"]["allowed_users"]]
    )

    for ext_name in config["extensions"]:
        application.add_handler(
            CommandHandler(
                ext_name,
                get_extension_by_name(ext_name)(
                    config["extensions"][ext_name]
                ).execute_action,
                restrict_access_filter,
            )
        )

    application.add_handler(CommandHandler("chatid", chatid))

    application.run_polling()


if __name__ == "__main__":
    main()

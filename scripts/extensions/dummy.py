"""
Dummy extension used as sample.
"""
from telegram import Update
from telegram.ext import ContextTypes

from extensions.extension_base import ExtensionBase


class Dummy(ExtensionBase):
    """
    Dummy extension.
    """

    def __init__(self, dummy_config) -> None:
        """
        Init all variables and objects.
        """
        pass

    async def execute_action(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Entry point for dummy extension. Overrides 'ExtensionBase.execute_action'.
        :return: None
        """
        await update.message.reply_text(text="Sample extension")

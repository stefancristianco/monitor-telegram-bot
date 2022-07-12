"""
Every extension should derive this class and implement the required functionality.
"""
from telegram import Update
from telegram.ext import ContextTypes

from abc import ABC, abstractmethod


class ExtensionBase(ABC):
    """
    Extension base required functionality.
    """

    @abstractmethod
    async def execute_action(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        pass

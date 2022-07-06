"""
Every extension should derive ExtensionBase and implement the required functionality.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from abc import ABC, abstractmethod


logger = logging.getLogger(__name__)


class ExtensionBase(ABC):
    """
    Extension base required functionality.
    """

    @abstractmethod
    async def execute_action(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        pass

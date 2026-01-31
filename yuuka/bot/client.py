"""
Discord Bot Client for Yuuka Transaction Parser.

This module provides the Discord bot interface using a cogs-based architecture
for better separation of concerns.
"""

from typing import Optional

import discord
from discord.ext import commands

from yuuka.db import BudgetRepository, LedgerRepository, get_repository
from yuuka.services import TransactionNLPService
from yuuka.services.export import ExportService
from yuuka.services.recap import RecapService

from .cogs import (
    BudgetCog,
    ExportCog,
    GeneralCog,
    LedgerCog,
    ParsingCog,
    RecapCog,
)


class YuukaBot(commands.Bot):
    """Discord bot client for transaction parsing using cogs architecture."""

    def __init__(self, repository: Optional[LedgerRepository] = None):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)

        # Initialize services and repositories
        self.repository = repository or get_repository()
        self.budget_repo = BudgetRepository(self.repository.db_path)
        self.nlp_service = TransactionNLPService()
        self.recap_service = RecapService(self.repository, self.budget_repo)
        self.export_service = ExportService(self.repository)

    async def setup_hook(self):
        """Called when the bot is ready to set up cogs and commands."""
        # Add cogs with their dependencies
        await self.add_cog(GeneralCog(self))

        await self.add_cog(
            ParsingCog(
                self,
                self.nlp_service,
                self.repository,
            )
        )

        await self.add_cog(
            LedgerCog(
                self,
                self.repository,
            )
        )

        await self.add_cog(
            BudgetCog(
                self,
                self.repository,
                self.budget_repo,
                self.recap_service,
            )
        )

        await self.add_cog(
            RecapCog(
                self,
                self.repository,
                self.budget_repo,
                self.recap_service,
            )
        )

        await self.add_cog(
            ExportCog(
                self,
                self.repository,
                self.export_service,
            )
        )

        # Sync commands with Discord
        await self.tree.sync()

    async def on_ready(self):
        """Called when the bot has successfully connected."""
        if self.user:
            print(f"Logged in as {self.user} (ID: {self.user.id})")
            print(f"Loaded cogs: {', '.join(self.cogs.keys())}")
            print("------")


def create_bot(repository: Optional[LedgerRepository] = None) -> YuukaBot:
    """
    Create and configure the Discord bot.

    Args:
        repository: Optional LedgerRepository instance. If not provided,
                   the default repository will be used.

    Returns:
        Configured YuukaBot instance ready to run.
    """
    return YuukaBot(repository=repository)

"""
Discord Bot Client for Yuuka Transaction Parser.

This module provides the Discord bot interface using a cogs-based architecture
for better separation of concerns.
"""

import logging
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

logger = logging.getLogger(__name__)


class YuukaBot(commands.Bot):
    """Discord bot client for transaction parsing using cogs architecture."""

    def __init__(self, repository: Optional[LedgerRepository] = None):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)

        try:
            # Initialize services and repositories
            self.repository = repository or get_repository()
            logger.info(f"Repository initialized: {self.repository.db_path}")

            self.budget_repo = BudgetRepository(self.repository.db_path)
            logger.info("Budget repository initialized")

            self.nlp_service = TransactionNLPService()
            logger.info("NLP service initialized")

            self.recap_service = RecapService(self.repository, self.budget_repo)
            logger.info("Recap service initialized")

            self.export_service = ExportService(self.repository)
            logger.info("Export service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize bot services: {e}", exc_info=True)
            raise

    async def setup_hook(self):
        """Called when the bot is ready to set up cogs and commands."""
        try:
            logger.info("Starting bot setup...")

            # Add cogs with their dependencies
            await self.add_cog(GeneralCog(self))
            logger.info("Added GeneralCog")

            await self.add_cog(
                ParsingCog(
                    self,
                    self.nlp_service,
                    self.repository,
                )
            )
            logger.info("Added ParsingCog")

            await self.add_cog(
                LedgerCog(
                    self,
                    self.repository,
                )
            )
            logger.info("Added LedgerCog")

            await self.add_cog(
                BudgetCog(
                    self,
                    self.repository,
                    self.budget_repo,
                    self.recap_service,
                )
            )
            logger.info("Added BudgetCog")

            await self.add_cog(
                RecapCog(
                    self,
                    self.repository,
                    self.budget_repo,
                    self.recap_service,
                )
            )
            logger.info("Added RecapCog")

            await self.add_cog(
                ExportCog(
                    self,
                    self.repository,
                    self.export_service,
                )
            )
            logger.info("Added ExportCog")

            # Sync commands with Discord
            await self.tree.sync()
            logger.info("Synced command tree with Discord")
        except Exception as e:
            logger.error(f"Error in setup_hook: {e}", exc_info=True)
            raise

    async def on_ready(self):
        """Called when the bot has successfully connected."""
        try:
            if self.user:
                message = f"Logged in as {self.user} (ID: {self.user.id})"
                cogs_message = f"Loaded cogs: {', '.join(self.cogs.keys())}"

                logger.info(message)
                logger.info(cogs_message)
                logger.info(f"Bot is ready to receive commands")

                print(message)
                print(cogs_message)
                print("------")
            else:
                logger.warning("Bot user is None in on_ready")
        except Exception as e:
            logger.error(f"Error in on_ready: {e}", exc_info=True)

    async def on_error(self, event_method: str, *args, **kwargs):
        """Called when an event handler raises an exception."""
        logger.error(
            f"Error in event handler '{event_method}'",
            exc_info=True,
            extra={"args": args, "kwargs": kwargs},
        )


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

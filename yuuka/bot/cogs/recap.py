"""
Recap Cog for daily financial recaps with charts.

Handles the /recap command for generating daily summaries and burndown charts.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import BudgetRepository, LedgerRepository
from yuuka.services.recap import RecapService

logger = logging.getLogger(__name__)


class RecapCog(commands.Cog):
    """Cog for daily recap functionality."""

    def __init__(
        self,
        bot: commands.Bot,
        repository: LedgerRepository,
        budget_repo: BudgetRepository,
        recap_service: RecapService,
    ):
        self.bot = bot
        self.repository = repository
        self.budget_repo = budget_repo
        self.recap_service = recap_service

    def _is_dm(self, interaction: discord.Interaction) -> bool:
        """Check if interaction is in a DM."""
        return interaction.guild is None

    @app_commands.command(name="recap", description="Get your daily financial recap")
    async def recap_command(self, interaction: discord.Interaction):
        """Generate and send the daily recap with chart."""
        try:
            is_dm = self._is_dm(interaction)
            user_id = str(interaction.user.id)

            await interaction.response.defer(ephemeral=not is_dm)

            # Generate recap
            try:
                recap = self.recap_service.generate_recap(user_id)
            except Exception as e:
                logger.error(
                    f"Error generating recap for user {user_id}: {e}", exc_info=True
                )
                await interaction.followup.send(
                    "❌ Error generating recap. Please try again.",
                    ephemeral=not is_dm,
                )
                return

            # Check if there's any data
            if (
                recap.current_balance == 0
                and recap.today_summary.transaction_count == 0
            ):
                await interaction.followup.send(
                    "📭 No transaction data found. "
                    "Start recording transactions to see your recap!",
                    ephemeral=not is_dm,
                )
                logger.debug(f"No recap data for user {user_id}")
                return

            # Get budget for chart
            budget = self.budget_repo.get_by_user(user_id)

            # Generate chart
            chart_buffer = None
            try:
                chart_buffer = self.recap_service.generate_burndown_chart(recap, budget)
            except MemoryError:
                logger.error(
                    f"Memory error generating chart for user {user_id}", exc_info=True
                )
                await interaction.followup.send(
                    "❌ Chart generation failed due to memory constraints. "
                    "Try viewing your summary with /summary instead.",
                    ephemeral=not is_dm,
                )
                return
            except Exception as e:
                logger.error(
                    f"Error generating chart for user {user_id}: {e}", exc_info=True
                )
                await interaction.followup.send(
                    "❌ Error generating chart. Please try again.",
                    ephemeral=not is_dm,
                )
                return

            # Format message
            try:
                message = self.recap_service.format_recap_message(recap)
            except Exception as e:
                logger.error(f"Error formatting recap message: {e}", exc_info=True)
                message = (
                    "📊 **Daily Recap**\n\nError formatting details. Please check logs."
                )

            # Send with chart
            try:
                file = discord.File(chart_buffer, filename="burndown_chart.png")
                await interaction.followup.send(content=message, file=file)
                logger.info(f"Sent recap for user {user_id}")
            except discord.HTTPException as e:
                logger.error(f"Discord API error sending recap: {e}", exc_info=True)
                await interaction.followup.send(
                    "❌ Error sending recap. The chart may be too large.",
                    ephemeral=not is_dm,
                )
            finally:
                # Clean up buffer
                if chart_buffer:
                    chart_buffer.close()
        except Exception as e:
            logger.error(f"Error in recap_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while generating your recap. Please try again."
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        error_msg, ephemeral=not self._is_dm(interaction)
                    )
                else:
                    await interaction.response.send_message(
                        error_msg, ephemeral=not self._is_dm(interaction)
                    )
            except Exception:
                logger.error("Could not send error message to user")


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    # This will be called with proper dependencies from the main bot setup
    pass

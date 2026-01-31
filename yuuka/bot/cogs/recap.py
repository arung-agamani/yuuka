"""
Recap Cog for daily financial recaps with charts.

Handles the /recap command for generating daily summaries and burndown charts.
"""

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import BudgetRepository, LedgerRepository
from yuuka.services.recap import RecapService


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

    @app_commands.command(name="recap", description="Get your daily financial recap")
    async def recap_command(self, interaction: discord.Interaction):
        """Generate and send the daily recap with chart."""
        user_id = str(interaction.user.id)

        await interaction.response.defer()

        # Generate recap
        recap = self.recap_service.generate_recap(user_id)

        # Check if there's any data
        if recap.current_balance == 0 and recap.today_summary.transaction_count == 0:
            await interaction.followup.send(
                "📭 No transaction data found. "
                "Start recording transactions to see your recap!",
                ephemeral=True,
            )
            return

        # Get budget for chart
        budget = self.budget_repo.get_by_user(user_id)

        # Generate chart
        chart_buffer = self.recap_service.generate_burndown_chart(recap, budget)

        # Format message
        message = self.recap_service.format_recap_message(recap)

        # Send with chart
        file = discord.File(chart_buffer, filename="burndown_chart.png")
        await interaction.followup.send(content=message, file=file)


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    # This will be called with proper dependencies from the main bot setup
    pass

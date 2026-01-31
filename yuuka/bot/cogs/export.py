"""
Export Cog for ledger data export functionality.

Handles the /export command for exporting ledger data to XLSX and CSV formats.
"""

from datetime import date, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import LedgerRepository
from yuuka.services.export import ExportFormat, ExportService


class ExportCog(commands.Cog):
    """Cog for data export functionality."""

    def __init__(
        self,
        bot: commands.Bot,
        repository: LedgerRepository,
        export_service: ExportService,
    ):
        self.bot = bot
        self.repository = repository
        self.export_service = export_service

    @app_commands.command(
        name="export", description="Export your ledger data to a file"
    )
    @app_commands.describe(
        format="Export format (xlsx or csv)",
        period="Time period to export",
    )
    @app_commands.choices(
        format=[
            app_commands.Choice(name="Excel (XLSX)", value="xlsx"),
            app_commands.Choice(name="CSV", value="csv"),
        ],
        period=[
            app_commands.Choice(name="All time", value="all"),
            app_commands.Choice(name="This month", value="month"),
            app_commands.Choice(name="Last 30 days", value="30days"),
            app_commands.Choice(name="Last 90 days", value="90days"),
            app_commands.Choice(name="This year", value="year"),
        ],
    )
    async def export_command(
        self,
        interaction: discord.Interaction,
        format: str = "xlsx",
        period: str = "all",
    ):
        """Export ledger data to XLSX or CSV file."""
        user_id = str(interaction.user.id)

        await interaction.response.defer(ephemeral=True)

        # Calculate date range based on period
        today = date.today()
        start_date: Optional[date] = None
        end_date: Optional[date] = None

        if period == "month":
            start_date = today.replace(day=1)
            end_date = today
        elif period == "30days":
            start_date = today - timedelta(days=30)
            end_date = today
        elif period == "90days":
            start_date = today - timedelta(days=90)
            end_date = today
        elif period == "year":
            start_date = today.replace(month=1, day=1)
            end_date = today
        # "all" leaves both as None

        # Check if user has any entries
        entry_count = self.repository.count_user_entries(user_id)
        if entry_count == 0:
            await interaction.followup.send(
                "📭 No transactions found to export. "
                "Start recording transactions first!",
                ephemeral=True,
            )
            return

        # Generate export
        export_format = ExportFormat(format)

        if export_format == ExportFormat.XLSX:
            buffer = self.export_service.export_to_xlsx(user_id, start_date, end_date)
        else:
            buffer = self.export_service.export_to_csv(user_id, start_date, end_date)

        filename = self.export_service.get_filename(
            user_id, export_format, start_date, end_date
        )

        # Send file
        file = discord.File(buffer, filename=filename)

        period_text = {
            "all": "all time",
            "month": "this month",
            "30days": "last 30 days",
            "90days": "last 90 days",
            "year": "this year",
        }.get(period, period)

        await interaction.followup.send(
            f"📁 Here's your ledger export ({period_text}):",
            file=file,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    # This will be called with proper dependencies from the main bot setup
    pass

"""
Export Cog for ledger data export functionality.

Handles the /export command for exporting ledger data to XLSX and CSV formats.
"""

import logging
from datetime import date, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import LedgerRepository
from yuuka.services.export import ExportFormat, ExportService

logger = logging.getLogger(__name__)


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

    def _is_dm(self, interaction: discord.Interaction) -> bool:
        """Check if interaction is in a DM."""
        return interaction.guild is None

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
        try:
            is_dm = self._is_dm(interaction)
            user_id = str(interaction.user.id)

            await interaction.response.defer(ephemeral=not is_dm)

            # Validate format
            if format not in ["xlsx", "csv"]:
                await interaction.followup.send(
                    "❌ Invalid export format. Please choose 'xlsx' or 'csv'.",
                    ephemeral=not is_dm,
                )
                return

            # Calculate date range based on period
            today = date.today()
            start_date: Optional[date] = None
            end_date: Optional[date] = None

            try:
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
            except Exception as e:
                logger.error(f"Error calculating date range: {e}", exc_info=True)
                await interaction.followup.send(
                    "❌ Error calculating date range. Please try again.",
                    ephemeral=not is_dm,
                )
                return

            # Check if user has any entries
            entry_count = self.repository.count_user_entries(user_id)
            if entry_count == 0:
                await interaction.followup.send(
                    "📭 No transactions found to export. "
                    "Start recording transactions first!",
                    ephemeral=not is_dm,
                )
                logger.debug(f"No entries to export for user {user_id}")
                return

            # Generate export
            export_format = ExportFormat(format)

            try:
                if export_format == ExportFormat.XLSX:
                    buffer = self.export_service.export_to_xlsx(
                        user_id, start_date, end_date
                    )
                else:
                    buffer = self.export_service.export_to_csv(
                        user_id, start_date, end_date
                    )
            except MemoryError:
                logger.error(
                    f"Memory error exporting for user {user_id}", exc_info=True
                )
                await interaction.followup.send(
                    "❌ Export too large to process. Try a smaller date range.",
                    ephemeral=not is_dm,
                )
                return
            except Exception as e:
                logger.error(f"Error generating export: {e}", exc_info=True)
                await interaction.followup.send(
                    "❌ Error generating export file. Please try again.",
                    ephemeral=not is_dm,
                )
                return

            filename = self.export_service.get_filename(
                user_id, export_format, start_date, end_date
            )

            # Send file
            try:
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
                    ephemeral=not is_dm,
                )
                logger.info(
                    f"Exported {entry_count} entries for user {user_id} ({format})"
                )
            except discord.HTTPException as e:
                logger.error(f"Discord API error sending file: {e}", exc_info=True)
                await interaction.followup.send(
                    "❌ Error uploading file. The export may be too large.",
                    ephemeral=not is_dm,
                )
            finally:
                # Clean up buffer
                buffer.close()
        except ValueError as e:
            logger.warning(f"Validation error in export_command: {e}")
            error_msg = f"❌ Invalid input: {str(e)}"
            if interaction.response.is_done():
                await interaction.followup.send(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )
            else:
                await interaction.response.send_message(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )
        except Exception as e:
            logger.error(f"Error in export_command: {e}", exc_info=True)
            error_msg = "❌ An error occurred while exporting. Please try again."
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

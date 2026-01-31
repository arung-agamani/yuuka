"""
Ledger Cog for viewing and managing ledger entries.

Handles the /history, /summary, /balance, and /delete commands.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import LedgerEntry, LedgerRepository
from yuuka.models import TransactionAction

logger = logging.getLogger(__name__)


def format_entry(entry: LedgerEntry) -> str:
    """Format a ledger entry for display in Discord."""
    action_emoji = {
        TransactionAction.INCOMING: "📥",
        TransactionAction.OUTGOING: "📤",
        TransactionAction.TRANSFER: "🔄",
    }

    emoji = action_emoji.get(entry.action, "💰")
    amount_str = f"{entry.amount:,.0f}"
    date_str = entry.created_at.strftime("%Y-%m-%d %H:%M")

    return (
        f"`#{entry.id}` {emoji} **{entry.action.value}** {amount_str} | "
        f"{entry.source or '-'} → {entry.destination or '-'} | "
        f"{entry.description or '-'} | {date_str}"
    )


class LedgerCog(commands.Cog):
    """Cog for ledger viewing and management functionality."""

    def __init__(self, bot: commands.Bot, repository: LedgerRepository):
        self.bot = bot
        self.repository = repository

    @app_commands.command(name="history", description="View your transaction history")
    @app_commands.describe(
        limit="Number of entries to show (default: 10, max: 25)",
        action="Filter by action type",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="All", value="all"),
            app_commands.Choice(name="Incoming", value="incoming"),
            app_commands.Choice(name="Outgoing", value="outgoing"),
            app_commands.Choice(name="Transfer", value="transfer"),
        ]
    )
    async def history_command(
        self,
        interaction: discord.Interaction,
        limit: int = 10,
        action: str = "all",
    ):
        """Show transaction history for the user."""
        try:
            user_id = str(interaction.user.id)
            limit = min(max(1, limit), 25)  # Clamp between 1 and 25

            action_filter = None
            if action != "all":
                try:
                    action_filter = TransactionAction(action)
                except ValueError:
                    await interaction.response.send_message(
                        f"❌ Invalid action type: {action}",
                        ephemeral=True,
                    )
                    return

            entries = self.repository.get_user_entries(
                user_id=user_id,
                limit=limit,
                action=action_filter,
            )

            if not entries:
                await interaction.response.send_message(
                    "📭 No transactions found. Start by recording some transactions!",
                    ephemeral=True,
                )
                logger.debug(f"No history found for user {user_id}")
                return

            total = self.repository.count_user_entries(user_id, action_filter)
            lines = [
                f"📜 **Transaction History** (showing {len(entries)} of {total}):\n"
            ]

            for entry in entries:
                lines.append(format_entry(entry))

            message = "\n".join(lines)
            # Discord has a 2000 character limit
            if len(message) > 2000:
                message = message[:1997] + "..."
                logger.warning(f"History message truncated for user {user_id}")

            await interaction.response.send_message(message, ephemeral=True)
            logger.info(f"Showed {len(entries)} history entries for user {user_id}")
        except ValueError as e:
            logger.warning(f"Validation error in history_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in history_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while retrieving your history. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

    @app_commands.command(name="summary", description="View your ledger summary")
    async def summary_command(self, interaction: discord.Interaction):
        """Show a summary of the user's ledger."""
        try:
            user_id = str(interaction.user.id)
            summary = self.repository.get_user_summary(user_id)

            if summary["total_entries"] == 0:
                await interaction.response.send_message(
                    "📭 No transactions found. Start by recording some transactions!",
                    ephemeral=True,
                )
                logger.debug(f"No summary data for user {user_id}")
                return

            incoming = summary["incoming"]
            outgoing = summary["outgoing"]
            transfer = summary["transfer"]
            net = summary["net"]

            net_emoji = "📈" if net >= 0 else "📉"

            inc_total = f"{incoming['total']:,.0f}"
            out_total = f"{outgoing['total']:,.0f}"
            tfr_total = f"{transfer['total']:,.0f}"
            net_total = f"{net:,.0f}"

            lines = [
                "📊 **Ledger Summary**",
                "```",
                f"📥 Incoming:  {incoming['count']:>4} entries | {inc_total:>15}",
                f"📤 Outgoing:  {outgoing['count']:>4} entries | {out_total:>15}",
                f"🔄 Transfer:  {transfer['count']:>4} entries | {tfr_total:>15}",
                "─" * 45,
                f"{net_emoji} Net:                        | {net_total:>15}",
                "```",
            ]

            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            logger.info(
                f"Showed summary for user {user_id}: {summary['total_entries']} entries"
            )
        except ValueError as e:
            logger.warning(f"Validation error in summary_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in summary_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while retrieving your summary. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

    @app_commands.command(name="balance", description="View balances by account")
    async def balance_command(self, interaction: discord.Interaction):
        """Show balance breakdown by account."""
        try:
            user_id = str(interaction.user.id)
            balances = self.repository.get_user_balance_by_account(user_id)

            if not balances:
                await interaction.response.send_message(
                    "📭 No accounts found. Start by recording some transactions!",
                    ephemeral=True,
                )
                logger.debug(f"No balances found for user {user_id}")
                return

            # Sort by balance descending
            sorted_balances = sorted(balances.items(), key=lambda x: x[1], reverse=True)

            lines = ["💰 **Account Balances**", "```"]

            for account, balance in sorted_balances:
                emoji = "+" if balance >= 0 else ""
                # Sanitize account name to prevent formatting issues
                safe_account = account[:20] if account else "Unknown"
                lines.append(f"{safe_account:<20} | {emoji}{balance:>15,.0f}")

            lines.append("```")

            message = "\n".join(lines)
            # Discord has a 2000 character limit
            if len(message) > 2000:
                message = message[:1997] + "..."
                logger.warning(f"Balance message truncated for user {user_id}")

            await interaction.response.send_message(message, ephemeral=True)
            logger.info(
                f"Showed balances for {len(balances)} accounts for user {user_id}"
            )
        except ValueError as e:
            logger.warning(f"Validation error in balance_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in balance_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while retrieving your balances. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)

    @app_commands.command(name="delete", description="Delete a transaction by ID")
    @app_commands.describe(entry_id="The transaction ID to delete")
    async def delete_command(self, interaction: discord.Interaction, entry_id: int):
        """Delete a transaction entry."""
        try:
            # Validate entry_id
            if entry_id <= 0:
                await interaction.response.send_message(
                    "❌ Transaction ID must be a positive number.",
                    ephemeral=True,
                )
                return

            user_id = str(interaction.user.id)

            # Get entry first to show what's being deleted
            entry = self.repository.get_by_id(entry_id)

            if not entry:
                await interaction.response.send_message(
                    f"❌ Transaction `#{entry_id}` not found.",
                    ephemeral=True,
                )
                logger.debug(
                    f"Entry {entry_id} not found for deletion by user {user_id}"
                )
                return

            if entry.user_id != user_id:
                await interaction.response.send_message(
                    "❌ You can only delete your own transactions.",
                    ephemeral=True,
                )
                logger.warning(
                    f"User {user_id} attempted to delete entry {entry_id} owned by {entry.user_id}"
                )
                return

            deleted = self.repository.delete_entry(entry_id, user_id)

            if deleted:
                await interaction.response.send_message(
                    f"🗑️ Deleted transaction `#{entry_id}`:\n{format_entry(entry)}",
                    ephemeral=True,
                )
                logger.info(f"User {user_id} deleted entry {entry_id}")
            else:
                await interaction.response.send_message(
                    f"❌ Failed to delete transaction `#{entry_id}`.",
                    ephemeral=True,
                )
                logger.error(f"Failed to delete entry {entry_id} for user {user_id}")
        except ValueError as e:
            logger.warning(f"Validation error in delete_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=True,
            )
        except Exception as e:
            logger.error(f"Error in delete_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while deleting the transaction. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    # This will be called with proper dependencies from the main bot setup
    pass

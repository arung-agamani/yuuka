"""
Ledger Cog for viewing and managing ledger entries.

Handles the /history, /summary, /balance, /delete, /edit, /accounts, /trial_balance,
/income_statement, and /balance_sheet commands.

This cog supports the double-entry bookkeeping system with proper
debit/credit accounting.
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import LedgerEntry, LedgerRepository
from yuuka.models import TransactionAction
from yuuka.models.account import AccountType

logger = logging.getLogger(__name__)


class EditTransactionModal(discord.ui.Modal, title="Edit Transaction"):
    """Modal for editing an existing transaction."""

    amount = discord.ui.TextInput(
        label="Amount",
        placeholder="Enter new amount (leave empty to keep current)",
        required=False,
        max_length=20,
    )

    source = discord.ui.TextInput(
        label="Source (from)",
        placeholder="Enter new source account (leave empty to keep current)",
        required=False,
        max_length=100,
    )

    destination = discord.ui.TextInput(
        label="Destination (to)",
        placeholder="Enter new destination account (leave empty to keep current)",
        required=False,
        max_length=100,
    )

    description = discord.ui.TextInput(
        label="Description",
        placeholder="Enter new description (leave empty to keep current)",
        required=False,
        max_length=200,
        style=discord.TextStyle.short,
    )

    def __init__(
        self,
        repository: LedgerRepository,
        transaction_id: int,
        user_id: str,
        current_amount: float,
        current_source: Optional[str],
        current_destination: Optional[str],
        current_description: Optional[str],
    ):
        super().__init__()
        self.repository = repository
        self.transaction_id = transaction_id
        self.user_id = user_id

        # Pre-fill with current values
        self.amount.default = str(int(current_amount)) if current_amount else ""
        self.source.default = current_source or ""
        self.destination.default = current_destination or ""
        self.description.default = current_description or ""

    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission."""
        try:
            # Parse and validate amount
            new_amount = None
            if self.amount.value and self.amount.value.strip():
                try:
                    # Remove commas and parse
                    amount_str = (
                        self.amount.value.strip().replace(",", "").replace(".", "")
                    )
                    new_amount = float(amount_str)
                    if new_amount <= 0:
                        await interaction.response.send_message(
                            "❌ Amount must be a positive number.",
                            ephemeral=True,
                        )
                        return
                except ValueError:
                    await interaction.response.send_message(
                        "❌ Invalid amount format. Please enter a number.",
                        ephemeral=True,
                    )
                    return

            # Get new values (None means keep current)
            new_source = (
                self.source.value.strip() if self.source.value.strip() else None
            )
            new_destination = (
                self.destination.value.strip()
                if self.destination.value.strip()
                else None
            )
            new_description = (
                self.description.value.strip()
                if self.description.value.strip()
                else None
            )

            # Check if anything changed
            if (
                new_amount is None
                and new_source is None
                and new_destination is None
                and new_description is None
            ):
                await interaction.response.send_message(
                    "ℹ️ No changes made. All fields were left empty.",
                    ephemeral=True,
                )
                return

            # Update the transaction
            updated_txn = self.repository.update_transaction(
                transaction_id=self.transaction_id,
                user_id=self.user_id,
                new_amount=new_amount,
                new_source=new_source,
                new_destination=new_destination,
                new_description=new_description,
            )

            if updated_txn:
                # Format the updated transaction for display
                lines = [
                    f"✅ Transaction `#{self.transaction_id}` updated successfully!",
                    "",
                    "**Updated values:**",
                    "```",
                ]

                # Show the journal entries
                for entry in updated_txn.entries:
                    entry_type = "DR" if entry.entry_type.value == "debit" else "CR"
                    lines.append(
                        f"{entry_type} {entry.account_name:<20} {entry.amount:>12,.0f}"
                    )

                lines.append("```")

                if updated_txn.description:
                    lines.append(f"📝 Description: {updated_txn.description}")

                await interaction.response.send_message(
                    "\n".join(lines),
                    ephemeral=True,
                )
                logger.info(
                    f"User {self.user_id} updated transaction {self.transaction_id}"
                )
            else:
                await interaction.response.send_message(
                    "❌ Failed to update transaction. It may have been deleted.",
                    ephemeral=True,
                )

        except Exception as e:
            logger.error(f"Error in EditTransactionModal.on_submit: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while updating the transaction. Please try again.",
                ephemeral=True,
            )

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        """Handle modal errors."""
        logger.error(f"Error in EditTransactionModal: {error}", exc_info=True)
        await interaction.response.send_message(
            "❌ An error occurred. Please try again.",
            ephemeral=True,
        )


def format_entry(entry: LedgerEntry) -> str:
    """Format a ledger entry for display in Discord."""
    action_emoji = {
        "incoming": "📥",
        "outgoing": "📤",
        "transfer": "🔄",
    }

    emoji = action_emoji.get(entry.action, "💰")
    amount_str = f"{entry.amount:,.0f}"
    date_str = entry.created_at.strftime("%Y-%m-%d %H:%M")

    return (
        f"`#{entry.id}` {emoji} **{entry.action}** {amount_str} | "
        f"{entry.source or '-'} → {entry.destination or '-'} | "
        f"{entry.description or '-'} | {date_str}"
    )


def format_account_type(account_type: AccountType) -> str:
    """Format account type with emoji."""
    type_emoji = {
        AccountType.ASSET: "💰",
        AccountType.LIABILITY: "📋",
        AccountType.EQUITY: "🏦",
        AccountType.REVENUE: "📈",
        AccountType.EXPENSE: "📉",
    }
    emoji = type_emoji.get(account_type, "📄")
    return f"{emoji} {account_type.value.title()}"


class LedgerCog(commands.Cog):
    """Cog for ledger viewing and management functionality."""

    def __init__(self, bot: commands.Bot, repository: LedgerRepository):
        self.bot = bot
        self.repository = repository

    def _is_dm(self, interaction: discord.Interaction) -> bool:
        """Check if interaction is in a DM."""
        return interaction.guild is None

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

            is_dm = self._is_dm(interaction)

            if not entries:
                await interaction.response.send_message(
                    "📭 No transactions found. Start by recording some transactions!",
                    ephemeral=not is_dm,
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

            await interaction.response.send_message(message, ephemeral=not is_dm)
            logger.info(f"Showed {len(entries)} history entries for user {user_id}")
        except ValueError as e:
            logger.warning(f"Validation error in history_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=not self._is_dm(interaction),
            )
        except Exception as e:
            logger.error(f"Error in history_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while retrieving your history. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )
            else:
                await interaction.response.send_message(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )

    @app_commands.command(name="summary", description="View your ledger summary")
    async def summary_command(self, interaction: discord.Interaction):
        """Show a summary of the user's ledger."""
        try:
            is_dm = self._is_dm(interaction)
            user_id = str(interaction.user.id)
            summary = self.repository.get_user_summary(user_id)

            if summary["total_entries"] == 0:
                await interaction.response.send_message(
                    "📭 No transactions found. Start by recording some transactions!",
                    ephemeral=not is_dm,
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

            await interaction.response.send_message(
                "\n".join(lines), ephemeral=not is_dm
            )
            logger.info(
                f"Showed summary for user {user_id}: {summary['total_entries']} entries"
            )
        except ValueError as e:
            logger.warning(f"Validation error in summary_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=not self._is_dm(interaction),
            )
        except Exception as e:
            logger.error(f"Error in summary_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while retrieving your summary. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )
            else:
                await interaction.response.send_message(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )

    @app_commands.command(name="balance", description="View balances by account")
    async def balance_command(self, interaction: discord.Interaction):
        """Show balance breakdown by ASSET accounts (your pockets/wallets)."""
        try:
            is_dm = self._is_dm(interaction)
            user_id = str(interaction.user.id)

            # Get balance sheet which properly categorizes accounts
            balance_sheet = self.repository.get_balance_sheet(user_id)

            if not balance_sheet or not balance_sheet.get("assets"):
                await interaction.response.send_message(
                    "📭 No asset accounts found. Start by recording some transactions!",
                    ephemeral=not is_dm,
                )
                logger.debug(f"No asset balances found for user {user_id}")
                return

            # Get assets sorted by balance descending
            assets = sorted(
                balance_sheet["assets"],
                key=lambda x: x["amount"],
                reverse=True,
            )

            lines = ["💰 **Your Pockets/Wallets**", "```"]

            for asset in assets:
                name = asset["name"][:18] if asset["name"] else "Unknown"
                amount = asset["amount"]
                # Format with Rp prefix
                amount_str = f"Rp {amount:>14,.0f}"
                lines.append(f"{name:<18} | {amount_str}")

            lines.append("```")

            # Add total
            total_assets = balance_sheet["total_assets"]
            lines.append(f"\n💵 **Total Balance:** Rp {total_assets:,.0f}")

            message = "\n".join(lines)
            if len(message) > 2000:
                message = message[:1997] + "..."
                logger.warning(f"Balance message truncated for user {user_id}")

            await interaction.response.send_message(message, ephemeral=not is_dm)
            logger.info(
                f"Showed balances for {len(assets)} asset accounts for user {user_id}"
            )
        except ValueError as e:
            logger.warning(f"Validation error in balance_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=not self._is_dm(interaction),
            )
        except Exception as e:
            logger.error(f"Error in balance_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while retrieving your balances. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )
            else:
                await interaction.response.send_message(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )

    @app_commands.command(
        name="trial_balance", description="View trial balance (debits vs credits)"
    )
    async def trial_balance_command(self, interaction: discord.Interaction):
        """Show trial balance to verify debits equal credits."""
        try:
            is_dm = self._is_dm(interaction)
            user_id = str(interaction.user.id)
            trial_balance = self.repository.get_trial_balance(user_id)

            if not trial_balance["accounts"]:
                await interaction.response.send_message(
                    "📭 No transactions found to generate trial balance.",
                    ephemeral=not is_dm,
                )
                return

            lines = ["⚖️ **Trial Balance**", "```"]
            lines.append(f"{'Account':<20} {'Debit':>12} {'Credit':>12}")
            lines.append("─" * 46)

            for acc in trial_balance["accounts"]:
                debit = f"{acc['debit']:,.0f}" if acc["debit"] else "-"
                credit = f"{acc['credit']:,.0f}" if acc["credit"] else "-"
                lines.append(f"{acc['name']:<20} {debit:>12} {credit:>12}")

            lines.append("─" * 46)
            total_dr = f"{trial_balance['total_debits']:,.0f}"
            total_cr = f"{trial_balance['total_credits']:,.0f}"
            lines.append(f"{'TOTAL':<20} {total_dr:>12} {total_cr:>12}")
            lines.append("```")

            # Balance status
            if trial_balance["is_balanced"]:
                lines.append("✅ **Balanced!** Debits equal Credits")
            else:
                diff = trial_balance["difference"]
                lines.append(f"⚠️ **Unbalanced!** Difference: {diff:,.0f}")

            await interaction.response.send_message(
                "\n".join(lines), ephemeral=not is_dm
            )
            logger.info(f"Showed trial balance for user {user_id}")
        except Exception as e:
            logger.error(f"Error in trial_balance_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while generating trial balance.",
                ephemeral=not self._is_dm(interaction),
            )

    @app_commands.command(
        name="income_statement", description="View income statement (profit & loss)"
    )
    async def income_statement_command(self, interaction: discord.Interaction):
        """Show income statement with revenue and expenses."""
        try:
            is_dm = self._is_dm(interaction)
            user_id = str(interaction.user.id)
            income_stmt = self.repository.get_income_statement(user_id)

            if not income_stmt["revenue"] and not income_stmt["expenses"]:
                await interaction.response.send_message(
                    "📭 No income or expense transactions found.",
                    ephemeral=not is_dm,
                )
                return

            lines = ["📊 **Income Statement (Profit & Loss)**", ""]

            # Revenue section
            lines.append("**📈 Revenue**")
            if income_stmt["revenue"]:
                for item in income_stmt["revenue"]:
                    lines.append(f"  {item['name']:<20} {item['amount']:>12,.0f}")
            else:
                lines.append("  _(no revenue)_")
            lines.append(
                f"  **{'Total Revenue':<20} {income_stmt['total_revenue']:>12,.0f}**"
            )
            lines.append("")

            # Expense section
            lines.append("**📉 Expenses**")
            if income_stmt["expenses"]:
                for item in income_stmt["expenses"]:
                    lines.append(f"  {item['name']:<20} {item['amount']:>12,.0f}")
            else:
                lines.append("  _(no expenses)_")
            lines.append(
                f"  **{'Total Expenses':<20} {income_stmt['total_expenses']:>12,.0f}**"
            )
            lines.append("")

            # Net income
            net = income_stmt["net_income"]
            emoji = "✅" if net >= 0 else "⚠️"
            status = "Profit" if net >= 0 else "Loss"
            lines.append("─" * 35)
            lines.append(f"{emoji} **Net {status}: {net:,.0f}**")

            await interaction.response.send_message(
                "\n".join(lines), ephemeral=not is_dm
            )
            logger.info(f"Showed income statement for user {user_id}")
        except Exception as e:
            logger.error(f"Error in income_statement_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while generating income statement.",
                ephemeral=not self._is_dm(interaction),
            )

    @app_commands.command(
        name="balance_sheet",
        description="View balance sheet (assets, liabilities, equity)",
    )
    async def balance_sheet_command(self, interaction: discord.Interaction):
        """Show balance sheet with assets, liabilities, and equity."""
        try:
            is_dm = self._is_dm(interaction)
            user_id = str(interaction.user.id)
            balance_sheet = self.repository.get_balance_sheet(user_id)

            if not any(
                [
                    balance_sheet["assets"],
                    balance_sheet["liabilities"],
                    balance_sheet["equity"],
                ]
            ):
                await interaction.response.send_message(
                    "📭 No data found to generate balance sheet.",
                    ephemeral=not is_dm,
                )
                return

            lines = ["🏦 **Balance Sheet**", "```"]

            # Assets section
            lines.append("💰 Assets")
            if balance_sheet["assets"]:
                for item in balance_sheet["assets"]:
                    name = item["name"][:18] if item["name"] else "Unknown"
                    amount_str = f"Rp {item['amount']:>14,.0f}"
                    lines.append(f"  {name:<18} {amount_str}")
            else:
                lines.append("  (no assets)")
            total_assets_str = f"Rp {balance_sheet['total_assets']:>14,.0f}"
            lines.append(f"  {'Total Assets':<18} {total_assets_str}")
            lines.append("")

            # Liabilities section
            lines.append("📋 Liabilities")
            if balance_sheet["liabilities"]:
                for item in balance_sheet["liabilities"]:
                    name = item["name"][:18] if item["name"] else "Unknown"
                    amount_str = f"Rp {item['amount']:>14,.0f}"
                    lines.append(f"  {name:<18} {amount_str}")
            else:
                lines.append("  (no liabilities)")
            total_liab_str = f"Rp {balance_sheet['total_liabilities']:>14,.0f}"
            lines.append(f"  {'Total Liabilities':<18} {total_liab_str}")
            lines.append("")

            # Equity section
            lines.append("🏛️ Equity (incl. Retained Earnings)")
            if balance_sheet["equity"]:
                for item in balance_sheet["equity"]:
                    name = item["name"][:18] if item["name"] else "Unknown"
                    amount_str = f"Rp {item['amount']:>14,.0f}"
                    lines.append(f"  {name:<18} {amount_str}")
            total_equity_str = f"Rp {balance_sheet['total_equity']:>14,.0f}"
            lines.append(f"  {'Total Equity':<18} {total_equity_str}")
            lines.append("```")

            # Balance check
            if balance_sheet["is_balanced"]:
                lines.append("✅ **Accounting equation balanced!**")
                lines.append("Assets = Liabilities + Equity")
            else:
                lines.append("⚠️ **Warning: Equation not balanced**")

            await interaction.response.send_message(
                "\n".join(lines), ephemeral=not is_dm
            )
            logger.info(f"Showed balance sheet for user {user_id}")
        except Exception as e:
            logger.error(f"Error in balance_sheet_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while generating balance sheet.",
                ephemeral=not self._is_dm(interaction),
            )

    @app_commands.command(name="edit", description="Edit an existing transaction")
    @app_commands.describe(entry_id="The ID of the transaction to edit")
    async def edit_command(self, interaction: discord.Interaction, entry_id: int):
        """Edit an existing transaction via modal."""
        try:
            user_id = str(interaction.user.id)

            is_dm = self._is_dm(interaction)

            # Validate entry_id
            if entry_id <= 0:
                await interaction.response.send_message(
                    "❌ Invalid entry ID. Please provide a positive number.",
                    ephemeral=not is_dm,
                )
                return

            # Get the existing entry
            entry = self.repository.get_by_id(entry_id)

            if not entry:
                await interaction.response.send_message(
                    f"❌ Transaction `#{entry_id}` not found.",
                    ephemeral=not is_dm,
                )
                return

            # Check ownership
            if entry.user_id != user_id:
                await interaction.response.send_message(
                    "❌ You can only edit your own transactions.",
                    ephemeral=not is_dm,
                )
                logger.warning(
                    f"User {user_id} attempted to edit entry {entry_id} owned by {entry.user_id}"
                )
                return

            # Open the edit modal with current values
            modal = EditTransactionModal(
                repository=self.repository,
                transaction_id=entry.transaction_id or entry_id,
                user_id=user_id,
                current_amount=entry.amount,
                current_source=entry.source,
                current_destination=entry.destination,
                current_description=entry.description,
            )

            await interaction.response.send_modal(modal)
            logger.info(f"Opened edit modal for entry {entry_id} for user {user_id}")

        except ValueError as e:
            logger.warning(f"Validation error in edit_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=not self._is_dm(interaction),
            )
        except Exception as e:
            logger.error(f"Error in edit_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while preparing the edit form. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )
            else:
                await interaction.response.send_message(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )

    @app_commands.command(name="delete", description="Delete a transaction")
    @app_commands.describe(entry_id="The ID of the transaction to delete")
    async def delete_command(self, interaction: discord.Interaction, entry_id: int):
        """Delete a transaction entry and its associated double-entry records."""
        try:
            is_dm = self._is_dm(interaction)

            # Validate entry_id
            if entry_id <= 0:
                await interaction.response.send_message(
                    "❌ Transaction ID must be a positive number.",
                    ephemeral=not is_dm,
                )
                return

            user_id = str(interaction.user.id)

            # Get entry first to show what's being deleted
            entry = self.repository.get_by_id(entry_id)

            if not entry:
                await interaction.response.send_message(
                    f"❌ Transaction `#{entry_id}` not found.",
                    ephemeral=not is_dm,
                )
                logger.debug(
                    f"Entry {entry_id} not found for deletion by user {user_id}"
                )
                return

            if entry.user_id != user_id:
                await interaction.response.send_message(
                    "❌ You can only delete your own transactions.",
                    ephemeral=not is_dm,
                )
                logger.warning(
                    f"User {user_id} attempted to delete entry {entry_id} owned by {entry.user_id}"
                )
                return

            deleted = self.repository.delete_entry(entry_id, user_id)

            if deleted:
                await interaction.response.send_message(
                    f"🗑️ Deleted transaction `#{entry_id}` (and associated journal entries):\n{format_entry(entry)}",
                    ephemeral=not is_dm,
                )
                logger.info(f"User {user_id} deleted entry {entry_id}")
            else:
                await interaction.response.send_message(
                    f"❌ Failed to delete transaction `#{entry_id}`.",
                    ephemeral=not is_dm,
                )
                logger.error(f"Failed to delete entry {entry_id} for user {user_id}")
        except ValueError as e:
            logger.warning(f"Validation error in delete_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=not self._is_dm(interaction),
            )
        except Exception as e:
            logger.error(f"Error in delete_command: {e}", exc_info=True)
            error_msg = (
                "❌ An error occurred while deleting the transaction. Please try again."
            )
            if interaction.response.is_done():
                await interaction.followup.send(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )
            else:
                await interaction.response.send_message(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    # This will be called with proper dependencies from the main bot setup
    pass

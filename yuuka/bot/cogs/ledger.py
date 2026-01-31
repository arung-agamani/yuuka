"""
Ledger Cog for viewing and managing ledger entries.

Handles the /history, /summary, /balance, /delete, /accounts, /trial_balance,
/income_statement, and /balance_sheet commands.

This cog supports the double-entry bookkeeping system with proper
debit/credit accounting.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import LedgerEntry, LedgerRepository
from yuuka.models import TransactionAction
from yuuka.models.account import AccountType

logger = logging.getLogger(__name__)


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
        """Show balance breakdown by account using double-entry bookkeeping."""
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

            # Get account types for better display
            accounts = self.repository.get_user_accounts(user_id)
            account_types = {acc.name: acc.account_type for acc in accounts}

            # Sort by balance descending
            sorted_balances = sorted(balances.items(), key=lambda x: x[1], reverse=True)

            lines = ["💰 **Account Balances** (Double-Entry)", "```"]

            for account, balance in sorted_balances:
                emoji = "+" if balance >= 0 else ""
                safe_account = account[:20] if account else "Unknown"
                acc_type = account_types.get(account, AccountType.ASSET)
                type_abbr = acc_type.value[:3].upper()
                lines.append(
                    f"[{type_abbr}] {safe_account:<16} | {emoji}{balance:>12,.0f}"
                )

            lines.append("```")

            # Add total
            total_balance = sum(
                bal
                for acc, bal in balances.items()
                if account_types.get(acc, AccountType.ASSET) == AccountType.ASSET
            )
            lines.append(f"\n💵 **Total Assets:** {total_balance:,.0f}")

            message = "\n".join(lines)
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

    @app_commands.command(name="accounts", description="View your chart of accounts")
    async def accounts_command(self, interaction: discord.Interaction):
        """Show all accounts for the user organized by type."""
        try:
            user_id = str(interaction.user.id)
            accounts = self.repository.get_user_accounts(user_id)

            if not accounts:
                await interaction.response.send_message(
                    "📭 No accounts found. Accounts are created automatically when you record transactions!",
                    ephemeral=True,
                )
                return

            # Group by account type
            by_type: dict[AccountType, list] = {t: [] for t in AccountType}
            for acc in accounts:
                by_type[acc.account_type].append(acc)

            lines = ["📋 **Chart of Accounts**\n"]

            type_order = [
                AccountType.ASSET,
                AccountType.LIABILITY,
                AccountType.EQUITY,
                AccountType.REVENUE,
                AccountType.EXPENSE,
            ]

            for acc_type in type_order:
                acc_list = by_type[acc_type]
                if acc_list:
                    lines.append(f"**{format_account_type(acc_type)}**")
                    for acc in acc_list:
                        system_marker = " ⚙️" if acc.is_system else ""
                        lines.append(f"  • {acc.name}{system_marker}")
                    lines.append("")

            message = "\n".join(lines)
            if len(message) > 2000:
                message = message[:1997] + "..."

            await interaction.response.send_message(message, ephemeral=True)
            logger.info(f"Showed {len(accounts)} accounts for user {user_id}")
        except Exception as e:
            logger.error(f"Error in accounts_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while retrieving your accounts.",
                ephemeral=True,
            )

    @app_commands.command(
        name="trial_balance", description="View trial balance (debits vs credits)"
    )
    async def trial_balance_command(self, interaction: discord.Interaction):
        """Show trial balance to verify debits equal credits."""
        try:
            user_id = str(interaction.user.id)
            trial_balance = self.repository.get_trial_balance(user_id)

            if not trial_balance["accounts"]:
                await interaction.response.send_message(
                    "📭 No transactions found to generate trial balance.",
                    ephemeral=True,
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

            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            logger.info(f"Showed trial balance for user {user_id}")
        except Exception as e:
            logger.error(f"Error in trial_balance_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while generating trial balance.",
                ephemeral=True,
            )

    @app_commands.command(
        name="income_statement", description="View income statement (profit & loss)"
    )
    async def income_statement_command(self, interaction: discord.Interaction):
        """Show income statement with revenue and expenses."""
        try:
            user_id = str(interaction.user.id)
            income_stmt = self.repository.get_income_statement(user_id)

            if not income_stmt["revenue"] and not income_stmt["expenses"]:
                await interaction.response.send_message(
                    "📭 No income or expense transactions found.",
                    ephemeral=True,
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

            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            logger.info(f"Showed income statement for user {user_id}")
        except Exception as e:
            logger.error(f"Error in income_statement_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while generating income statement.",
                ephemeral=True,
            )

    @app_commands.command(
        name="balance_sheet",
        description="View balance sheet (assets, liabilities, equity)",
    )
    async def balance_sheet_command(self, interaction: discord.Interaction):
        """Show balance sheet with assets, liabilities, and equity."""
        try:
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
                    ephemeral=True,
                )
                return

            lines = ["🏦 **Balance Sheet**", ""]

            # Assets section
            lines.append("**💰 Assets**")
            if balance_sheet["assets"]:
                for item in balance_sheet["assets"]:
                    lines.append(f"  {item['name']:<20} {item['amount']:>12,.0f}")
            else:
                lines.append("  _(no assets)_")
            lines.append(
                f"  **{'Total Assets':<20} {balance_sheet['total_assets']:>12,.0f}**"
            )
            lines.append("")

            # Liabilities section
            lines.append("**📋 Liabilities**")
            if balance_sheet["liabilities"]:
                for item in balance_sheet["liabilities"]:
                    lines.append(f"  {item['name']:<20} {item['amount']:>12,.0f}")
            else:
                lines.append("  _(no liabilities)_")
            lines.append(
                f"  **{'Total Liabilities':<20} {balance_sheet['total_liabilities']:>12,.0f}**"
            )
            lines.append("")

            # Equity section
            lines.append("**🏛️ Equity (including Retained Earnings)**")
            if balance_sheet["equity"]:
                for item in balance_sheet["equity"]:
                    lines.append(f"  {item['name']:<20} {item['amount']:>12,.0f}")
            lines.append(
                f"  **{'Total Equity':<20} {balance_sheet['total_equity']:>12,.0f}**"
            )
            lines.append("")

            # Balance check
            lines.append("─" * 35)
            if balance_sheet["is_balanced"]:
                lines.append("✅ **Accounting equation balanced!**")
                lines.append("Assets = Liabilities + Equity")
            else:
                lines.append("⚠️ **Warning: Equation not balanced**")

            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            logger.info(f"Showed balance sheet for user {user_id}")
        except Exception as e:
            logger.error(f"Error in balance_sheet_command: {e}", exc_info=True)
            await interaction.response.send_message(
                "❌ An error occurred while generating balance sheet.",
                ephemeral=True,
            )

    @app_commands.command(name="delete", description="Delete a transaction by ID")
    @app_commands.describe(entry_id="The transaction ID to delete")
    async def delete_command(self, interaction: discord.Interaction, entry_id: int):
        """Delete a transaction entry and its associated double-entry records."""
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
                    f"🗑️ Deleted transaction `#{entry_id}` (and associated journal entries):\n{format_entry(entry)}",
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

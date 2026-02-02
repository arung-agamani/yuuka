"""
General Cog for help and utility commands.

Handles the /help command and other general bot functionality.
"""

import discord
from discord import app_commands
from discord.ext import commands


class GeneralCog(commands.Cog):
    """Cog for general bot commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_dm(self, interaction: discord.Interaction) -> bool:
        """Check if interaction is in a DM."""
        return interaction.guild is None

    @app_commands.command(name="help", description="Show help for using Yuuka bot")
    async def help_command(self, interaction: discord.Interaction):
        """Show help information."""
        is_dm = self._is_dm(interaction)
        help_text = """
**Yuuka Transaction Parser** 🧾

I can parse natural language transaction messages and save them to your ledger.

**📝 Recording Transactions**
• `/parse <message>` - Parse and save a transaction
• Or just DM me or mention me with your transaction

**📊 Viewing Your Ledger**
• `/history [limit] [action]` - View transaction history
• `/summary` - View income/expense summary
• `/balance` - View balances by asset account

**💰 Account Management**
• `/accounts` - View account groups (alias for /account_groups)
• `/account_groups` - View account groups and their aliases
• `/create_account` - Create a new account group
• `/add_alias` - Add an alias to an account group
• `/remove_alias` - Remove an alias
• `/assign_account` - Assign unmapped account to a group
• `/lookup_account` - Check which group an account maps to

**📈 Financial Reports**
• `/trial_balance` - View trial balance (debits vs credits)
• `/income_statement` - View profit & loss statement
• `/balance_sheet` - View assets, liabilities, equity

**💵 Budget & Forecasting**
• `/budget [daily_limit] [payday]` - Configure your budget
• `/recap` - Get daily recap with burndown chart
• `/forecast` - See if you'll make it to payday

**✏️ Managing Entries**
• `/edit <id>` - Edit a transaction by ID
• `/delete <id>` - Delete a transaction by ID
• `/export [format] [period]` - Export ledger to XLSX or CSV

**🔧 Utility**
• `/ping` - Check if the bot is responsive
• `/help` - Show this help message

**Example transaction messages:**
• `16k from gopay for commuting`
• `52.500 from main pocket for lunch`
• `transfer 1mil from account1 to account3`
• `incoming salary 21m to main pocket`

**Supported formats:**
• Amounts: `16k`, `1mil`, `21m`, `52.500` (Indonesian format)
• Actions: `incoming`, `outgoing`, `transfer` (auto-detected)
• Keywords: `from`, `to`, `for`
        """
        await interaction.response.send_message(help_text.strip(), ephemeral=not is_dm)

    @app_commands.command(name="ping", description="Check if the bot is responsive")
    async def ping_command(self, interaction: discord.Interaction):
        """Check bot latency."""
        is_dm = self._is_dm(interaction)
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! Latency: {latency}ms",
            ephemeral=not is_dm,
        )


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    await bot.add_cog(GeneralCog(bot))

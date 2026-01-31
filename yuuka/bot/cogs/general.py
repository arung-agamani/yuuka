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

    @app_commands.command(name="help", description="Show help for using Yuuka bot")
    async def help_command(self, interaction: discord.Interaction):
        """Show help information."""
        help_text = """
**Yuuka Transaction Parser** 🧾

I can parse natural language transaction messages and save them to your ledger.

**Recording Transactions:**
• `/parse <message>` - Parse and save a transaction
• Or just DM me or mention me with your transaction

**Viewing Your Ledger:**
• `/history [limit] [action]` - View transaction history
• `/summary` - View income/expense summary
• `/balance` - View balances by account

**Budget & Forecasting:**
• `/budget [daily_limit] [payday]` - Configure your budget
• `/recap` - Get daily recap with burndown chart
• `/forecast` - See if you'll make it to payday

**Managing Entries:**
• `/delete <id>` - Delete a transaction by ID
• `/export [format] [period]` - Export ledger to XLSX or CSV

**Example messages:**
• `16k from gopay for commuting`
• `52.500 from main pocket for lunch`
• `transfer 1mil from account1 to account3`
• `incoming salary 21m to main pocket`

**Supported formats:**
• Amounts: `16k`, `1mil`, `21m`, `52.500` (Indonesian format)
• Actions: `incoming`, `outgoing`, `transfer` (auto-detected)
• Keywords: `from`, `to`, `for`
        """
        await interaction.response.send_message(help_text.strip(), ephemeral=True)

    @app_commands.command(name="ping", description="Check if the bot is responsive")
    async def ping_command(self, interaction: discord.Interaction):
        """Check bot latency."""
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(
            f"🏓 Pong! Latency: {latency}ms",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    await bot.add_cog(GeneralCog(bot))

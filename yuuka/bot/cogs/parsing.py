"""
Parsing Cog for transaction parsing commands and message handling.

Handles the /parse command and on_message event for natural language
transaction parsing.
"""

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import LedgerRepository
from yuuka.models import ParsedTransaction, TransactionAction
from yuuka.services import TransactionNLPService

# Confidence threshold below which we ask for user confirmation
LOW_CONFIDENCE_THRESHOLD = 0.7


def format_transaction(parsed: ParsedTransaction) -> str:
    """Format a parsed transaction for display in Discord."""
    action_emoji = {
        TransactionAction.INCOMING: "📥",
        TransactionAction.OUTGOING: "📤",
        TransactionAction.TRANSFER: "🔄",
    }

    emoji = action_emoji.get(parsed.action, "💰")
    amount_str = f"{parsed.amount:,.0f}" if parsed.amount else "N/A"

    lines = [
        f"{emoji} **{parsed.action.value.upper()}**",
        "```",
        f"Amount:      {amount_str}",
        f"Source:      {parsed.source or '-'}",
        f"Destination: {parsed.destination or '-'}",
        f"Description: {parsed.description or '-'}",
        f"Confidence:  {parsed.confidence:.0%}",
        "```",
    ]

    return "\n".join(lines)


def format_low_confidence_message(parsed: ParsedTransaction) -> str:
    """Format message for low-confidence parses asking for confirmation."""
    return (
        f"⚠️ I parsed your message but I'm not fully confident. "
        f"Is this correct?\n{format_transaction(parsed)}"
    )


class TransactionView(discord.ui.View):
    """View with confirmation buttons for low-confidence parses."""

    def __init__(
        self,
        parsed: ParsedTransaction,
        original_message: str,
        repository: LedgerRepository,
        user_id: str,
        channel_id: str,
        message_id: str,
        guild_id: Optional[str] = None,
    ):
        super().__init__(timeout=60.0)
        self.parsed = parsed
        self.original_message = original_message
        self.repository = repository
        self.user_id = user_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.guild_id = guild_id
        self.confirmed: bool | None = None

    @discord.ui.button(label="✓ Correct", style=discord.ButtonStyle.success)
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Handle confirmation that the parse is correct."""
        self.confirmed = True

        # Save to database
        entry = self.repository.insert(
            parsed=self.parsed,
            user_id=self.user_id,
            channel_id=self.channel_id,
            message_id=self.message_id,
            guild_id=self.guild_id,
            confirmed=True,
        )

        content = (
            f"✅ Confirmed! Transaction recorded (ID: `{entry.id}`):\n"
            f"{format_transaction(self.parsed)}"
        )
        await interaction.response.edit_message(content=content, view=None)
        self.stop()

    @discord.ui.button(label="✗ Incorrect", style=discord.ButtonStyle.danger)
    async def reject_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Handle rejection - parse was incorrect."""
        self.confirmed = False
        await interaction.response.edit_message(
            content=(
                "❌ Got it, transaction cancelled.\n"
                "Please try rephrasing your transaction message."
            ),
            view=None,
        )
        self.stop()

    async def on_timeout(self):
        """Called when the view times out."""
        self.confirmed = None


class ParsingCog(commands.Cog):
    """Cog for transaction parsing functionality."""

    def __init__(
        self,
        bot: commands.Bot,
        nlp_service: TransactionNLPService,
        repository: LedgerRepository,
    ):
        self.bot = bot
        self.nlp_service = nlp_service
        self.repository = repository

    @app_commands.command(name="parse", description="Parse a transaction message")
    @app_commands.describe(message="The transaction message to parse")
    async def parse_command(self, interaction: discord.Interaction, message: str):
        """Slash command to parse a transaction message."""
        parsed = self.nlp_service.parse(message)

        if not parsed.is_valid():
            await interaction.response.send_message(
                f"❓ I couldn't parse a valid transaction from your message:\n"
                f"```{message}```\n"
                "Please make sure to include an amount and source/destination.",
                ephemeral=True,
            )
            return

        user_id = str(interaction.user.id)
        channel_id = str(interaction.channel_id)
        guild_id = str(interaction.guild_id) if interaction.guild_id else None

        if parsed.confidence < LOW_CONFIDENCE_THRESHOLD:
            # Send first to get message ID
            await interaction.response.send_message(
                format_low_confidence_message(parsed),
            )
            response = await interaction.original_response()
            message_id = str(response.id)

            view = TransactionView(
                parsed=parsed,
                original_message=message,
                repository=self.repository,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_id,
                guild_id=guild_id,
            )
            await interaction.edit_original_response(view=view)
        else:
            # High confidence - save directly
            await interaction.response.send_message("Processing...")
            response = await interaction.original_response()
            message_id = str(response.id)

            entry = self.repository.insert(
                parsed=parsed,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_id,
                guild_id=guild_id,
                confirmed=True,
            )

            await interaction.edit_original_response(
                content=(
                    f"✅ Transaction recorded (ID: `{entry.id}`):\n"
                    f"{format_transaction(parsed)}"
                )
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle regular messages for transaction parsing."""
        # Ignore messages from the bot itself
        if message.author == self.bot.user:
            return

        # Ensure bot.user is available
        if self.bot.user is None:
            return

        # Check if this is a DM or if the bot is mentioned
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = self.bot.user in message.mentions

        # In DMs, process all messages; in channels, require mention
        if not is_dm and not is_mentioned:
            return

        # Remove the bot mention from the message if present
        content = message.content
        if is_mentioned:
            content = content.replace(f"<@{self.bot.user.id}>", "").strip()

        if not content:
            return

        parsed = self.nlp_service.parse(content)

        if not parsed.is_valid():
            await message.reply(
                "❓ I couldn't parse a valid transaction from your message.\n"
                "Please make sure to include an amount and source/destination.\n"
                "Use `/help` for examples."
            )
            return

        user_id = str(message.author.id)
        channel_id = str(message.channel.id)
        message_id = str(message.id)
        guild_id = str(message.guild.id) if message.guild else None

        if parsed.confidence < LOW_CONFIDENCE_THRESHOLD:
            view = TransactionView(
                parsed=parsed,
                original_message=content,
                repository=self.repository,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_id,
                guild_id=guild_id,
            )
            await message.reply(
                format_low_confidence_message(parsed),
                view=view,
            )
        else:
            # High confidence - save directly
            entry = self.repository.insert(
                parsed=parsed,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_id,
                guild_id=guild_id,
                confirmed=True,
            )

            await message.reply(
                f"✅ Transaction recorded (ID: `{entry.id}`):\n"
                f"{format_transaction(parsed)}"
            )


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    # This will be called with proper dependencies from the main bot setup
    pass

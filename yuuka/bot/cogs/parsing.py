"""
Parsing Cog for transaction parsing commands and message handling.

Handles the /parse command and on_message event for natural language
transaction parsing.
"""

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import LedgerRepository
from yuuka.models import ParsedTransaction, TransactionAction
from yuuka.services import TransactionNLPService

logger = logging.getLogger(__name__)

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


def format_asset_balances(repository: LedgerRepository, user_id: str) -> Optional[str]:
    """Format asset balances for display after transaction recording."""
    try:
        balance_sheet = repository.get_balance_sheet(user_id)

        if not balance_sheet or not balance_sheet.get("assets"):
            return None

        # Get assets sorted by recently used
        assets = sorted(
            balance_sheet["assets"],
            key=lambda x: x.get("last_used") or "",
            reverse=True,
        )

        if not assets:
            return None

        lines = ["", "💰 **Current Balances**", "```"]

        for asset in assets:
            name = asset["name"][:18] if asset["name"] else "Unknown"
            amount = asset["amount"]
            # Format with Rp prefix
            amount_str = f"Rp {amount:>14,.0f}"
            lines.append(f"{name:<18} | {amount_str}")

        lines.append("```")

        # Add total
        total_assets = balance_sheet["total_assets"]
        lines.append(f"💵 **Total:** Rp {total_assets:,.0f}")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Error formatting asset balances: {e}", exc_info=True)
        return None


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
        is_dm: bool = False,
    ):
        super().__init__(timeout=60.0)
        self.parsed = parsed
        self.original_message = original_message
        self.repository = repository
        self.user_id = user_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.guild_id = guild_id
        self.is_dm = is_dm
        self.confirmed: bool | None = None

    @discord.ui.button(label="✓ Correct", style=discord.ButtonStyle.success)
    async def confirm_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Handle confirmation that the parse is correct."""
        try:
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

            # Add asset balances
            balances = format_asset_balances(self.repository, self.user_id)
            if balances:
                content += balances

            await interaction.response.edit_message(content=content, view=None)
            logger.info(f"User {self.user_id} confirmed transaction {entry.id}")
            self.stop()
        except Exception as e:
            logger.error(f"Error in confirm_button: {e}", exc_info=True)
            await interaction.response.edit_message(
                content="❌ An error occurred while saving your transaction. Please try again with `/parse`.",
                view=None,
            )
            self.stop()

    @discord.ui.button(label="✗ Incorrect", style=discord.ButtonStyle.danger)
    async def reject_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Handle rejection - parse was incorrect."""
        try:
            self.confirmed = False
            await interaction.response.edit_message(
                content=(
                    "❌ Got it, transaction cancelled.\n"
                    "Please try rephrasing your transaction message."
                ),
                view=None,
            )
            logger.info(f"User {self.user_id} rejected transaction parse")
            self.stop()
        except Exception as e:
            logger.error(f"Error in reject_button: {e}", exc_info=True)
            self.stop()

    async def on_timeout(self):
        """Called when the view times out."""
        self.confirmed = None
        logger.info(f"Transaction confirmation timed out for user {self.user_id}")


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

    def _is_dm(self, interaction: discord.Interaction) -> bool:
        """Check if interaction is in a DM."""
        return interaction.guild is None

    @app_commands.command(name="parse", description="Parse a transaction message")
    @app_commands.describe(message="The transaction message to parse")
    async def parse_command(self, interaction: discord.Interaction, message: str):
        """Slash command to parse a transaction message."""
        try:
            is_dm = self._is_dm(interaction)

            # Validate input
            if not message or not message.strip():
                await interaction.response.send_message(
                    "❌ Please provide a transaction message to parse.",
                    ephemeral=not is_dm,
                )
                return

            # Limit message length to prevent abuse
            if len(message) > 500:
                await interaction.response.send_message(
                    "❌ Transaction message is too long (max 500 characters).",
                    ephemeral=not is_dm,
                )
                return

            parsed = self.nlp_service.parse(message)

            if not parsed.is_valid():
                await interaction.response.send_message(
                    f"❓ I couldn't parse a valid transaction from your message:\n"
                    f"```{message}```\n"
                    "Please make sure to include an amount and source/destination.",
                    ephemeral=not is_dm,
                )
                logger.info(
                    f"Invalid transaction parse for user {interaction.user.id}: {message}"
                )
                return

            user_id = str(interaction.user.id)
            channel_id = str(interaction.channel_id)
            guild_id = str(interaction.guild_id) if interaction.guild_id else None

            if parsed.confidence < LOW_CONFIDENCE_THRESHOLD:
                # Send first to get message ID
                await interaction.response.send_message(
                    format_low_confidence_message(parsed),
                    ephemeral=not is_dm,
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
                    is_dm=is_dm,
                )
                await interaction.edit_original_response(view=view)
                logger.info(
                    f"Low confidence parse for user {user_id}, awaiting confirmation"
                )
            else:
                # High confidence - save directly
                await interaction.response.send_message(
                    "Processing...",
                    ephemeral=not is_dm,
                )
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

                content = (
                    f"✅ Transaction recorded (ID: `{entry.id}`):\n"
                    f"{format_transaction(parsed)}"
                )

                # Add asset balances
                balances = format_asset_balances(self.repository, user_id)
                if balances:
                    content += balances

                await interaction.edit_original_response(content=content)
                logger.info(f"Transaction {entry.id} recorded for user {user_id}")
        except ValueError as e:
            logger.warning(f"Validation error in parse_command: {e}")
            await interaction.response.send_message(
                f"❌ Invalid input: {str(e)}",
                ephemeral=not self._is_dm(interaction),
            )
        except Exception as e:
            logger.error(f"Error in parse_command: {e}", exc_info=True)
            error_msg = "❌ An error occurred while processing your transaction. Please try again."
            if interaction.response.is_done():
                await interaction.followup.send(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )
            else:
                await interaction.response.send_message(
                    error_msg, ephemeral=not self._is_dm(interaction)
                )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle regular messages for transaction parsing."""
        try:
            # Ignore messages from the bot itself
            if message.author == self.bot.user:
                return

            # Ignore bot messages
            if message.author.bot:
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

            if not content or not content.strip():
                return

            # Limit message length to prevent abuse
            if len(content) > 500:
                await message.reply(
                    "❌ Transaction message is too long (max 500 characters)."
                )
                return

            parsed = self.nlp_service.parse(content)

            if not parsed.is_valid():
                await message.reply(
                    "❓ I couldn't parse a valid transaction from your message.\n"
                    "Please make sure to include an amount and source/destination.\n"
                    "Use `/help` for examples."
                )
                logger.info(
                    f"Invalid transaction parse from user {message.author.id}: {content}"
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
                    is_dm=is_dm,
                )
                await message.reply(
                    format_low_confidence_message(parsed),
                    view=view,
                )
                logger.info(
                    f"Low confidence parse from user {user_id}, awaiting confirmation"
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

                reply_content = (
                    f"✅ Transaction recorded (ID: `{entry.id}`):\n"
                    f"{format_transaction(parsed)}"
                )

                # Add asset balances
                balances = format_asset_balances(self.repository, user_id)
                if balances:
                    reply_content += balances

                await message.reply(reply_content)
                logger.info(f"Transaction {entry.id} recorded from user {user_id}")
        except ValueError as e:
            logger.warning(f"Validation error in on_message: {e}")
            await message.reply(f"❌ Invalid input: {str(e)}")
        except discord.HTTPException as e:
            logger.error(f"Discord API error in on_message: {e}", exc_info=True)
            # Don't reply if we can't send messages
        except Exception as e:
            logger.error(f"Error in on_message: {e}", exc_info=True)
            try:
                await message.reply(
                    "❌ An error occurred while processing your transaction. Please try again."
                )
            except Exception:
                # If we can't even send an error message, just log it
                logger.error("Could not send error message to user")


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    # This will be called with proper dependencies from the main bot setup
    pass

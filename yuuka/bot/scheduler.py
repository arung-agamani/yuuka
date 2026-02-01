"""
Scheduler module for automated tasks like daily recap.

Handles scheduling tasks to run at specific times using discord.ext.tasks.
"""

import asyncio
import logging
from datetime import time, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from discord.ext import tasks

if TYPE_CHECKING:
    from yuuka.bot.client import YuukaBot

logger = logging.getLogger(__name__)

# UTC+7 timezone (e.g., WIB - Western Indonesia Time)
UTC_PLUS_7 = timezone(timedelta(hours=7))

# Time to send daily recap (00:00 UTC+7)
DAILY_RECAP_TIME = time(hour=0, minute=0, second=0, tzinfo=UTC_PLUS_7)


class RecapScheduler:
    """Scheduler for automated daily recaps."""

    def __init__(self, bot: "YuukaBot"):
        """
        Initialize the scheduler.

        Args:
            bot: The YuukaBot instance
        """
        self.bot = bot
        self._started = False
        logger.info("RecapScheduler initialized")

    def start(self):
        """Start the scheduled tasks."""
        if not self._started:
            self.daily_recap_task.start()
            self._started = True
            logger.info(
                f"Daily recap scheduler started. "
                f"Will run at {DAILY_RECAP_TIME.strftime('%H:%M')} UTC+7 daily."
            )

    def stop(self):
        """Stop the scheduled tasks."""
        if self._started:
            self.daily_recap_task.cancel()
            self._started = False
            logger.info("Daily recap scheduler stopped")

    @tasks.loop(time=DAILY_RECAP_TIME)
    async def daily_recap_task(self):
        """Send daily recap to all users with budget config at 00:00 UTC+7."""
        logger.info("Starting daily recap task...")

        try:
            # Get all users who have daily recap enabled
            users_with_config = (
                self.bot.budget_repo.get_all_users_with_daily_recap_enabled()
            )

            if not users_with_config:
                logger.info("No users with daily recap enabled found")
                return

            logger.info(f"Sending daily recap to {len(users_with_config)} users")

            success_count = 0
            error_count = 0

            for user_id in users_with_config:
                try:
                    await self._send_recap_to_user(user_id)
                    success_count += 1
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(1)
                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"Failed to send recap to user {user_id}: {e}", exc_info=True
                    )

            logger.info(
                f"Daily recap task completed. "
                f"Success: {success_count}, Errors: {error_count}"
            )

        except Exception as e:
            logger.error(f"Error in daily recap task: {e}", exc_info=True)

    @daily_recap_task.before_loop
    async def before_daily_recap(self):
        """Wait until the bot is ready before starting the task."""
        await self.bot.wait_until_ready()
        logger.info("Bot is ready, daily recap scheduler is now active")

    @daily_recap_task.error
    async def daily_recap_error(self, error: BaseException):
        """Handle errors in the daily recap task."""
        logger.error(f"Error in daily_recap_task: {error}", exc_info=True)

    async def _send_recap_to_user(self, user_id: str):
        """
        Send a daily recap to a specific user via DM.

        Args:
            user_id: Discord user ID
        """
        try:
            # Get the Discord user
            user = await self.bot.fetch_user(int(user_id))

            if not user:
                logger.warning(f"Could not find Discord user {user_id}")
                return

            # Don't send to bots
            if user.bot:
                return

            # Generate recap
            recap = self.bot.recap_service.generate_recap(user_id)

            # Check if there's any data
            if (
                recap.current_balance == 0
                and recap.today_summary.transaction_count == 0
            ):
                logger.debug(f"No recap data for user {user_id}, skipping")
                return

            # Get budget for chart
            budget = self.bot.budget_repo.get_by_user(user_id)

            # Generate chart
            try:
                chart_buffer = self.bot.recap_service.generate_burndown_chart(
                    recap, budget
                )
            except Exception as e:
                logger.error(f"Failed to generate chart for user {user_id}: {e}")
                chart_buffer = None

            # Format message
            message = self.bot.recap_service.format_recap_message(recap)

            # Add header for automated recap
            message = (
                "🌅 **Good morning! Here's your daily financial recap:**\n\n" + message
            )

            # Send via DM
            try:
                dm_channel = await user.create_dm()

                if chart_buffer:
                    file = discord.File(chart_buffer, filename="daily_recap.png")
                    await dm_channel.send(content=message, file=file)
                    chart_buffer.close()
                else:
                    await dm_channel.send(content=message)

                logger.info(f"Sent daily recap to user {user_id}")

            except discord.Forbidden:
                logger.warning(
                    f"Cannot send DM to user {user_id} - DMs may be disabled"
                )
            except discord.HTTPException as e:
                logger.error(f"Discord API error sending recap to {user_id}: {e}")

        except Exception as e:
            logger.error(f"Error sending recap to user {user_id}: {e}", exc_info=True)
            raise

    async def send_manual_recap(self, user_id: str) -> bool:
        """
        Manually trigger a recap send to a user (for testing).

        Args:
            user_id: Discord user ID

        Returns:
            True if successful, False otherwise
        """
        try:
            await self._send_recap_to_user(user_id)
            return True
        except Exception as e:
            logger.error(f"Manual recap failed for user {user_id}: {e}")
            return False


def setup_scheduler(bot: "YuukaBot") -> RecapScheduler:
    """
    Create and configure the scheduler for the bot.

    Args:
        bot: The YuukaBot instance

    Returns:
        Configured RecapScheduler
    """
    scheduler = RecapScheduler(bot)
    return scheduler

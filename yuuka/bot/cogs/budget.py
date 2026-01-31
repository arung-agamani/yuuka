"""
Budget Cog for budget configuration and financial forecasting.

Handles the /budget and /forecast commands.
"""

from datetime import date
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from yuuka.db import BudgetRepository, LedgerRepository
from yuuka.services.recap import RecapService


class BudgetCog(commands.Cog):
    """Cog for budget configuration and forecasting functionality."""

    def __init__(
        self,
        bot: commands.Bot,
        repository: LedgerRepository,
        budget_repo: BudgetRepository,
        recap_service: RecapService,
    ):
        self.bot = bot
        self.repository = repository
        self.budget_repo = budget_repo
        self.recap_service = recap_service

    @app_commands.command(name="budget", description="Configure your budget settings")
    @app_commands.describe(
        daily_limit="Your daily spending limit",
        payday="Day of month when you get paid (1-31)",
        monthly_income="Your expected monthly income",
    )
    async def budget_command(
        self,
        interaction: discord.Interaction,
        daily_limit: Optional[float] = None,
        payday: Optional[int] = None,
        monthly_income: Optional[float] = None,
    ):
        """Configure budget settings for forecasting."""
        user_id = str(interaction.user.id)

        # Validate payday
        if payday is not None and (payday < 1 or payday > 31):
            await interaction.response.send_message(
                "❌ Payday must be between 1 and 31.",
                ephemeral=True,
            )
            return

        # If no arguments, show current config
        if daily_limit is None and payday is None and monthly_income is None:
            config = self.budget_repo.get_by_user(user_id)
            if config:
                monthly_inc_str = (
                    f"{config.monthly_income:,.0f}"
                    if config.monthly_income
                    else "Not set"
                )
                lines = [
                    "⚙️ **Your Budget Configuration**",
                    "```",
                    f"Daily Limit:     {config.daily_limit:>15,.0f}",
                    f"Payday:          {config.payday:>15} (day of month)",
                    f"Monthly Income:  {monthly_inc_str:>15}",
                    f"Warning at:      {config.warning_threshold * 100:>14.0f}%",
                    "```",
                    "",
                    f"Days until payday: **{config.days_until_payday()}**",
                ]
                await interaction.response.send_message(
                    "\n".join(lines), ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "📭 No budget configured yet.\n"
                    "Use `/budget daily_limit:<amount> payday:<day>` to set up.",
                    ephemeral=True,
                )
            return

        # Update/create config
        config = self.budget_repo.upsert(
            user_id=user_id,
            daily_limit=daily_limit,
            payday=payday,
            monthly_income=monthly_income,
        )

        await interaction.response.send_message(
            f"✅ Budget updated!\n"
            f"• Daily limit: **{config.daily_limit:,.0f}**\n"
            f"• Payday: **{config.payday}** (day of month)\n"
            f"• Days until payday: **{config.days_until_payday()}**",
            ephemeral=True,
        )

    @app_commands.command(name="forecast", description="See your financial forecast")
    async def forecast_command(self, interaction: discord.Interaction):
        """Show detailed financial forecast."""
        user_id = str(interaction.user.id)

        budget = self.budget_repo.get_by_user(user_id)
        if not budget:
            await interaction.response.send_message(
                "📭 No budget configured. Use `/budget` to set up your daily limit "
                "and payday first.",
                ephemeral=True,
            )
            return

        current_balance = self.repository.get_total_balance(user_id)
        forecast = self.recap_service.generate_forecast(
            user_id, budget, current_balance, date.today()
        )

        # Format forecast message
        if forecast.warning_level == "danger":
            emoji = "🚨"
            color_word = "RED ALERT"
        elif forecast.warning_level == "warning":
            emoji = "⚠️"
            color_word = "WARNING"
        else:
            emoji = "✅"
            color_word = "LOOKING GOOD"

        lines = [
            f"{emoji} **Financial Forecast: {color_word}**",
            "",
            "```",
            f"Current Balance:       {forecast.current_balance:>15,.0f}",
            f"Days until payday:     {forecast.days_until_payday:>15}",
            f"Your daily limit:      {forecast.daily_limit:>15,.0f}",
            "",
            f"Projected at payday:   {forecast.projected_balance_at_payday:>15,.0f}",
            "```",
        ]

        if forecast.is_at_risk:
            lines.append("")
            lines.append("🚨 **You're at risk of going into the red!**")
            if forecast.days_until_red is not None:
                if forecast.days_until_red == 0:
                    lines.append("• You're already in the red!")
                else:
                    lines.append(
                        f"• At current spending, you'll hit zero "
                        f"in **{forecast.days_until_red} days**"
                    )
            lines.append("")
            lines.append("💡 **To avoid going red:**")
            rec_limit = f"{forecast.recommended_daily_limit:,.0f}"
            lines.append(f"• Reduce daily spending to **{rec_limit}**")
            if forecast.savings_needed > 0:
                lines.append(
                    f"• Or add **{forecast.savings_needed:,.0f}** to your balance"
                )
        else:
            lines.append("")
            lines.append("🎉 You're on track to make it to payday!")
            buffer = forecast.projected_balance_at_payday
            lines.append(f"You'll have **{buffer:,.0f}** remaining.")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    """Setup function for loading the cog."""
    # This will be called with proper dependencies from the main bot setup
    pass

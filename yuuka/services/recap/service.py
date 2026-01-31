"""
Recap service for daily summaries and financial forecasting.

Provides functionality for:
- Daily transaction summaries
- Burndown chart visualization
- Financial health forecasting (will I go red before payday?)
"""

import io
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.ticker import FuncFormatter

from yuuka.db.budget import BudgetConfig, BudgetRepository
from yuuka.db.repository import LedgerRepository

# Use non-interactive backend for Discord bot
matplotlib.use("Agg")

logger = logging.getLogger(__name__)


@dataclass
class DailySummary:
    """Summary of a single day's transactions."""

    date: date
    incoming: float
    outgoing: float
    net: float
    transaction_count: int


@dataclass
class ForecastResult:
    """Result of financial forecasting."""

    current_balance: float
    days_until_payday: int
    daily_limit: float
    projected_balance_at_payday: float
    is_at_risk: bool  # Will go negative before payday?
    days_until_red: Optional[int]  # Days until balance goes negative
    recommended_daily_limit: float  # Suggested limit to avoid going red
    savings_needed: float  # Amount to save to avoid going red
    warning_level: str  # "safe", "warning", "danger"


@dataclass
class RecapReport:
    """Complete recap report for a user."""

    user_id: str
    report_date: date
    today_summary: DailySummary
    period_start: date  # Start of current pay period
    period_spending: float  # Total spending this period
    current_balance: float
    forecast: Optional[ForecastResult]
    daily_summaries: list[DailySummary]  # For chart data


class RecapService:
    """Service for generating daily recaps and financial forecasts."""

    def __init__(
        self,
        ledger_repo: LedgerRepository,
        budget_repo: BudgetRepository,
    ):
        """
        Initialize the recap service.

        Args:
            ledger_repo: Repository for ledger entries
            budget_repo: Repository for budget configurations
        """
        self.ledger_repo = ledger_repo
        self.budget_repo = budget_repo

        # Set up seaborn style
        try:
            sns.set_theme(style="darkgrid")
            logger.info("RecapService initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to set seaborn theme: {e}")

    def get_period_start(self, budget: BudgetConfig, for_date: date) -> date:
        """Calculate the start of the current pay period."""
        current_day = for_date.day
        current_month = for_date.month
        current_year = for_date.year

        if current_day >= budget.payday:
            # Period started this month
            try:
                return date(current_year, current_month, budget.payday)
            except ValueError:
                # Handle invalid day for month
                return date(current_year, current_month, 1)
        else:
            # Period started last month
            if current_month == 1:
                prev_month = 12
                prev_year = current_year - 1
            else:
                prev_month = current_month - 1
                prev_year = current_year

            try:
                return date(prev_year, prev_month, budget.payday)
            except ValueError:
                return date(prev_year, prev_month, 1)

    def generate_daily_summary(self, user_id: str, for_date: date) -> DailySummary:
        """Generate a summary for a specific day."""
        entries = self.ledger_repo.get_entries_for_date_range(
            user_id, for_date, for_date
        )

        incoming = sum(e.amount for e in entries if e.action == "incoming")
        outgoing = sum(e.amount for e in entries if e.action == "outgoing")

        return DailySummary(
            date=for_date,
            incoming=incoming,
            outgoing=outgoing,
            net=incoming - outgoing,
            transaction_count=len(entries),
        )

    def generate_forecast(
        self,
        user_id: str,
        budget: BudgetConfig,
        current_balance: float,
        for_date: date,
    ) -> ForecastResult:
        """
        Generate financial forecast based on current spending patterns.

        Args:
            user_id: Discord user ID
            budget: User's budget configuration
            current_balance: Current total balance
            for_date: Date to forecast from

        Returns:
            ForecastResult with projections and recommendations
        """
        days_until_payday = budget.days_until_payday(for_date)
        daily_limit = budget.daily_limit

        # Project balance at payday if spending at daily limit
        projected_spending = daily_limit * days_until_payday
        projected_balance = current_balance - projected_spending

        # Calculate if/when balance goes negative
        is_at_risk = False
        days_until_red = None

        if current_balance <= 0:
            is_at_risk = True
            days_until_red = 0
        elif daily_limit > 0:
            # Days until red at current daily limit
            days_at_current_rate = current_balance / daily_limit
            if days_at_current_rate < days_until_payday:
                is_at_risk = True
                days_until_red = int(days_at_current_rate)

        # Calculate recommended daily limit to avoid going red
        if days_until_payday > 0:
            recommended_daily_limit = current_balance / days_until_payday
        else:
            recommended_daily_limit = current_balance

        # Ensure recommended limit is not negative
        recommended_daily_limit = max(0, recommended_daily_limit)

        # Calculate savings needed to maintain current daily limit
        needed_for_period = daily_limit * days_until_payday
        savings_needed = max(0, needed_for_period - current_balance)

        # Determine warning level
        if current_balance <= 0:
            warning_level = "danger"
        elif is_at_risk:
            warning_level = "danger"
        elif current_balance < (
            daily_limit * days_until_payday * budget.warning_threshold
        ):
            warning_level = "warning"
        else:
            warning_level = "safe"

        return ForecastResult(
            current_balance=current_balance,
            days_until_payday=days_until_payday,
            daily_limit=daily_limit,
            projected_balance_at_payday=projected_balance,
            is_at_risk=is_at_risk,
            days_until_red=days_until_red,
            recommended_daily_limit=recommended_daily_limit,
            savings_needed=savings_needed,
            warning_level=warning_level,
        )

    def generate_recap(
        self,
        user_id: str,
        for_date: Optional[date] = None,
    ) -> RecapReport:
        """
        Generate a complete recap report for a user.

        Args:
            user_id: Discord user ID
            for_date: Date to generate recap for (defaults to today)

        Returns:
            Complete RecapReport
        """
        if for_date is None:
            for_date = date.today()

        # Get budget config (or use defaults)
        budget = self.budget_repo.get_by_user(user_id)

        # Get current balance
        current_balance = self.ledger_repo.get_total_balance(user_id)

        # Generate today's summary
        today_summary = self.generate_daily_summary(user_id, for_date)

        # Calculate period info
        if budget:
            period_start = self.get_period_start(budget, for_date)
            period_spending = self.ledger_repo.get_spending_since_date(
                user_id, period_start
            )
            forecast = self.generate_forecast(
                user_id, budget, current_balance, for_date
            )
        else:
            # No budget config - use last 30 days as period
            period_start = for_date - timedelta(days=30)
            period_spending = self.ledger_repo.get_spending_since_date(
                user_id, period_start
            )
            forecast = None

        # Get daily summaries for the period (for chart)
        daily_totals = self.ledger_repo.get_daily_totals(
            user_id, period_start, for_date
        )
        daily_summaries = [
            DailySummary(
                date=date.fromisoformat(day) if isinstance(day, str) else day,
                incoming=totals["incoming"],
                outgoing=totals["outgoing"],
                net=totals.get("net", totals["incoming"] - totals["outgoing"]),
                transaction_count=0,  # Not tracked in daily_totals
            )
            for day, totals in sorted(daily_totals.items())
        ]

        return RecapReport(
            user_id=user_id,
            report_date=for_date,
            today_summary=today_summary,
            period_start=period_start,
            period_spending=period_spending,
            current_balance=current_balance,
            forecast=forecast,
            daily_summaries=daily_summaries,
        )

    def generate_burndown_chart(
        self,
        recap: RecapReport,
        budget: Optional[BudgetConfig] = None,
    ) -> io.BytesIO:
        """
        Generate a burndown chart showing balance over time with forecast.

        Args:
            recap: The recap report data
            budget: Optional budget config for forecast line

        Returns:
            BytesIO buffer containing the PNG image

        Raises:
            ValueError: If recap data is invalid
        """
        if not recap:
            raise ValueError("recap cannot be None")

        fig = None
        try:
            # Prepare data
            dates = [s.date for s in recap.daily_summaries]

            if not dates:
                # No data - create empty chart
                fig, ax = plt.subplots(figsize=(10, 6))
                ax.text(
                    0.5,
                    0.5,
                    "No transaction data available",
                    ha="center",
                    va="center",
                    fontsize=14,
                )
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
                buf.seek(0)
                plt.close(fig)
                logger.debug("Generated empty burndown chart")
                return buf

            # Calculate running balance
            running_balance = []
            balance = recap.current_balance

            # Work backwards from current balance
            daily_nets = [s.net for s in recap.daily_summaries]
            cumulative_net = sum(daily_nets)
            starting_balance = balance - cumulative_net

            current = starting_balance
            for summary in recap.daily_summaries:
                current += summary.net
                running_balance.append(current)

            # Create DataFrame
            df = pd.DataFrame(
                {
                    "Date": dates,
                    "Balance": running_balance,
                    "Daily Spending": [s.outgoing for s in recap.daily_summaries],
                    "Daily Income": [s.incoming for s in recap.daily_summaries],
                }
            )

            # Create figure with two subplots
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[2, 1])

            # Color palette
            colors = {
                "balance": "#2ecc71",  # Green
                "forecast": "#e74c3c",  # Red
                "ideal": "#3498db",  # Blue
                "spending": "#e74c3c",  # Red
                "income": "#2ecc71",  # Green
                "danger_zone": "#ffcccc",  # Light red
            }

            # Plot 1: Balance burndown
            ax1.fill_between(
                df["Date"],
                0,
                df["Balance"],
                alpha=0.3,
                color=colors["balance"],
                label="_nolegend_",
            )
            ax1.plot(
                df["Date"],
                df["Balance"],
                color=colors["balance"],
                linewidth=2.5,
                marker="o",
                markersize=4,
                label="Actual Balance",
            )

            # Add forecast line if budget is configured
            if budget and recap.forecast:
                forecast_dates = []
                forecast_balance = []

                last_date = dates[-1]
                last_balance = running_balance[-1]

                for i in range(recap.forecast.days_until_payday + 1):
                    forecast_date = last_date + timedelta(days=i)
                    forecast_dates.append(forecast_date)
                    forecast_balance.append(last_balance - (budget.daily_limit * i))

                ax1.plot(
                    forecast_dates,
                    forecast_balance,
                    color=colors["forecast"],
                    linewidth=2,
                    linestyle="--",
                    marker="",
                    label=f"Forecast (@ {budget.daily_limit:,.0f}/day)",
                )

                # Add ideal spending line
                ideal_daily = last_balance / max(recap.forecast.days_until_payday, 1)
                ideal_balance = [
                    last_balance - (ideal_daily * i) for i in range(len(forecast_dates))
                ]
                ax1.plot(
                    forecast_dates,
                    ideal_balance,
                    color=colors["ideal"],
                    linewidth=1.5,
                    linestyle=":",
                    label=f"Ideal (@ {ideal_daily:,.0f}/day)",
                )

                # Shade danger zone (below zero)
                ax1.axhline(y=0, color="red", linestyle="-", linewidth=1, alpha=0.7)
                ax1.fill_between(
                    forecast_dates,
                    [min(min(forecast_balance), 0)] * len(forecast_dates),
                    0,
                    alpha=0.2,
                    color=colors["danger_zone"],
                    label="_nolegend_",
                )

            ax1.set_title("Balance Burndown Chart", fontsize=14, fontweight="bold")
            ax1.set_xlabel("")
            ax1.set_ylabel("Balance", fontsize=11)
            ax1.legend(loc="upper right")
            ax1.tick_params(axis="x", rotation=45)

            # Format y-axis with thousands separator
            ax1.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f"{x:,.0f}"))

            # Plot 2: Daily spending vs income
            bar_width = 0.35
            x = range(len(df))

            ax2.bar(
                [i - bar_width / 2 for i in x],
                df["Daily Income"],
                bar_width,
                label="Income",
                color=colors["income"],
                alpha=0.8,
            )
            ax2.bar(
                [i + bar_width / 2 for i in x],
                df["Daily Spending"],
                bar_width,
                label="Spending",
                color=colors["spending"],
                alpha=0.8,
            )

            # Add daily limit line if configured
            if budget:
                ax2.axhline(
                    y=budget.daily_limit,
                    color=colors["ideal"],
                    linestyle="--",
                    linewidth=2,
                    label=f"Daily Limit ({budget.daily_limit:,.0f})",
                )

            ax2.set_title("Daily Income vs Spending", fontsize=14, fontweight="bold")
            ax2.set_xlabel("Date", fontsize=11)
            ax2.set_ylabel("Amount", fontsize=11)
            ax2.set_xticks(x)
            ax2.set_xticklabels([d.strftime("%m/%d") for d in df["Date"]], rotation=45)
            ax2.legend(loc="upper right")
            ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, p: f"{x:,.0f}"))

            # Adjust layout
            plt.tight_layout()

            # Save to buffer
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            buf.seek(0)

            logger.debug(f"Generated burndown chart for user {recap.user_id}")
            return buf
        except Exception as e:
            logger.error(f"Error generating burndown chart: {e}", exc_info=True)
            raise
        finally:
            # Always close the figure to free memory
            if fig is not None:
                plt.close(fig)

    def format_recap_message(self, recap: RecapReport) -> str:
        """
        Format the recap report as a Discord message.

        Args:
            recap: The recap report to format

        Returns:
            Formatted message string

        Raises:
            ValueError: If recap is invalid
        """
        if not recap:
            raise ValueError("recap cannot be None")

        try:
            lines = [
                f"📅 **Daily Recap for {recap.report_date.strftime('%A, %B %d, %Y')}**",
                "",
            ]

            # Today's summary
            lines.append("**Today's Activity:**")
            lines.append("```")
            lines.append(f"📥 Income:    {recap.today_summary.incoming:>15,.0f}")
            lines.append(f"📤 Spending:  {recap.today_summary.outgoing:>15,.0f}")
            lines.append(f"📊 Net:       {recap.today_summary.net:>15,.0f}")
            lines.append(f"📝 Transactions: {recap.today_summary.transaction_count}")
            lines.append("```")

            # Period summary
            lines.append("")
            lines.append(
                f"**Period Summary** (since {recap.period_start.strftime('%b %d')}):"
            )
            lines.append("```")
            lines.append(f"💸 Total Spent: {recap.period_spending:>15,.0f}")
            lines.append(f"💰 Balance:     {recap.current_balance:>15,.0f}")
            lines.append("```")

            # Forecast section
            if recap.forecast:
                forecast = recap.forecast
                lines.append("")

                # Warning emoji based on level
                if forecast.warning_level == "danger":
                    emoji = "🚨"
                    status = "DANGER"
                elif forecast.warning_level == "warning":
                    emoji = "⚠️"
                    status = "WARNING"
                else:
                    emoji = "✅"
                    status = "SAFE"

                lines.append(f"**Forecast** {emoji} {status}")
                lines.append("```")
                lines.append(f"Days until payday:     {forecast.days_until_payday:>10}")
                lines.append(f"Daily limit:           {forecast.daily_limit:>10,.0f}")
                lines.append(
                    f"Projected at payday:   {forecast.projected_balance_at_payday:>10,.0f}"
                )
                lines.append("```")

                if forecast.is_at_risk:
                    lines.append("")
                    lines.append("⚠️ **Risk Alert:**")
                    if (
                        forecast.days_until_red is not None
                        and forecast.days_until_red > 0
                    ):
                        days_before = (
                            forecast.days_until_payday - forecast.days_until_red
                        )
                        lines.append(
                            f"At your current daily limit, you'll run out of money "
                            f"in **{forecast.days_until_red} days** "
                            f"({days_before} days before payday)."
                        )
                    elif forecast.days_until_red == 0:
                        lines.append("⚠️ You're already in the red!")

                    lines.append("")
                    lines.append("💡 **Recommendations:**")
                    rec_limit = f"{forecast.recommended_daily_limit:,.0f}"
                    lines.append(
                        f"• Reduce daily spending to **{rec_limit}** to make it to payday"
                    )
                    if forecast.savings_needed > 0:
                        lines.append(
                            f"• Or find an additional **{forecast.savings_needed:,.0f}** "
                            f"to maintain current spending"
                        )

            message = "\n".join(lines)
            logger.debug(f"Formatted recap message for user {recap.user_id}")
            return message
        except Exception as e:
            logger.error(f"Error formatting recap message: {e}", exc_info=True)
            raise

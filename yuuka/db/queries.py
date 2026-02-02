"""
Queries repository module for balance calculations and analytics.

Handles all query-related database operations including:
- Balance calculations (by account, total, asset-only)
- Date range queries
- Daily totals and spending analytics
- Account ledger queries
"""

import logging
from datetime import date, datetime
from typing import Any, Optional

from yuuka.models.account import AccountType, EntryType

from .base import BaseRepository
from .models import LedgerEntry

logger = logging.getLogger(__name__)


class QueryRepository(BaseRepository):
    """
    Repository for balance calculations and analytics queries.

    Provides read-only query operations for analyzing ledger data.
    """

    def __init__(self, db_path=None, init_schema: bool = False):
        """
        Initialize the query repository.

        Args:
            db_path: Path to the SQLite database file
            init_schema: Whether to initialize schema
        """
        super().__init__(db_path, init_schema=init_schema)

    # =========================================================================
    # Balance Queries
    # =========================================================================

    def get_user_balance_by_account(self, user_id: str) -> dict[str, float]:
        """
        Calculate balance for each account using double-entry bookkeeping.

        This properly calculates balances based on account types:
        - Asset/Expense accounts: balance = debits - credits
        - Liability/Equity/Revenue accounts: balance = credits - debits

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary mapping account names to their balances
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        try:
            with self._get_connection() as conn:
                # Get all journal entries grouped by account name and entry type
                cursor = conn.execute(
                    """
                    SELECT
                        je.account_name as name,
                        je.entry_type,
                        SUM(je.amount) as total
                    FROM journal_entries je
                    JOIN transactions t ON je.transaction_id = t.id
                    WHERE t.user_id = ?
                    GROUP BY je.account_name, je.entry_type
                    """,
                    (user_id,),
                )

                # Calculate balances using proper accounting rules
                account_debits: dict[str, float] = {}
                account_credits: dict[str, float] = {}
                account_types: dict[str, AccountType] = {}

                rows = cursor.fetchall()

                # First pass: collect debits and credits
                for row in rows:
                    account_name = row["name"]
                    entry_type = EntryType(row["entry_type"])
                    amount = row["total"] or 0.0

                    if account_name not in account_debits:
                        account_debits[account_name] = 0.0
                        account_credits[account_name] = 0.0

                    if entry_type == EntryType.DEBIT:
                        account_debits[account_name] += amount
                    else:
                        account_credits[account_name] += amount

                # Second pass: lookup account types by name
                for account_name in account_debits.keys():
                    # Try account_groups first
                    type_cursor = conn.execute(
                        """
                        SELECT account_type FROM account_groups
                        WHERE name = ? AND user_id = ?
                        """,
                        (account_name, user_id),
                    )
                    type_row = type_cursor.fetchone()

                    if type_row:
                        account_types[account_name] = AccountType(
                            type_row["account_type"]
                        )
                    else:
                        # Fall back to accounts table
                        type_cursor = conn.execute(
                            """
                            SELECT account_type FROM accounts
                            WHERE name = ? AND user_id = ?
                            """,
                            (account_name, user_id),
                        )
                        type_row = type_cursor.fetchone()

                        if type_row:
                            account_types[account_name] = AccountType(
                                type_row["account_type"]
                            )
                        else:
                            # Default to asset if not found anywhere
                            account_types[account_name] = AccountType.ASSET

                # Calculate final balances based on account type
                balances: dict[str, float] = {}
                debit_normal_types = {AccountType.ASSET, AccountType.EXPENSE}

                for account_name in account_types:
                    account_type = account_types[account_name]
                    debit_total = account_debits[account_name]
                    credit_total = account_credits[account_name]

                    if account_type in debit_normal_types:
                        # Asset/Expense: Debits increase, Credits decrease
                        balances[account_name] = debit_total - credit_total
                    else:
                        # Liability/Equity/Revenue: Credits increase, Debits decrease
                        balances[account_name] = credit_total - debit_total

                logger.debug(
                    f"Calculated balances for {len(balances)} accounts "
                    f"for user {user_id}"
                )
                return balances
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting balances for user {user_id}: {e}", exc_info=True
            )
            raise

    def get_total_balance(self, user_id: str) -> float:
        """
        Get the total balance (sum of all asset accounts) for a user.

        In double-entry bookkeeping, this calculates the net position
        by summing asset account balances.

        Args:
            user_id: Discord user ID

        Returns:
            Total balance
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            # For a simple total, we use the net of incoming vs outgoing
            # which is effectively the sum of asset account balances
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT
                        COALESCE(SUM(
                            CASE WHEN action = 'incoming' THEN amount ELSE 0 END
                        ), 0) -
                        COALESCE(SUM(
                            CASE WHEN action = 'outgoing' THEN amount ELSE 0 END
                        ), 0) as balance
                    FROM ledger_entries
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
                result = cursor.fetchone()
                balance = result[0] if result else 0.0
                logger.debug(f"Total balance for user {user_id}: {balance}")
                return balance
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting balance for user {user_id}: {e}", exc_info=True
            )
            raise

    def get_asset_balances(self, user_id: str) -> dict[str, float]:
        """
        Get balances for all asset accounts.

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary mapping asset account names to their balances
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            balance_sheet = self.get_balance_sheet(user_id)
            assets = {}
            for asset in balance_sheet.get("assets", []):
                assets[asset["name"]] = asset["amount"]
            return assets
        except Exception as e:
            logger.error(
                f"Error getting asset balances for user {user_id}: {e}",
                exc_info=True,
            )
            raise

    # =========================================================================
    # Account Ledger Queries
    # =========================================================================

    def get_account_ledger(
        self,
        user_id: str,
        account_name: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get ledger entries for a specific account.

        Args:
            user_id: Discord user ID
            account_name: Account name to get ledger for
            limit: Maximum number of entries

        Returns:
            List of ledger entries with running balance
        """
        if not user_id:
            raise ValueError("User ID is required")
        if not account_name:
            raise ValueError("Account name is required")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT
                        t.id as transaction_id,
                        t.description,
                        t.created_at,
                        je.entry_type,
                        je.amount
                    FROM journal_entries je
                    JOIN transactions t ON je.transaction_id = t.id
                    WHERE t.user_id = ? AND je.account_name = ?
                    ORDER BY t.created_at DESC
                    LIMIT ?
                    """,
                    (user_id, account_name, limit),
                )

                entries = []
                for row in cursor.fetchall():
                    entries.append(
                        {
                            "transaction_id": row["transaction_id"],
                            "description": row["description"],
                            "created_at": row["created_at"],
                            "entry_type": row["entry_type"],
                            "amount": row["amount"],
                        }
                    )

                return entries
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting account ledger for {account_name}: {e}",
                exc_info=True,
            )
            raise

    # =========================================================================
    # Date Range Queries
    # =========================================================================

    def get_entries_for_date_range(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[LedgerEntry]:
        """
        Get entries for a date range.

        Args:
            user_id: Discord user ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of LedgerEntry objects
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            with self._get_connection() as conn:
                query = """
                    SELECT id, action, amount, source, destination, description,
                           raw_text, confidence, user_id, guild_id, channel_id,
                           message_id, created_at, confirmed, transaction_id
                    FROM ledger_entries
                    WHERE user_id = ?
                """
                params: list = [user_id]

                if start_date:
                    query += " AND date(created_at) >= ?"
                    params.append(start_date.isoformat())

                if end_date:
                    query += " AND date(created_at) <= ?"
                    params.append(end_date.isoformat())

                query += " ORDER BY created_at DESC"

                cursor = conn.execute(query, params)

                entries = []
                for row in cursor.fetchall():
                    entries.append(
                        LedgerEntry(
                            id=row[0],
                            action=row[1],
                            amount=row[2],
                            source=row[3],
                            destination=row[4],
                            description=row[5],
                            raw_text=row[6],
                            confidence=row[7],
                            user_id=row[8],
                            guild_id=row[9],
                            channel_id=row[10],
                            message_id=row[11],
                            created_at=datetime.fromisoformat(row[12]),
                            confirmed=bool(row[13]),
                            transaction_id=row[14],
                        )
                    )

                return entries
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error getting entries for date range: {e}", exc_info=True)
            raise

    def get_entries_for_today(self, user_id: str) -> list[LedgerEntry]:
        """Get all entries for today."""
        today = date.today()
        return self.get_entries_for_date_range(user_id, today, today)

    # =========================================================================
    # Analytics Queries
    # =========================================================================

    def get_daily_totals(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, dict[str, float]]:
        """
        Get daily totals for incoming and outgoing transactions.

        Args:
            user_id: Discord user ID
            start_date: Start date
            end_date: End date

        Returns:
            Dictionary mapping dates to {incoming, outgoing} totals
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT
                        date(created_at) as day,
                        action,
                        SUM(amount) as total
                    FROM ledger_entries
                    WHERE user_id = ?
                      AND date(created_at) >= ?
                      AND date(created_at) <= ?
                    GROUP BY date(created_at), action
                    ORDER BY day
                    """,
                    (user_id, start_date.isoformat(), end_date.isoformat()),
                )

                daily_totals: dict[str, dict[str, float]] = {}

                for row in cursor.fetchall():
                    day = row["day"]
                    action = row["action"]
                    total = row["total"] or 0.0

                    if day not in daily_totals:
                        daily_totals[day] = {"incoming": 0.0, "outgoing": 0.0}

                    if action in ("incoming", "outgoing"):
                        daily_totals[day][action] = total

                return daily_totals
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error getting daily totals: {e}", exc_info=True)
            raise

    def get_spending_by_category(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, float]:
        """
        Get spending breakdown by expense category (account group).

        Args:
            user_id: Discord user ID
            start_date: Start date
            end_date: End date

        Returns:
            Dictionary mapping expense account names to total spent
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            with self._get_connection() as conn:
                # Get outgoing transactions summed by destination (expense category)
                cursor = conn.execute(
                    """
                    SELECT
                        je.account_name,
                        SUM(je.amount) as total
                    FROM journal_entries je
                    JOIN transactions t ON je.transaction_id = t.id
                    WHERE t.user_id = ?
                      AND date(t.created_at) >= ?
                      AND date(t.created_at) <= ?
                      AND je.entry_type = 'debit'
                      AND je.account_name IN (
                          SELECT name FROM account_groups
                          WHERE user_id = ? AND account_type = 'expense'
                      )
                    GROUP BY je.account_name
                    ORDER BY total DESC
                    """,
                    (user_id, start_date.isoformat(), end_date.isoformat(), user_id),
                )

                categories: dict[str, float] = {}
                for row in cursor.fetchall():
                    categories[row["account_name"]] = row["total"] or 0.0

                # If no categories found from account_groups, try legacy approach
                if not categories:
                    cursor = conn.execute(
                        """
                        SELECT
                            COALESCE(destination, 'Other') as category,
                            SUM(amount) as total
                        FROM ledger_entries
                        WHERE user_id = ?
                          AND action = 'outgoing'
                          AND date(created_at) >= ?
                          AND date(created_at) <= ?
                        GROUP BY destination
                        ORDER BY total DESC
                        """,
                        (user_id, start_date.isoformat(), end_date.isoformat()),
                    )
                    for row in cursor.fetchall():
                        categories[row["category"]] = row["total"] or 0.0

                logger.debug(
                    f"Got spending by category for user {user_id}: "
                    f"{len(categories)} categories"
                )
                return categories

        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting spending by category for user {user_id}: {e}",
                exc_info=True,
            )
            raise

    def get_spending_since_date(self, user_id: str, since_date: date) -> float:
        """
        Get total spending (outgoing) since a specific date.

        Args:
            user_id: Discord user ID
            since_date: Start date

        Returns:
            Total spending amount
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT COALESCE(SUM(amount), 0) as total
                    FROM ledger_entries
                    WHERE user_id = ?
                      AND action = 'outgoing'
                      AND date(created_at) >= ?
                    """,
                    (user_id, since_date.isoformat()),
                )
                result = cursor.fetchone()
                return result[0] if result else 0.0
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting spending since {since_date}: {e}", exc_info=True
            )
            raise

    # =========================================================================
    # Financial Reports
    # =========================================================================

    def get_trial_balance(self, user_id: str) -> dict[str, Any]:
        """
        Generate a trial balance report.

        Shows all accounts with their debit and credit balances.
        Total debits should equal total credits.

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary with trial balance data
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT
                        je.account_name as name,
                        je.entry_type,
                        SUM(je.amount) as total
                    FROM journal_entries je
                    JOIN transactions t ON je.transaction_id = t.id
                    WHERE t.user_id = ?
                    GROUP BY je.account_name, je.entry_type
                    ORDER BY je.account_name
                    """,
                    (user_id,),
                )

                accounts: dict[str, dict[str, float]] = {}
                total_debits = 0.0
                total_credits = 0.0

                for row in cursor.fetchall():
                    name = row["name"]
                    entry_type = row["entry_type"]
                    amount = row["total"] or 0.0

                    if name not in accounts:
                        accounts[name] = {"debit": 0.0, "credit": 0.0}

                    accounts[name][entry_type] = amount

                    if entry_type == "debit":
                        total_debits += amount
                    else:
                        total_credits += amount

                return {
                    "accounts": accounts,
                    "total_debits": total_debits,
                    "total_credits": total_credits,
                    "is_balanced": abs(total_debits - total_credits) < 0.01,
                }
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error generating trial balance: {e}", exc_info=True)
            raise

    def get_income_statement(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        Generate an income statement (profit & loss).

        Shows revenue, expenses, and net income for a period.

        Args:
            user_id: Discord user ID
            start_date: Start of period (optional)
            end_date: End of period (optional)

        Returns:
            Dictionary with income statement data
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            with self._get_connection() as conn:
                # Build date filter
                date_filter = ""
                params: list = [user_id]

                if start_date:
                    date_filter += " AND date(t.created_at) >= ?"
                    params.append(start_date.isoformat())
                if end_date:
                    date_filter += " AND date(t.created_at) <= ?"
                    params.append(end_date.isoformat())

                # Get revenue (credits to revenue accounts)
                cursor = conn.execute(
                    f"""
                    SELECT je.account_name, SUM(je.amount) as total
                    FROM journal_entries je
                    JOIN transactions t ON je.transaction_id = t.id
                    JOIN account_groups ag ON je.account_name = ag.name
                        AND ag.user_id = t.user_id
                    WHERE t.user_id = ?
                      AND ag.account_type = 'revenue'
                      AND je.entry_type = 'credit'
                      {date_filter}
                    GROUP BY je.account_name
                    """,
                    params,
                )

                revenue = []
                total_revenue = 0.0
                for row in cursor.fetchall():
                    amount = row["total"] or 0.0
                    revenue.append({"name": row["account_name"], "amount": amount})
                    total_revenue += amount

                # Get expenses (debits to expense accounts)
                cursor = conn.execute(
                    f"""
                    SELECT je.account_name, SUM(je.amount) as total
                    FROM journal_entries je
                    JOIN transactions t ON je.transaction_id = t.id
                    JOIN account_groups ag ON je.account_name = ag.name
                        AND ag.user_id = t.user_id
                    WHERE t.user_id = ?
                      AND ag.account_type = 'expense'
                      AND je.entry_type = 'debit'
                      {date_filter}
                    GROUP BY je.account_name
                    """,
                    params,
                )

                expenses = []
                total_expenses = 0.0
                for row in cursor.fetchall():
                    amount = row["total"] or 0.0
                    expenses.append({"name": row["account_name"], "amount": amount})
                    total_expenses += amount

                return {
                    "revenue": revenue,
                    "expenses": expenses,
                    "total_revenue": total_revenue,
                    "total_expenses": total_expenses,
                    "net_income": total_revenue - total_expenses,
                }
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error generating income statement: {e}", exc_info=True)
            raise

    def get_balance_sheet(self, user_id: str) -> dict[str, Any]:
        """
        Generate a balance sheet.

        Shows assets, liabilities, and equity at a point in time.
        Assets = Liabilities + Equity (+ Retained Earnings)

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary with balance sheet data
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            balances = self.get_user_balance_by_account(user_id)

            with self._get_connection() as conn:
                # Get account types by looking up account names
                cursor = conn.execute(
                    """
                    SELECT DISTINCT je.account_name as name
                    FROM journal_entries je
                    JOIN transactions t ON je.transaction_id = t.id
                    WHERE t.user_id = ?
                    """,
                    (user_id,),
                )

                account_names = [row["name"] for row in cursor.fetchall()]
                account_types = {}

                for name in account_names:
                    # Try to find in account_groups first
                    group_cursor = conn.execute(
                        """
                        SELECT account_type FROM account_groups
                        WHERE name = ? AND user_id = ?
                        """,
                        (name, user_id),
                    )
                    group_row = group_cursor.fetchone()

                    if group_row:
                        account_types[name] = AccountType(group_row["account_type"])
                    else:
                        # Fall back to accounts table
                        account_cursor = conn.execute(
                            """
                            SELECT account_type FROM accounts
                            WHERE name = ? AND user_id = ?
                            """,
                            (name, user_id),
                        )
                        account_row = account_cursor.fetchone()

                        if account_row:
                            account_types[name] = AccountType(
                                account_row["account_type"]
                            )
                        else:
                            # Default to asset if not found
                            account_types[name] = AccountType.ASSET

            # Aggregate balances by resolved group names
            aggregated_balances = {}
            aggregated_types = {}

            for account_name, balance in balances.items():
                account_type = account_types.get(account_name, AccountType.ASSET)

                # Try to resolve to group name if it's an alias
                with self._get_connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT g.name
                        FROM account_groups g
                        JOIN account_aliases a ON g.id = a.group_id
                        WHERE a.alias = ? AND a.user_id = ?
                        """,
                        (account_name.lower(), user_id),
                    )
                    row = cursor.fetchone()
                    display_name = row["name"] if row else account_name

                # Aggregate balances with same display name
                if display_name not in aggregated_balances:
                    aggregated_balances[display_name] = 0.0
                    aggregated_types[display_name] = account_type

                aggregated_balances[display_name] += balance

            # Build balance sheet from aggregated data
            assets = []
            liabilities = []
            equity = []
            total_assets = 0.0
            total_liabilities = 0.0
            total_equity = 0.0

            for display_name, balance in aggregated_balances.items():
                account_type = aggregated_types[display_name]

                if account_type == AccountType.ASSET:
                    assets.append({"name": display_name, "amount": balance})
                    total_assets += balance
                elif account_type == AccountType.LIABILITY:
                    liabilities.append({"name": display_name, "amount": balance})
                    total_liabilities += balance
                elif account_type == AccountType.EQUITY:
                    equity.append({"name": display_name, "amount": balance})
                    total_equity += balance
                # Revenue and Expense contribute to retained earnings
                elif account_type == AccountType.REVENUE:
                    total_equity += balance
                elif account_type == AccountType.EXPENSE:
                    total_equity -= balance

            return {
                "assets": assets,
                "liabilities": liabilities,
                "equity": equity,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_equity": total_equity,
                "is_balanced": abs(total_assets - (total_liabilities + total_equity))
                < 0.01,
            }
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error generating balance sheet: {e}", exc_info=True)
            raise

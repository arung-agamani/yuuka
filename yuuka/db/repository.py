"""
Database repository for ledger operations.

Handles SQLite connection, schema initialization, and CRUD operations
for ledger entries.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from yuuka.models import ParsedTransaction, TransactionAction

from .models import LedgerEntry

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "yuuka.db"


class LedgerRepository:
    """Repository for managing ledger entries in SQLite."""

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the repository.

        Args:
            db_path: Path to the SQLite database file. Defaults to data/yuuka.db
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self._ensure_db_directory()
        self._init_schema()

    def _ensure_db_directory(self):
        """Ensure the database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ledger_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    amount REAL NOT NULL,
                    source TEXT,
                    destination TEXT,
                    description TEXT,
                    raw_text TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    user_id TEXT NOT NULL,
                    guild_id TEXT,
                    channel_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    confirmed INTEGER NOT NULL DEFAULT 1
                )
            """)

            # Create indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_user_id
                ON ledger_entries(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_created_at
                ON ledger_entries(created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_action
                ON ledger_entries(action)
            """)

    def insert(
        self,
        parsed: ParsedTransaction,
        user_id: str,
        channel_id: str,
        message_id: str,
        guild_id: Optional[str] = None,
        confirmed: bool = True,
    ) -> LedgerEntry:
        """
        Insert a new ledger entry from a parsed transaction.

        Args:
            parsed: The parsed transaction data
            user_id: Discord user ID
            channel_id: Discord channel ID
            message_id: Discord message ID
            guild_id: Discord guild ID (None for DMs)
            confirmed: Whether the entry was confirmed by user

        Returns:
            The created LedgerEntry with its ID
        """
        created_at = datetime.now()

        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ledger_entries (
                    action, amount, source, destination, description,
                    raw_text, confidence, user_id, guild_id, channel_id,
                    message_id, created_at, confirmed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parsed.action.value,
                    parsed.amount,
                    parsed.source,
                    parsed.destination,
                    parsed.description,
                    parsed.raw_text,
                    parsed.confidence,
                    user_id,
                    guild_id,
                    channel_id,
                    message_id,
                    created_at.isoformat(),
                    1 if confirmed else 0,
                ),
            )

            return LedgerEntry(
                id=cursor.lastrowid,
                action=parsed.action,
                amount=parsed.amount or 0.0,
                source=parsed.source,
                destination=parsed.destination,
                description=parsed.description,
                raw_text=parsed.raw_text,
                confidence=parsed.confidence,
                user_id=user_id,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
                created_at=created_at,
                confirmed=confirmed,
            )

    def get_by_id(self, entry_id: int) -> Optional[LedgerEntry]:
        """Get a ledger entry by its ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
            )
            row = cursor.fetchone()
            if row:
                return LedgerEntry.from_row(tuple(row))
            return None

    def get_user_entries(
        self,
        user_id: str,
        limit: int = 10,
        offset: int = 0,
        action: Optional[TransactionAction] = None,
    ) -> list[LedgerEntry]:
        """
        Get ledger entries for a specific user.

        Args:
            user_id: Discord user ID
            limit: Maximum number of entries to return
            offset: Number of entries to skip
            action: Filter by action type (optional)

        Returns:
            List of LedgerEntry objects
        """
        with self._get_connection() as conn:
            if action:
                cursor = conn.execute(
                    """
                    SELECT * FROM ledger_entries
                    WHERE user_id = ? AND action = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user_id, action.value, limit, offset),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM ledger_entries
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (user_id, limit, offset),
                )

            return [LedgerEntry.from_row(tuple(row)) for row in cursor.fetchall()]

    def get_user_summary(self, user_id: str) -> dict[str, Any]:
        """
        Get a summary of a user's ledger.

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary with summary statistics
        """
        with self._get_connection() as conn:
            # Total counts by action
            cursor = conn.execute(
                """
                SELECT action, COUNT(*) as count, SUM(amount) as total
                FROM ledger_entries
                WHERE user_id = ?
                GROUP BY action
                """,
                (user_id,),
            )

            summary = {
                "incoming": {"count": 0, "total": 0.0},
                "outgoing": {"count": 0, "total": 0.0},
                "transfer": {"count": 0, "total": 0.0},
            }

            for row in cursor.fetchall():
                action = row["action"]
                summary[action] = {
                    "count": row["count"],
                    "total": row["total"] or 0.0,
                }

            # Calculate net
            net = summary["incoming"]["total"] - summary["outgoing"]["total"]
            total_entries = sum(
                s["count"] for s in summary.values() if isinstance(s, dict)
            )

            return {
                **summary,
                "net": net,
                "total_entries": total_entries,
            }

    def get_user_balance_by_account(self, user_id: str) -> dict[str, float]:
        """
        Calculate balance for each account/source for a user.

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary mapping account names to their balances
        """
        with self._get_connection() as conn:
            # Get all incoming to destinations
            cursor = conn.execute(
                """
                SELECT destination, SUM(amount) as total
                FROM ledger_entries
                WHERE user_id = ? AND action = 'incoming' AND destination IS NOT NULL
                GROUP BY destination
                """,
                (user_id,),
            )
            balances: dict[str, float] = {}
            for row in cursor.fetchall():
                account = row["destination"]
                balances[account] = balances.get(account, 0.0) + (row["total"] or 0.0)

            # Subtract outgoing from sources
            cursor = conn.execute(
                """
                SELECT source, SUM(amount) as total
                FROM ledger_entries
                WHERE user_id = ? AND action = 'outgoing' AND source IS NOT NULL
                GROUP BY source
                """,
                (user_id,),
            )
            for row in cursor.fetchall():
                account = row["source"]
                balances[account] = balances.get(account, 0.0) - (row["total"] or 0.0)

            # Handle transfers (subtract from source, add to destination)
            cursor = conn.execute(
                """
                SELECT source, destination, SUM(amount) as total
                FROM ledger_entries
                WHERE user_id = ? AND action = 'transfer'
                GROUP BY source, destination
                """,
                (user_id,),
            )
            for row in cursor.fetchall():
                source = row["source"]
                destination = row["destination"]
                amount = row["total"] or 0.0
                if source:
                    balances[source] = balances.get(source, 0.0) - amount
                if destination:
                    balances[destination] = balances.get(destination, 0.0) + amount

            return balances

    def delete_entry(self, entry_id: int, user_id: str) -> bool:
        """
        Delete a ledger entry (only if owned by user).

        Args:
            entry_id: The entry ID to delete
            user_id: Discord user ID (for ownership verification)

        Returns:
            True if deleted, False if not found or not owned
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM ledger_entries WHERE id = ? AND user_id = ?",
                (entry_id, user_id),
            )
            return cursor.rowcount > 0

    def count_user_entries(
        self, user_id: str, action: Optional[TransactionAction] = None
    ) -> int:
        """Count total entries for a user."""
        with self._get_connection() as conn:
            if action:
                cursor = conn.execute(
                    """
                    SELECT COUNT(*) FROM ledger_entries
                    WHERE user_id = ? AND action = ?
                    """,
                    (user_id, action.value),
                )
            else:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM ledger_entries WHERE user_id = ?",
                    (user_id,),
                )
            return cursor.fetchone()[0]

    def get_entries_for_date_range(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> list[LedgerEntry]:
        """
        Get ledger entries within a date range for a user.

        Args:
            user_id: Discord user ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of LedgerEntry objects
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM ledger_entries
                WHERE user_id = ?
                AND date(created_at) >= date(?)
                AND date(created_at) <= date(?)
                ORDER BY created_at ASC
                """,
                (user_id, start_date.isoformat(), end_date.isoformat()),
            )
            return [LedgerEntry.from_row(tuple(row)) for row in cursor.fetchall()]

    def get_entries_for_today(self, user_id: str) -> list[LedgerEntry]:
        """Get all entries for today."""
        today = date.today()
        return self.get_entries_for_date_range(user_id, today, today)

    def get_daily_totals(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[date, dict[str, float]]:
        """
        Get daily totals for incoming/outgoing within a date range.

        Args:
            user_id: Discord user ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dictionary mapping dates to {incoming, outgoing, net} totals
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT date(created_at) as day, action, SUM(amount) as total
                FROM ledger_entries
                WHERE user_id = ?
                AND date(created_at) >= date(?)
                AND date(created_at) <= date(?)
                GROUP BY date(created_at), action
                ORDER BY day ASC
                """,
                (user_id, start_date.isoformat(), end_date.isoformat()),
            )

            daily_totals: dict[date, dict[str, float]] = {}

            # Initialize all dates in range
            current = start_date
            while current <= end_date:
                daily_totals[current] = {"incoming": 0.0, "outgoing": 0.0, "net": 0.0}
                current += timedelta(days=1)

            # Fill in actual data
            for row in cursor.fetchall():
                day = date.fromisoformat(row[0])
                action = row[1]
                total = row[2] or 0.0

                if action == "incoming":
                    daily_totals[day]["incoming"] = total
                elif action == "outgoing":
                    daily_totals[day]["outgoing"] = total
                # Transfers don't affect net balance

            # Calculate net for each day
            for day in daily_totals:
                daily_totals[day]["net"] = (
                    daily_totals[day]["incoming"] - daily_totals[day]["outgoing"]
                )

            return daily_totals

    def get_total_balance(self, user_id: str) -> float:
        """Get the total balance (incoming - outgoing) for a user."""
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
            return result[0] if result else 0.0

    def get_spending_since_date(self, user_id: str, since_date: date) -> float:
        """Get total outgoing spending since a given date."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM ledger_entries
                WHERE user_id = ? AND action = 'outgoing'
                  AND date(created_at) >= date(?)
                """,
                (user_id, since_date.isoformat()),
            )
            result = cursor.fetchone()
            return result[0] if result else 0.0


# Singleton instance
_default_repository: Optional[LedgerRepository] = None


def get_repository() -> LedgerRepository:
    """Get or create the default repository instance."""
    global _default_repository
    if _default_repository is None:
        _default_repository = LedgerRepository()
    return _default_repository

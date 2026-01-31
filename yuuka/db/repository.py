"""
Database repository for ledger operations.

Handles SQLite connection, schema initialization, and CRUD operations
for ledger entries.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from yuuka.models import ParsedTransaction, TransactionAction

from .models import LedgerEntry

logger = logging.getLogger(__name__)

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
        try:
            self._ensure_db_directory()
            self._init_schema()
            logger.info(f"LedgerRepository initialized with db_path: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize LedgerRepository: {e}", exc_info=True)
            raise

    def _ensure_db_directory(self):
        """Ensure the database directory exists."""
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Database directory ensured: {self.db_path.parent}")
        except Exception as e:
            logger.error(f"Failed to create database directory: {e}", exc_info=True)
            raise

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections with proper error handling."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            # Enable foreign keys
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except sqlite3.OperationalError as e:
            logger.error(f"Database locked or operational error: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise
        except Exception as e:
            logger.error(f"Database error: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    def _init_schema(self):
        """Initialize the database schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ledger_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL CHECK(action IN ('incoming', 'outgoing', 'transfer')),
                    amount REAL NOT NULL CHECK(amount > 0),
                    source TEXT,
                    destination TEXT,
                    description TEXT,
                    raw_text TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
                    user_id TEXT NOT NULL CHECK(length(user_id) > 0),
                    guild_id TEXT,
                    channel_id TEXT NOT NULL CHECK(length(channel_id) > 0),
                    message_id TEXT NOT NULL CHECK(length(message_id) > 0),
                    created_at TEXT NOT NULL,
                    confirmed INTEGER NOT NULL DEFAULT 1 CHECK(confirmed IN (0, 1))
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

            # Composite index for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_user_created
                ON ledger_entries(user_id, created_at DESC)
            """)

            logger.debug("Ledger schema initialized successfully")

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

        Raises:
            ValueError: If validation fails
        """
        # Validate inputs
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        if not channel_id or not isinstance(channel_id, str):
            raise ValueError(f"Invalid channel_id: {channel_id}")

        if not message_id or not isinstance(message_id, str):
            raise ValueError(f"Invalid message_id: {message_id}")

        if not parsed.is_valid():
            raise ValueError(f"Invalid parsed transaction: {parsed}")

        if parsed.amount is None or parsed.amount <= 0:
            raise ValueError(f"Invalid amount: {parsed.amount}")

        if parsed.confidence < 0 or parsed.confidence > 1:
            raise ValueError(f"Invalid confidence: {parsed.confidence}")

        created_at = datetime.now(timezone.utc)

        try:
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

                entry_id = cursor.lastrowid
                logger.info(f"Inserted ledger entry {entry_id} for user {user_id}")

                return LedgerEntry(
                    id=entry_id,
                    action=parsed.action,
                    amount=parsed.amount,
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
        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(f"Error inserting ledger entry: {e}", exc_info=True)
            raise

    def get_by_id(self, entry_id: int) -> Optional[LedgerEntry]:
        """
        Get a ledger entry by its ID.

        Args:
            entry_id: The entry ID to retrieve

        Returns:
            LedgerEntry if found, None otherwise

        Raises:
            ValueError: If entry_id is invalid
        """
        if not isinstance(entry_id, int) or entry_id <= 0:
            raise ValueError(f"Invalid entry_id: {entry_id}")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)
                )
                row = cursor.fetchone()
                if row:
                    return LedgerEntry.from_row(tuple(row))
                return None
        except Exception as e:
            logger.error(f"Error getting entry {entry_id}: {e}", exc_info=True)
            raise

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
            limit: Maximum number of entries to return (max 10000)
            offset: Number of entries to skip
            action: Filter by action type (optional)

        Returns:
            List of LedgerEntry objects

        Raises:
            ValueError: If parameters are invalid
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        if limit <= 0 or limit > 10000:
            raise ValueError(f"limit must be between 1 and 10000, got {limit}")

        if offset < 0:
            raise ValueError(f"offset must be >= 0, got {offset}")

        try:
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

                entries = [
                    LedgerEntry.from_row(tuple(row)) for row in cursor.fetchall()
                ]
                logger.debug(f"Retrieved {len(entries)} entries for user {user_id}")
                return entries
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting entries for user {user_id}: {e}", exc_info=True
            )
            raise

    def get_user_summary(self, user_id: str) -> dict[str, Any]:
        """
        Get a summary of a user's ledger.

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary with summary statistics

        Raises:
            ValueError: If user_id is invalid
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        try:
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

                result = {
                    **summary,
                    "net": net,
                    "total_entries": total_entries,
                }
                logger.debug(
                    f"Generated summary for user {user_id}: {total_entries} entries"
                )
                return result
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting summary for user {user_id}: {e}", exc_info=True
            )
            raise

    def get_user_balance_by_account(self, user_id: str) -> dict[str, float]:
        """
        Calculate balance for each account/source for a user.

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary mapping account names to their balances

        Raises:
            ValueError: If user_id is invalid
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        try:
            with self._get_connection() as conn:
                # Get all incoming to destinations
                cursor = conn.execute(
                    """
                    SELECT destination, SUM(amount) as total
                    FROM ledger_entries
                    WHERE user_id = ? AND action = 'incoming'
                      AND destination IS NOT NULL
                    GROUP BY destination
                    """,
                    (user_id,),
                )
                balances: dict[str, float] = {}
                for row in cursor.fetchall():
                    account = row["destination"]
                    balances[account] = balances.get(account, 0.0) + (
                        row["total"] or 0.0
                    )

                # Subtract outgoing from sources
                cursor = conn.execute(
                    """
                    SELECT source, SUM(amount) as total
                    FROM ledger_entries
                    WHERE user_id = ? AND action = 'outgoing'
                      AND source IS NOT NULL
                    GROUP BY source
                    """,
                    (user_id,),
                )
                for row in cursor.fetchall():
                    account = row["source"]
                    balances[account] = balances.get(account, 0.0) - (
                        row["total"] or 0.0
                    )

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

    def delete_entry(self, entry_id: int, user_id: str) -> bool:
        """
        Delete a ledger entry (only if owned by user).

        Args:
            entry_id: The entry ID to delete
            user_id: Discord user ID (for ownership verification)

        Returns:
            True if deleted, False if not found or not owned

        Raises:
            ValueError: If parameters are invalid
        """
        if not isinstance(entry_id, int) or entry_id <= 0:
            raise ValueError(f"Invalid entry_id: {entry_id}")

        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM ledger_entries WHERE id = ? AND user_id = ?",
                    (entry_id, user_id),
                )
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Deleted entry {entry_id} for user {user_id}")
                else:
                    logger.debug(
                        f"Entry {entry_id} not found or not owned by user {user_id}"
                    )
                return deleted
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting entry {entry_id}: {e}", exc_info=True)
            raise

    def count_user_entries(
        self, user_id: str, action: Optional[TransactionAction] = None
    ) -> int:
        """
        Count total entries for a user.

        Args:
            user_id: Discord user ID
            action: Optional action filter

        Returns:
            Count of entries

        Raises:
            ValueError: If user_id is invalid
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        try:
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
                count = cursor.fetchone()[0]
                logger.debug(f"Counted {count} entries for user {user_id}")
                return count
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error counting entries for user {user_id}: {e}", exc_info=True
            )
            raise

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

        Raises:
            ValueError: If parameters are invalid
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        if not isinstance(start_date, date):
            raise ValueError(f"Invalid start_date: {start_date}")

        if not isinstance(end_date, date):
            raise ValueError(f"Invalid end_date: {end_date}")

        if start_date > end_date:
            raise ValueError(
                f"start_date {start_date} cannot be after end_date {end_date}"
            )

        try:
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
                entries = [
                    LedgerEntry.from_row(tuple(row)) for row in cursor.fetchall()
                ]
                logger.debug(
                    f"Retrieved {len(entries)} entries for user {user_id} "
                    f"from {start_date} to {end_date}"
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
        """
        Get the total balance (incoming - outgoing) for a user.

        Args:
            user_id: Discord user ID

        Returns:
            Total balance

        Raises:
            ValueError: If user_id is invalid
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        try:
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

    def get_spending_since_date(self, user_id: str, since_date: date) -> float:
        """
        Get total outgoing spending since a given date.

        Args:
            user_id: Discord user ID
            since_date: Start date

        Returns:
            Total spending amount

        Raises:
            ValueError: If parameters are invalid
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        if not isinstance(since_date, date):
            raise ValueError(f"Invalid since_date: {since_date}")

        try:
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
                spending = result[0] if result else 0.0
                logger.debug(
                    f"Spending for user {user_id} since {since_date}: {spending}"
                )
                return spending
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting spending for user {user_id}: {e}", exc_info=True
            )
            raise


# Singleton instance
_default_repository: Optional[LedgerRepository] = None


def get_repository() -> LedgerRepository:
    """Get or create the default repository instance."""
    global _default_repository
    if _default_repository is None:
        _default_repository = LedgerRepository()
    return _default_repository

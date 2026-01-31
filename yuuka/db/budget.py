"""
Budget configuration models for recap forecasting.

Defines the schema for storing user budget settings used in daily recap
and financial forecasting.
"""

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BudgetConfig:
    """User's budget configuration for forecasting."""

    id: Optional[int]
    user_id: str
    daily_limit: float  # Daily spending limit
    payday: int  # Day of month when payslip arrives (1-31)
    monthly_income: Optional[float]  # Expected monthly income
    warning_threshold: float  # Percentage at which to warn (e.g., 0.2 = 20% remaining)
    created_at: datetime
    updated_at: datetime

    def days_until_payday(self, from_date: Optional[date] = None) -> int:
        """Calculate days until next payday from a given date."""
        if from_date is None:
            from_date = date.today()

        current_day = from_date.day
        current_month = from_date.month
        current_year = from_date.year

        if current_day < self.payday:
            # Payday is later this month
            try:
                next_payday = date(current_year, current_month, self.payday)
            except ValueError:
                # Handle months with fewer days than payday
                # Move to first day of next month
                if current_month == 12:
                    next_payday = date(current_year + 1, 1, 1)
                else:
                    next_payday = date(current_year, current_month + 1, 1)
        else:
            # Payday is next month
            if current_month == 12:
                next_month = 1
                next_year = current_year + 1
            else:
                next_month = current_month + 1
                next_year = current_year

            try:
                next_payday = date(next_year, next_month, self.payday)
            except ValueError:
                # Handle months with fewer days than payday
                if next_month == 12:
                    next_payday = date(next_year + 1, 1, 1)
                else:
                    next_payday = date(next_year, next_month + 1, 1)

        return (next_payday - from_date).days

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "daily_limit": self.daily_limit,
            "payday": self.payday,
            "monthly_income": self.monthly_income,
            "warning_threshold": self.warning_threshold,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_row(cls, row: tuple) -> "BudgetConfig":
        """Create a BudgetConfig from a database row."""
        return cls(
            id=row[0],
            user_id=row[1],
            daily_limit=row[2],
            payday=row[3],
            monthly_income=row[4],
            warning_threshold=row[5],
            created_at=datetime.fromisoformat(row[6]),
            updated_at=datetime.fromisoformat(row[7]),
        )


class BudgetRepository:
    """Repository for managing budget configurations in SQLite."""

    def __init__(self, db_path: Path):
        """
        Initialize the repository.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        try:
            self._init_schema()
            logger.info(f"BudgetRepository initialized with db_path: {db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize BudgetRepository: {e}", exc_info=True)
            raise

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections with proper error handling."""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
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
        """Initialize the budget_config table schema."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS budget_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL UNIQUE,
                    daily_limit REAL NOT NULL DEFAULT 50000 CHECK(daily_limit >= 0),
                    payday INTEGER NOT NULL DEFAULT 25 CHECK(payday >= 1 AND payday <= 31),
                    monthly_income REAL CHECK(monthly_income IS NULL OR monthly_income >= 0),
                    warning_threshold REAL NOT NULL DEFAULT 0.2 CHECK(warning_threshold >= 0 AND warning_threshold <= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Create index for faster user lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_budget_user_id
                ON budget_config(user_id)
            """)
            logger.debug("Budget schema initialized successfully")

    def get_by_user(self, user_id: str) -> Optional[BudgetConfig]:
        """
        Get budget config for a user.

        Args:
            user_id: Discord user ID

        Returns:
            BudgetConfig if found, None otherwise

        Raises:
            ValueError: If user_id is invalid
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM budget_config WHERE user_id = ?", (user_id,)
                )
                row = cursor.fetchone()
                if row:
                    logger.debug(f"Found budget config for user {user_id}")
                    return BudgetConfig.from_row(row)
                logger.debug(f"No budget config found for user {user_id}")
                return None
        except Exception as e:
            logger.error(f"Error getting budget for user {user_id}: {e}", exc_info=True)
            raise

    def upsert(
        self,
        user_id: str,
        daily_limit: Optional[float] = None,
        payday: Optional[int] = None,
        monthly_income: Optional[float] = None,
        warning_threshold: Optional[float] = None,
    ) -> BudgetConfig:
        """
        Create or update budget config for a user.

        Args:
            user_id: Discord user ID
            daily_limit: Daily spending limit (must be >= 0)
            payday: Day of month for payslip (1-31)
            monthly_income: Expected monthly income (must be >= 0)
            warning_threshold: Warning threshold percentage (0-1)

        Returns:
            The created or updated BudgetConfig

        Raises:
            ValueError: If any parameter validation fails
        """
        # Validate inputs
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        if daily_limit is not None and daily_limit < 0:
            raise ValueError(f"daily_limit must be >= 0, got {daily_limit}")

        if payday is not None and (payday < 1 or payday > 31):
            raise ValueError(f"payday must be between 1 and 31, got {payday}")

        if monthly_income is not None and monthly_income < 0:
            raise ValueError(f"monthly_income must be >= 0, got {monthly_income}")

        if warning_threshold is not None and (
            warning_threshold < 0 or warning_threshold > 1
        ):
            raise ValueError(
                f"warning_threshold must be between 0 and 1, got {warning_threshold}"
            )

        now = datetime.now()

        try:
            with self._get_connection() as conn:
                # Use INSERT OR REPLACE for true atomic upsert
                existing = self.get_by_user(user_id)

                if existing:
                    # Update existing config
                    new_daily_limit = (
                        daily_limit if daily_limit is not None else existing.daily_limit
                    )
                    new_payday = payday if payday is not None else existing.payday
                    new_monthly_income = (
                        monthly_income
                        if monthly_income is not None
                        else existing.monthly_income
                    )
                    new_warning_threshold = (
                        warning_threshold
                        if warning_threshold is not None
                        else existing.warning_threshold
                    )

                    conn.execute(
                        """
                        UPDATE budget_config
                        SET daily_limit = ?, payday = ?, monthly_income = ?,
                            warning_threshold = ?, updated_at = ?
                        WHERE user_id = ?
                        """,
                        (
                            new_daily_limit,
                            new_payday,
                            new_monthly_income,
                            new_warning_threshold,
                            now.isoformat(),
                            user_id,
                        ),
                    )

                    logger.info(f"Updated budget config for user {user_id}")

                    return BudgetConfig(
                        id=existing.id,
                        user_id=user_id,
                        daily_limit=new_daily_limit,
                        payday=new_payday,
                        monthly_income=new_monthly_income,
                        warning_threshold=new_warning_threshold,
                        created_at=existing.created_at,
                        updated_at=now,
                    )
                else:
                    # Create new config with defaults
                    new_daily_limit = (
                        daily_limit if daily_limit is not None else 50000.0
                    )
                    new_payday = payday if payday is not None else 25
                    new_warning_threshold = (
                        warning_threshold if warning_threshold is not None else 0.2
                    )

                    cursor = conn.execute(
                        """
                        INSERT INTO budget_config (
                            user_id, daily_limit, payday, monthly_income,
                            warning_threshold, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id,
                            new_daily_limit,
                            new_payday,
                            monthly_income,
                            new_warning_threshold,
                            now.isoformat(),
                            now.isoformat(),
                        ),
                    )

                    logger.info(f"Created new budget config for user {user_id}")

                    return BudgetConfig(
                        id=cursor.lastrowid,
                        user_id=user_id,
                        daily_limit=new_daily_limit,
                        payday=new_payday,
                        monthly_income=monthly_income,
                        warning_threshold=new_warning_threshold,
                        created_at=now,
                        updated_at=now,
                    )
        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(
                f"Error upserting budget for user {user_id}: {e}", exc_info=True
            )
            raise

    def delete(self, user_id: str) -> bool:
        """
        Delete budget config for a user.

        Args:
            user_id: Discord user ID

        Returns:
            True if deleted, False if not found

        Raises:
            ValueError: If user_id is invalid
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM budget_config WHERE user_id = ?", (user_id,)
                )
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Deleted budget config for user {user_id}")
                else:
                    logger.debug(f"No budget config to delete for user {user_id}")
                return deleted
        except Exception as e:
            logger.error(
                f"Error deleting budget for user {user_id}: {e}", exc_info=True
            )
            raise

    def get_all_users_with_config(self) -> list[str]:
        """
        Get all user IDs that have budget config (for scheduled recaps).

        Returns:
            List of user IDs
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute("SELECT user_id FROM budget_config")
                users = [row[0] for row in cursor.fetchall()]
                logger.debug(f"Found {len(users)} users with budget config")
                return users
        except Exception as e:
            logger.error(f"Error getting all users with config: {e}", exc_info=True)
            raise

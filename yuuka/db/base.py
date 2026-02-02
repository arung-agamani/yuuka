"""
Base repository module with connection management and schema initialization.

Provides the foundation for all database operations in the Yuuka ledger system.
"""

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "yuuka.db"


class BaseRepository:
    """
    Base repository class with SQLite connection management.

    Provides connection pooling, schema initialization, and common
    database utilities for all repository classes.
    """

    def __init__(self, db_path: Optional[Path] = None, init_schema: bool = True):
        """
        Initialize the base repository.

        Args:
            db_path: Path to the SQLite database file. Defaults to data/yuuka.db
            init_schema: Whether to initialize the schema on startup
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self._ensure_db_directory()
        if init_schema:
            self._init_schema()

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
        """Initialize the database schema for double-entry bookkeeping."""
        with self._get_connection() as conn:
            # Account groups table - canonical accounts
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    account_type TEXT NOT NULL CHECK(
                        account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')
                    ),
                    user_id TEXT NOT NULL CHECK(length(user_id) > 0),
                    description TEXT,
                    is_system INTEGER NOT NULL DEFAULT 0 CHECK(is_system IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name, user_id)
                )
            """)

            # Account aliases table - maps input names to account groups
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alias TEXT NOT NULL,
                    group_id INTEGER NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
                    user_id TEXT NOT NULL CHECK(length(user_id) > 0),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(alias, user_id)
                )
            """)

            # Legacy accounts table - for backward compatibility
            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    account_type TEXT NOT NULL CHECK(
                        account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')
                    ),
                    user_id TEXT NOT NULL CHECK(length(user_id) > 0),
                    description TEXT,
                    is_system INTEGER NOT NULL DEFAULT 0 CHECK(is_system IN (0, 1)),
                    group_id INTEGER REFERENCES account_groups(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name, user_id)
                )
            """)

            # Transactions table - groups journal entries
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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

            # Journal entries table - individual debit/credit entries
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id INTEGER NOT NULL
                        REFERENCES transactions(id) ON DELETE CASCADE,
                    account_id INTEGER NOT NULL,
                    account_name TEXT NOT NULL,
                    entry_type TEXT NOT NULL CHECK(entry_type IN ('debit', 'credit')),
                    amount REAL NOT NULL CHECK(amount > 0)
                )
            """)

            # Legacy ledger_entries table for backward compatibility
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ledger_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL CHECK(
                        action IN ('incoming', 'outgoing', 'transfer')
                    ),
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
                    confirmed INTEGER NOT NULL DEFAULT 1 CHECK(confirmed IN (0, 1)),
                    transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL
                )
            """)

            # Create indexes for performance
            self._create_indexes(conn)

            logger.debug("Double-entry ledger schema initialized successfully")

    def _create_indexes(self, conn):
        """Create database indexes for query performance."""
        indexes = [
            ("idx_account_groups_user_id", "account_groups", "user_id"),
            ("idx_account_aliases_user_id", "account_aliases", "user_id"),
            ("idx_account_aliases_group_id", "account_aliases", "group_id"),
            ("idx_account_aliases_lookup", "account_aliases", "alias, user_id"),
            ("idx_accounts_user_id", "accounts", "user_id"),
            ("idx_transactions_user_id", "transactions", "user_id"),
            ("idx_transactions_created_at", "transactions", "created_at"),
            ("idx_journal_entries_transaction_id", "journal_entries", "transaction_id"),
            ("idx_journal_entries_account_id", "journal_entries", "account_id"),
            ("idx_ledger_user_id", "ledger_entries", "user_id"),
            ("idx_ledger_created_at", "ledger_entries", "created_at"),
            ("idx_ledger_action", "ledger_entries", "action"),
            ("idx_ledger_user_created", "ledger_entries", "user_id, created_at DESC"),
        ]

        for index_name, table, columns in indexes:
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {table}({columns})
            """)

"""
Database repository for double-entry ledger operations.

Handles SQLite connection, schema initialization, and CRUD operations
for the double-entry bookkeeping system with account aliasing support.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from yuuka.models import ParsedTransaction, TransactionAction
from yuuka.models.account import AccountType, EntryType

from .models import (
    Account,
    AccountAlias,
    AccountGroup,
    JournalEntry,
    LedgerEntry,
    Transaction,
)

logger = logging.getLogger(__name__)

# Default database path
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "yuuka.db"

# Default system accounts that will be auto-created for each user
DEFAULT_SYSTEM_ACCOUNTS = [
    ("income", AccountType.REVENUE, "Default income account"),
    ("expense", AccountType.EXPENSE, "Default expense account"),
    ("cash", AccountType.ASSET, "Default cash/wallet account"),
]


class LedgerRepository:
    """
    Repository for managing double-entry ledger in SQLite.

    This implements proper double-entry bookkeeping where:
    - Every transaction creates balanced debit and credit entries
    - Accounts have types (Asset, Liability, Equity, Revenue, Expense)
    - The accounting equation (Assets = Liabilities + Equity) is maintained
    """

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
        """Initialize the database schema for double-entry bookkeeping."""
        with self._get_connection() as conn:
            # Account groups table - canonical accounts
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    account_type TEXT NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
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
                    account_type TEXT NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
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
                    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
                    account_id INTEGER NOT NULL REFERENCES accounts(id),
                    account_name TEXT NOT NULL,
                    entry_type TEXT NOT NULL CHECK(entry_type IN ('debit', 'credit')),
                    amount REAL NOT NULL CHECK(amount > 0)
                )
            """)

            # Legacy ledger_entries table for backward compatibility
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
                    confirmed INTEGER NOT NULL DEFAULT 1 CHECK(confirmed IN (0, 1)),
                    transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL
                )
            """)

            # Create indexes
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_account_groups_user_id
                ON account_groups(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_account_aliases_user_id
                ON account_aliases(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_account_aliases_group_id
                ON account_aliases(group_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_account_aliases_lookup
                ON account_aliases(alias, user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_accounts_user_id
                ON accounts(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_transactions_user_id
                ON transactions(user_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_transactions_created_at
                ON transactions(created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_journal_entries_transaction_id
                ON journal_entries(transaction_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_journal_entries_account_id
                ON journal_entries(account_id)
            """)
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
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ledger_user_created
                ON ledger_entries(user_id, created_at DESC)
            """)

            logger.debug("Double-entry ledger schema initialized successfully")

    # ==================== Account Group & Alias Operations ====================

    def create_account_group(
        self,
        name: str,
        user_id: str,
        account_type: AccountType,
        description: Optional[str] = None,
        is_system: bool = False,
    ) -> AccountGroup:
        """
        Create a new account group (canonical account).

        Args:
            name: Display name for the account group
            user_id: Discord user ID
            account_type: Type of account
            description: Optional description
            is_system: Whether this is a system account

        Returns:
            The created AccountGroup

        Raises:
            ValueError: If inputs are invalid or name already exists
        """
        if not name or not name.strip():
            raise ValueError("Account group name cannot be empty")
        if not user_id:
            raise ValueError("User ID cannot be empty")

        name = name.strip()
        created_at = datetime.now(timezone.utc)

        try:
            with self._get_connection() as conn:
                # Check if group already exists
                cursor = conn.execute(
                    """
                    SELECT id FROM account_groups
                    WHERE LOWER(name) = LOWER(?) AND user_id = ?
                    """,
                    (name, user_id),
                )
                if cursor.fetchone():
                    raise ValueError(f"Account group '{name}' already exists")

                # Create the group
                cursor = conn.execute(
                    """
                    INSERT INTO account_groups
                    (name, account_type, user_id, description, is_system, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        account_type.value,
                        user_id,
                        description,
                        1 if is_system else 0,
                        created_at.isoformat(),
                    ),
                )
                group_id = cursor.lastrowid

                # Auto-create an alias with the canonical name (lowercase)
                conn.execute(
                    """
                    INSERT INTO account_aliases (alias, group_id, user_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (name.lower(), group_id, user_id, created_at.isoformat()),
                )

                logger.info(
                    f"Created account group '{name}' (type: {account_type.value}) "
                    f"for user {user_id}"
                )

                return AccountGroup(
                    id=group_id,
                    name=name,
                    account_type=account_type,
                    user_id=user_id,
                    description=description,
                    is_system=is_system,
                    created_at=created_at,
                )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error creating account group: {e}", exc_info=True)
            raise

    def get_account_group_by_id(
        self, group_id: int, user_id: str
    ) -> Optional[AccountGroup]:
        """Get an account group by ID."""
        if group_id <= 0:
            raise ValueError(f"Invalid group_id: {group_id}")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, name, account_type, user_id, description,
                           is_system, created_at
                    FROM account_groups
                    WHERE id = ? AND user_id = ?
                    """,
                    (group_id, user_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                return AccountGroup(
                    id=row[0],
                    name=row[1],
                    account_type=AccountType(row[2]),
                    user_id=row[3],
                    description=row[4],
                    is_system=bool(row[5]),
                    created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error getting account group: {e}", exc_info=True)
            raise

    def get_account_group_by_name(
        self, name: str, user_id: str
    ) -> Optional[AccountGroup]:
        """Get an account group by its canonical name."""
        if not name:
            return None

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, name, account_type, user_id, description,
                           is_system, created_at
                    FROM account_groups
                    WHERE LOWER(name) = LOWER(?) AND user_id = ?
                    """,
                    (name.strip(), user_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                return AccountGroup(
                    id=row[0],
                    name=row[1],
                    account_type=AccountType(row[2]),
                    user_id=row[3],
                    description=row[4],
                    is_system=bool(row[5]),
                    created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                )
        except Exception as e:
            logger.error(f"Error getting account group by name: {e}", exc_info=True)
            raise

    def get_user_account_groups(self, user_id: str) -> list[AccountGroup]:
        """Get all account groups for a user."""
        if not user_id:
            raise ValueError("User ID cannot be empty")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, name, account_type, user_id, description,
                           is_system, created_at
                    FROM account_groups
                    WHERE user_id = ?
                    ORDER BY account_type, name
                    """,
                    (user_id,),
                )

                return [
                    AccountGroup(
                        id=row[0],
                        name=row[1],
                        account_type=AccountType(row[2]),
                        user_id=row[3],
                        description=row[4],
                        is_system=bool(row[5]),
                        created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                    )
                    for row in cursor.fetchall()
                ]
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error getting account groups: {e}", exc_info=True)
            raise

    def add_account_alias(
        self,
        alias: str,
        group_id: int,
        user_id: str,
    ) -> AccountAlias:
        """
        Add an alias to an account group.

        Args:
            alias: The alias string (will be normalized to lowercase)
            group_id: The account group to add the alias to
            user_id: Discord user ID

        Returns:
            The created AccountAlias

        Raises:
            ValueError: If alias already exists or group doesn't exist
        """
        if not alias or not alias.strip():
            raise ValueError("Alias cannot be empty")
        if not user_id:
            raise ValueError("User ID cannot be empty")

        alias = alias.strip().lower()
        created_at = datetime.now(timezone.utc)

        try:
            with self._get_connection() as conn:
                # Verify the group exists and belongs to user
                cursor = conn.execute(
                    """
                    SELECT id FROM account_groups
                    WHERE id = ? AND user_id = ?
                    """,
                    (group_id, user_id),
                )
                if not cursor.fetchone():
                    raise ValueError(f"Account group {group_id} not found")

                # Check if alias already exists
                cursor = conn.execute(
                    """
                    SELECT id, group_id FROM account_aliases
                    WHERE alias = ? AND user_id = ?
                    """,
                    (alias, user_id),
                )
                existing = cursor.fetchone()
                if existing:
                    if existing[1] == group_id:
                        # Already mapped to this group, return existing
                        return AccountAlias(
                            id=existing[0],
                            alias=alias,
                            group_id=group_id,
                            user_id=user_id,
                        )
                    else:
                        raise ValueError(
                            f"Alias '{alias}' is already mapped to another account"
                        )

                # Create the alias
                cursor = conn.execute(
                    """
                    INSERT INTO account_aliases (alias, group_id, user_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (alias, group_id, user_id, created_at.isoformat()),
                )

                logger.info(
                    f"Added alias '{alias}' to account group {group_id} "
                    f"for user {user_id}"
                )

                return AccountAlias(
                    id=cursor.lastrowid,
                    alias=alias,
                    group_id=group_id,
                    user_id=user_id,
                    created_at=created_at,
                )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error adding account alias: {e}", exc_info=True)
            raise

    def get_aliases_for_group(self, group_id: int, user_id: str) -> list[AccountAlias]:
        """Get all aliases for an account group."""
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, alias, group_id, user_id, created_at
                    FROM account_aliases
                    WHERE group_id = ? AND user_id = ?
                    ORDER BY alias
                    """,
                    (group_id, user_id),
                )

                return [
                    AccountAlias(
                        id=row[0],
                        alias=row[1],
                        group_id=row[2],
                        user_id=row[3],
                        created_at=datetime.fromisoformat(row[4]) if row[4] else None,
                    )
                    for row in cursor.fetchall()
                ]
        except Exception as e:
            logger.error(f"Error getting aliases for group: {e}", exc_info=True)
            raise

    def resolve_account_alias(self, alias: str, user_id: str) -> Optional[AccountGroup]:
        """
        Resolve an alias to its account group.

        This is the main lookup method used when processing transactions.
        If the alias is found, returns the associated AccountGroup.

        Args:
            alias: The input account name (will be normalized)
            user_id: Discord user ID

        Returns:
            AccountGroup if alias is found, None otherwise
        """
        if not alias:
            return None

        alias = alias.strip().lower()

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT g.id, g.name, g.account_type, g.user_id,
                           g.description, g.is_system, g.created_at
                    FROM account_groups g
                    JOIN account_aliases a ON g.id = a.group_id
                    WHERE a.alias = ? AND a.user_id = ?
                    """,
                    (alias, user_id),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                return AccountGroup(
                    id=row[0],
                    name=row[1],
                    account_type=AccountType(row[2]),
                    user_id=row[3],
                    description=row[4],
                    is_system=bool(row[5]),
                    created_at=datetime.fromisoformat(row[6]) if row[6] else None,
                )
        except Exception as e:
            logger.error(f"Error resolving account alias: {e}", exc_info=True)
            raise

    def remove_account_alias(self, alias: str, user_id: str) -> bool:
        """
        Remove an alias.

        Args:
            alias: The alias to remove
            user_id: Discord user ID

        Returns:
            True if removed, False if not found
        """
        if not alias:
            return False

        alias = alias.strip().lower()

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM account_aliases
                    WHERE alias = ? AND user_id = ?
                    """,
                    (alias, user_id),
                )
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Removed alias '{alias}' for user {user_id}")
                return deleted
        except Exception as e:
            logger.error(f"Error removing alias: {e}", exc_info=True)
            raise

    def is_unresolved_account(self, name: str, user_id: str) -> bool:
        """
        Check if an account name is unresolved (no alias mapping exists).

        Args:
            name: The account name to check
            user_id: Discord user ID

        Returns:
            True if the name has no alias mapping
        """
        return self.resolve_account_alias(name, user_id) is None

    def get_pending_account_names(self, user_id: str) -> list[str]:
        """
        Get account names that are used but not mapped to any group.

        This finds names in the legacy accounts table that don't have
        a corresponding alias mapping.

        Args:
            user_id: Discord user ID

        Returns:
            List of unmapped account names
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT a.name
                    FROM accounts a
                    LEFT JOIN account_aliases al
                        ON LOWER(a.name) = al.alias AND a.user_id = al.user_id
                    WHERE a.user_id = ? AND al.id IS NULL
                    ORDER BY a.name
                    """,
                    (user_id,),
                )
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting pending account names: {e}", exc_info=True)
            raise

    def ensure_system_account_groups(self, user_id: str) -> dict[str, AccountGroup]:
        """
        Ensure all default system account groups exist for a user.

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary mapping account names to AccountGroup objects
        """
        from yuuka.models.account import DEFAULT_SYSTEM_ACCOUNTS

        groups = {}
        for name, account_type, description in DEFAULT_SYSTEM_ACCOUNTS:
            # Check if group exists
            group = self.get_account_group_by_name(name, user_id)
            if not group:
                group = self.create_account_group(
                    name=name,
                    user_id=user_id,
                    account_type=account_type,
                    description=description,
                    is_system=True,
                )
            groups[name.lower()] = group
        return groups

    # ==================== Legacy Account Operations (for backward compat) ====================

    def get_or_create_account(
        self,
        name: str,
        user_id: str,
        account_type: AccountType,
        description: Optional[str] = None,
        is_system: bool = False,
        group_id: Optional[int] = None,
    ) -> Account:
        """
        Get an existing account or create a new one.

        This method now also handles account group resolution via aliases.

        Args:
            name: Account name (will be normalized to lowercase)
            user_id: Discord user ID
            account_type: Type of account (asset, liability, etc.)
            description: Optional account description
            is_system: Whether this is a system-created account
            group_id: Optional account group ID to link to

        Returns:
            The existing or newly created Account

        Raises:
            ValueError: If inputs are invalid
        """
        if not name or not name.strip():
            raise ValueError("Account name cannot be empty")
        if not user_id:
            raise ValueError("User ID cannot be empty")

        name = name.strip().lower()

        try:
            with self._get_connection() as conn:
                # Try to get existing account
                cursor = conn.execute(
                    """
                    SELECT id, name, account_type, user_id, description, is_system, group_id
                    FROM accounts
                    WHERE name = ? AND user_id = ?
                    """,
                    (name, user_id),
                )
                row = cursor.fetchone()

                if row:
                    return Account(
                        id=row[0],
                        name=row[1],
                        account_type=AccountType(row[2]),
                        user_id=row[3],
                        description=row[4],
                        is_system=bool(row[5]),
                        group_id=row[6],
                    )

                # Create new account
                cursor = conn.execute(
                    """
                    INSERT INTO accounts
                    (name, account_type, user_id, description, is_system, group_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        account_type.value,
                        user_id,
                        description,
                        1 if is_system else 0,
                        group_id,
                    ),
                )

                account_id = cursor.lastrowid
                logger.info(
                    f"Created account '{name}' (type: {account_type.value}) "
                    f"for user {user_id}"
                )

                return Account(
                    id=account_id,
                    name=name,
                    account_type=account_type,
                    user_id=user_id,
                    description=description,
                    is_system=is_system,
                    group_id=group_id,
                )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error getting/creating account: {e}", exc_info=True)
            raise

    def ensure_system_accounts(self, user_id: str) -> dict[str, Account]:
        """
        Ensure all default system accounts exist for a user.

        Args:
            user_id: Discord user ID

        Returns:
            Dictionary mapping account names to Account objects
        """
        from yuuka.models.account import DEFAULT_SYSTEM_ACCOUNTS

        # First ensure system account groups exist
        groups = self.ensure_system_account_groups(user_id)

        accounts = {}
        for name, account_type, description in DEFAULT_SYSTEM_ACCOUNTS:
            group = groups.get(name.lower())
            account = self.get_or_create_account(
                name=name.lower(),
                user_id=user_id,
                account_type=account_type,
                description=description,
                is_system=True,
                group_id=group.id if group else None,
            )
            accounts[name.lower()] = account
        return accounts

    def get_user_accounts(self, user_id: str) -> list[Account]:
        """
        Get all accounts for a user.

        Args:
            user_id: Discord user ID

        Returns:
            List of Account objects
        """
        if not user_id:
            raise ValueError("User ID cannot be empty")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, name, account_type, user_id, description,
                           is_system, group_id
                    FROM accounts
                    WHERE user_id = ?
                    ORDER BY account_type, name
                    """,
                    (user_id,),
                )

                return [
                    Account(
                        id=row[0],
                        name=row[1],
                        account_type=AccountType(row[2]),
                        user_id=row[3],
                        description=row[4],
                        is_system=bool(row[5]),
                        group_id=row[6],
                    )
                    for row in cursor.fetchall()
                ]
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting accounts for user {user_id}: {e}", exc_info=True
            )
            raise

    def infer_account_type(self, name: str) -> AccountType:
        """
        Infer account type from account name.

        This uses heuristics to determine what type of account a name represents.
        For example, "salary" is likely revenue, "food" is likely expense, etc.

        Args:
            name: Account name

        Returns:
            Inferred AccountType
        """
        name_lower = name.lower().strip()

        # Revenue indicators
        revenue_keywords = {
            "income",
            "salary",
            "wage",
            "revenue",
            "earnings",
            "bonus",
            "commission",
            "dividend",
            "interest",
        }
        if any(kw in name_lower for kw in revenue_keywords):
            return AccountType.REVENUE

        # Expense indicators
        expense_keywords = {
            "expense",
            "food",
            "lunch",
            "dinner",
            "breakfast",
            "transport",
            "commute",
            "rent",
            "utility",
            "subscription",
            "shopping",
            "entertainment",
            "coffee",
            "snack",
        }
        if any(kw in name_lower for kw in expense_keywords):
            return AccountType.EXPENSE

        # Asset indicators (money storage)
        asset_keywords = {
            "bank",
            "wallet",
            "cash",
            "account",
            "savings",
            "pocket",
            "gopay",
            "ovo",
            "dana",
            "shopeepay",
            "paypal",
            "venmo",
        }
        if any(kw in name_lower for kw in asset_keywords):
            return AccountType.ASSET

        # Liability indicators
        liability_keywords = {
            "loan",
            "debt",
            "credit card",
            "mortgage",
            "payable",
            "owe",
        }
        if any(kw in name_lower for kw in liability_keywords):
            return AccountType.LIABILITY

        # Default to asset for unknown accounts (most common case for personal finance)
        return AccountType.ASSET

    def resolve_or_flag_account(
        self,
        name: str,
        user_id: str,
        account_type: AccountType,
    ) -> tuple[Optional[AccountGroup], bool]:
        """
        Resolve an account name to a group, or flag it as needing user input.

        This method first tries to resolve the name via aliases.
        If no alias exists, it returns (None, True) to indicate the name
        needs user assignment to a group.

        Args:
            name: The account name from user input
            user_id: Discord user ID
            account_type: Default account type if auto-creating

        Returns:
            Tuple of (AccountGroup or None, needs_assignment bool)
            - If alias exists: (AccountGroup, False)
            - If no alias: (None, True)
        """
        if not name:
            return None, True

        # Try to resolve via alias
        group = self.resolve_account_alias(name, user_id)
        if group:
            return group, False

        # No alias found - needs user assignment
        return None, True

    def auto_assign_account_to_group(
        self,
        name: str,
        user_id: str,
        group_id: int,
    ) -> AccountAlias:
        """
        Automatically assign an account name to a group (creates alias).

        This is called when the user confirms which group an account belongs to.
        Future uses of this name will automatically resolve to the group.

        Args:
            name: The account name
            user_id: Discord user ID
            group_id: The target account group

        Returns:
            The created AccountAlias
        """
        return self.add_account_alias(name, group_id, user_id)

    # ==================== Transaction Operations ====================

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
        Insert a new transaction using double-entry bookkeeping.

        This method:
        1. Creates/gets the necessary accounts
        2. Creates a transaction record
        3. Creates balanced journal entries (debit and credit)
        4. Creates a legacy ledger entry for backward compatibility

        Args:
            parsed: The parsed transaction data
            user_id: Discord user ID
            channel_id: Discord channel ID
            message_id: Discord message ID
            guild_id: Discord guild ID (None for DMs)
            confirmed: Whether the entry was confirmed by user

        Returns:
            LedgerEntry for backward compatibility

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
                # Ensure system accounts exist
                self.ensure_system_accounts(user_id)

                # Determine accounts and entry types based on transaction action
                debit_account_name: str
                credit_account_name: str
                debit_account_type: AccountType
                credit_account_type: AccountType

                if parsed.action == TransactionAction.INCOMING:
                    # Income: Debit Asset (where money goes), Credit Revenue (source)
                    debit_account_name = parsed.destination or "cash"
                    credit_account_name = parsed.source or "income"
                    debit_account_type = self.infer_account_type(debit_account_name)
                    credit_account_type = AccountType.REVENUE
                    # Ensure debit is an asset
                    if debit_account_type not in (
                        AccountType.ASSET,
                        AccountType.EXPENSE,
                    ):
                        debit_account_type = AccountType.ASSET

                elif parsed.action == TransactionAction.OUTGOING:
                    # Expense: Debit Expense (purpose), Credit Asset (where money comes from)
                    debit_account_name = parsed.destination or "expense"
                    credit_account_name = parsed.source or "cash"
                    debit_account_type = AccountType.EXPENSE
                    credit_account_type = self.infer_account_type(credit_account_name)
                    # Ensure credit is an asset
                    if credit_account_type not in (
                        AccountType.ASSET,
                        AccountType.LIABILITY,
                    ):
                        credit_account_type = AccountType.ASSET

                elif parsed.action == TransactionAction.TRANSFER:
                    # Transfer: Debit destination Asset, Credit source Asset
                    debit_account_name = parsed.destination or "cash"
                    credit_account_name = parsed.source or "cash"
                    debit_account_type = self.infer_account_type(debit_account_name)
                    credit_account_type = self.infer_account_type(credit_account_name)
                    # Both should be assets for a transfer
                    if debit_account_type not in (
                        AccountType.ASSET,
                        AccountType.LIABILITY,
                    ):
                        debit_account_type = AccountType.ASSET
                    if credit_account_type not in (
                        AccountType.ASSET,
                        AccountType.LIABILITY,
                    ):
                        credit_account_type = AccountType.ASSET

                else:
                    raise ValueError(f"Unknown transaction action: {parsed.action}")

                # Try to resolve accounts via alias system
                debit_group = self.resolve_account_alias(debit_account_name, user_id)
                credit_group = self.resolve_account_alias(credit_account_name, user_id)

                # Get or create legacy accounts (for backward compat)
                debit_account = self.get_or_create_account(
                    name=debit_account_name,
                    user_id=user_id,
                    account_type=debit_account_type,
                    group_id=debit_group.id if debit_group else None,
                )
                credit_account = self.get_or_create_account(
                    name=credit_account_name,
                    user_id=user_id,
                    account_type=credit_account_type,
                    group_id=credit_group.id if credit_group else None,
                )

                # Use group name for display if available, else use raw name
                debit_display_name = (
                    debit_group.name if debit_group else debit_account_name
                )
                credit_display_name = (
                    credit_group.name if credit_group else credit_account_name
                )

                # Create transaction record
                cursor = conn.execute(
                    """
                    INSERT INTO transactions (
                        description, raw_text, confidence, user_id, guild_id,
                        channel_id, message_id, created_at, confirmed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
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
                transaction_id = cursor.lastrowid

                # Create journal entries (balanced debit and credit)
                # Use group ID if available, else use legacy account ID
                debit_journal_account_id = (
                    debit_group.id if debit_group else debit_account.id
                )
                credit_journal_account_id = (
                    credit_group.id if credit_group else credit_account.id
                )

                conn.execute(
                    """
                    INSERT INTO journal_entries (
                        transaction_id, account_id, account_name, entry_type, amount
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        debit_journal_account_id,
                        debit_display_name,
                        EntryType.DEBIT.value,
                        parsed.amount,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO journal_entries (
                        transaction_id, account_id, account_name, entry_type, amount
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        transaction_id,
                        credit_journal_account_id,
                        credit_display_name,
                        EntryType.CREDIT.value,
                        parsed.amount,
                    ),
                )

                # Create legacy ledger entry for backward compatibility
                cursor = conn.execute(
                    """
                    INSERT INTO ledger_entries (
                        action, amount, source, destination, description,
                        raw_text, confidence, user_id, guild_id, channel_id,
                        message_id, created_at, confirmed, transaction_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        transaction_id,
                    ),
                )

                entry_id = cursor.lastrowid
                logger.info(
                    f"Inserted double-entry transaction {transaction_id} "
                    f"(ledger entry {entry_id}) for user {user_id}: "
                    f"DR {debit_display_name} / CR {credit_display_name} = {parsed.amount}"
                )

                return LedgerEntry(
                    id=entry_id,
                    action=parsed.action.value,
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
                    transaction_id=transaction_id,
                )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error inserting transaction: {e}", exc_info=True)
            raise

    def get_transaction_by_id(self, transaction_id: int) -> Optional[Transaction]:
        """
        Get a transaction with its journal entries by ID.

        Args:
            transaction_id: Transaction ID

        Returns:
            Transaction with entries, or None if not found
        """
        if transaction_id <= 0:
            raise ValueError(f"Invalid transaction_id: {transaction_id}")

        try:
            with self._get_connection() as conn:
                # Get transaction
                cursor = conn.execute(
                    """
                    SELECT id, description, raw_text, confidence, user_id,
                           guild_id, channel_id, message_id, created_at, confirmed
                    FROM transactions
                    WHERE id = ?
                    """,
                    (transaction_id,),
                )
                row = cursor.fetchone()

                if not row:
                    return None

                transaction = Transaction(
                    id=row[0],
                    description=row[1],
                    raw_text=row[2],
                    confidence=row[3],
                    user_id=row[4],
                    guild_id=row[5],
                    channel_id=row[6],
                    message_id=row[7],
                    created_at=datetime.fromisoformat(row[8]),
                    confirmed=bool(row[9]),
                    entries=[],
                )

                # Get journal entries
                cursor = conn.execute(
                    """
                    SELECT id, transaction_id, account_id, account_name, entry_type, amount
                    FROM journal_entries
                    WHERE transaction_id = ?
                    ORDER BY entry_type DESC
                    """,
                    (transaction_id,),
                )

                for entry_row in cursor.fetchall():
                    transaction.entries.append(
                        JournalEntry(
                            id=entry_row[0],
                            transaction_id=entry_row[1],
                            account_id=entry_row[2],
                            account_name=entry_row[3],
                            entry_type=EntryType(entry_row[4]),
                            amount=entry_row[5],
                        )
                    )

                return transaction
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting transaction {transaction_id}: {e}", exc_info=True
            )
            raise

    def get_by_id(self, entry_id: int) -> Optional[LedgerEntry]:
        """
        Get a ledger entry by ID.

        Args:
            entry_id: Entry ID

        Returns:
            LedgerEntry or None if not found
        """
        if entry_id <= 0:
            raise ValueError(f"Invalid entry_id: {entry_id}")

        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, action, amount, source, destination, description,
                           raw_text, confidence, user_id, guild_id, channel_id,
                           message_id, created_at, confirmed, transaction_id
                    FROM ledger_entries
                    WHERE id = ?
                    """,
                    (entry_id,),
                )
                row = cursor.fetchone()

                if not row:
                    return None

                return LedgerEntry(
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
        except ValueError:
            raise
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
        Get ledger entries for a user.

        Args:
            user_id: Discord user ID
            limit: Maximum number of entries to return
            offset: Number of entries to skip
            action: Optional filter by action type

        Returns:
            List of LedgerEntry objects
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        if limit <= 0 or limit > 100:
            limit = 10
        if offset < 0:
            offset = 0

        try:
            with self._get_connection() as conn:
                if action:
                    cursor = conn.execute(
                        """
                        SELECT id, action, amount, source, destination, description,
                               raw_text, confidence, user_id, guild_id, channel_id,
                               message_id, created_at, confirmed, transaction_id
                        FROM ledger_entries
                        WHERE user_id = ? AND action = ?
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (user_id, action.value, limit, offset),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT id, action, amount, source, destination, description,
                               raw_text, confidence, user_id, guild_id, channel_id,
                               message_id, created_at, confirmed, transaction_id
                        FROM ledger_entries
                        WHERE user_id = ?
                        ORDER BY created_at DESC
                        LIMIT ? OFFSET ?
                        """,
                        (user_id, limit, offset),
                    )

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
        """
        if not user_id or not isinstance(user_id, str):
            raise ValueError(f"Invalid user_id: {user_id}")

        try:
            with self._get_connection() as conn:
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
                # Get all journal entries with account info for this user
                # Use account_groups for canonical names, fallback to accounts
                cursor = conn.execute(
                    """
                    SELECT
                        je.account_name as name,
                        COALESCE(ag.account_type, a.account_type) as acct_type,
                        je.entry_type,
                        SUM(je.amount) as total
                    FROM journal_entries je
                    LEFT JOIN account_groups ag ON je.account_id = ag.id
                    LEFT JOIN accounts a ON je.account_id = a.id
                    JOIN transactions t ON je.transaction_id = t.id
                    WHERE t.user_id = ?
                    GROUP BY je.account_name, acct_type, je.entry_type
                    """,
                    (user_id,),
                )

                # Calculate balances using proper accounting rules
                # Now we aggregate by account_name from journal entries,
                # which uses the canonical group name when available
                account_debits: dict[str, float] = {}
                account_credits: dict[str, float] = {}
                account_types: dict[str, AccountType] = {}

                for row in cursor.fetchall():
                    account_name = row["name"]
                    account_type = AccountType(row["acct_type"])
                    entry_type = EntryType(row["entry_type"])
                    amount = row["total"] or 0.0

                    if account_name not in account_types:
                        account_debits[account_name] = 0.0
                        account_credits[account_name] = 0.0
                        account_types[account_name] = account_type

                    if entry_type == EntryType.DEBIT:
                        account_debits[account_name] += amount
                    else:
                        account_credits[account_name] += amount

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
                    f"Calculated balances for {len(balances)} accounts for user {user_id}"
                )
                return balances
        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error getting balances for user {user_id}: {e}", exc_info=True
            )
            raise

    def get_account_ledger(
        self,
        user_id: str,
        account_name: str,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get detailed ledger for a specific account (T-account format).

        Args:
            user_id: Discord user ID
            account_name: Name of the account
            limit: Maximum number of entries

        Returns:
            List of dictionaries with transaction details and running balance
        """
        if not user_id or not account_name:
            raise ValueError("User ID and account name are required")

        account_name = account_name.strip().lower()

        try:
            with self._get_connection() as conn:
                # Get account info
                cursor = conn.execute(
                    """
                    SELECT id, account_type FROM accounts
                    WHERE name = ? AND user_id = ?
                    """,
                    (account_name, user_id),
                )
                account_row = cursor.fetchone()

                if not account_row:
                    return []

                account_id = account_row[0]
                account_type = AccountType(account_row[1])

                # Get journal entries for this account
                cursor = conn.execute(
                    """
                    SELECT
                        je.id,
                        je.entry_type,
                        je.amount,
                        t.id as transaction_id,
                        t.description,
                        t.created_at
                    FROM journal_entries je
                    JOIN transactions t ON je.transaction_id = t.id
                    WHERE je.account_id = ? AND t.user_id = ?
                    ORDER BY t.created_at DESC
                    LIMIT ?
                    """,
                    (account_id, user_id, limit),
                )

                debit_normal = account_type in {AccountType.ASSET, AccountType.EXPENSE}
                entries = []

                for row in cursor.fetchall():
                    entry_type = EntryType(row["entry_type"])
                    amount = row["amount"]

                    # Calculate the effect on balance
                    if debit_normal:
                        effect = amount if entry_type == EntryType.DEBIT else -amount
                    else:
                        effect = amount if entry_type == EntryType.CREDIT else -amount

                    entries.append(
                        {
                            "id": row["id"],
                            "transaction_id": row["transaction_id"],
                            "entry_type": entry_type.value,
                            "amount": amount,
                            "effect": effect,
                            "description": row["description"],
                            "created_at": row["created_at"],
                        }
                    )

                return entries
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error getting account ledger: {e}", exc_info=True)
            raise

    def delete_entry(self, entry_id: int, user_id: str) -> bool:
        """
        Delete a ledger entry and its associated double-entry transaction.

        Args:
            entry_id: Entry ID to delete
            user_id: User ID (for authorization)

        Returns:
            True if deleted, False if not found or not authorized
        """
        if entry_id <= 0:
            raise ValueError(f"Invalid entry_id: {entry_id}")
        if not user_id:
            raise ValueError("User ID is required")

        try:
            with self._get_connection() as conn:
                # Get the entry and verify ownership
                cursor = conn.execute(
                    """
                    SELECT transaction_id, user_id FROM ledger_entries
                    WHERE id = ?
                    """,
                    (entry_id,),
                )
                row = cursor.fetchone()

                if not row:
                    return False

                if row["user_id"] != user_id:
                    logger.warning(
                        f"User {user_id} attempted to delete entry {entry_id} owned by {row['user_id']}"
                    )
                    return False

                transaction_id = row["transaction_id"]

                # Delete the ledger entry
                conn.execute("DELETE FROM ledger_entries WHERE id = ?", (entry_id,))

                # Delete associated transaction and journal entries (cascade)
                if transaction_id:
                    conn.execute(
                        "DELETE FROM journal_entries WHERE transaction_id = ?",
                        (transaction_id,),
                    )
                    conn.execute(
                        "DELETE FROM transactions WHERE id = ?", (transaction_id,)
                    )

                logger.info(
                    f"Deleted entry {entry_id} and transaction {transaction_id} for user {user_id}"
                )
                return True
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting entry {entry_id}: {e}", exc_info=True)
            raise

    def count_user_entries(
        self,
        user_id: str,
        action: Optional[TransactionAction] = None,
    ) -> int:
        """
        Count total entries for a user.

        Args:
            user_id: Discord user ID
            action: Optional filter by action type

        Returns:
            Count of entries
        """
        if not user_id:
            raise ValueError("User ID is required")

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
                        """
                        SELECT COUNT(*) FROM ledger_entries
                        WHERE user_id = ?
                        """,
                        (user_id,),
                    )

                return cursor.fetchone()[0]
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

    # ==================== Double-Entry Specific Methods ====================

    def get_trial_balance(self, user_id: str) -> dict[str, Any]:
        """
        Generate a trial balance report.

        In double-entry bookkeeping, the trial balance verifies that
        total debits equal total credits.

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
                        COALESCE(ag.account_type, a.account_type) as acct_type,
                        SUM(CASE WHEN je.entry_type = 'debit' THEN je.amount ELSE 0 END) as total_debit,
                        SUM(CASE WHEN je.entry_type = 'credit' THEN je.amount ELSE 0 END) as total_credit
                    FROM journal_entries je
                    LEFT JOIN account_groups ag ON je.account_id = ag.id
                    LEFT JOIN accounts a ON je.account_id = a.id
                    JOIN transactions t ON je.transaction_id = t.id
                    WHERE t.user_id = ?
                    GROUP BY je.account_name, acct_type
                    ORDER BY acct_type, je.account_name
                    """,
                    (user_id,),
                )

                accounts = []
                total_debits = 0.0
                total_credits = 0.0

                for row in cursor.fetchall():
                    debit = row["total_debit"] or 0.0
                    credit = row["total_credit"] or 0.0
                    total_debits += debit
                    total_credits += credit

                    accounts.append(
                        {
                            "name": row["name"],
                            "type": row["acct_type"],
                            "debit": debit,
                            "credit": credit,
                        }
                    )

                is_balanced = abs(total_debits - total_credits) < 0.01

                return {
                    "accounts": accounts,
                    "total_debits": total_debits,
                    "total_credits": total_credits,
                    "is_balanced": is_balanced,
                    "difference": total_debits - total_credits,
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

        Shows revenue minus expenses for a period.

        Args:
            user_id: Discord user ID
            start_date: Optional start date
            end_date: Optional end date

        Returns:
            Dictionary with income statement data
        """
        if not user_id:
            raise ValueError("User ID is required")

        try:
            with self._get_connection() as conn:
                query = """
                    SELECT
                        je.account_name as name,
                        COALESCE(ag.account_type, a.account_type) as acct_type,
                        SUM(CASE WHEN je.entry_type = 'debit' THEN je.amount ELSE 0 END) as total_debit,
                        SUM(CASE WHEN je.entry_type = 'credit' THEN je.amount ELSE 0 END) as total_credit
                    FROM journal_entries je
                    LEFT JOIN account_groups ag ON je.account_id = ag.id
                    LEFT JOIN accounts a ON je.account_id = a.id
                    JOIN transactions t ON je.transaction_id = t.id
                    WHERE t.user_id = ?
                      AND COALESCE(ag.account_type, a.account_type) IN ('revenue', 'expense')
                """
                params: list = [user_id]

                if start_date:
                    query += " AND date(t.created_at) >= ?"
                    params.append(start_date.isoformat())

                if end_date:
                    query += " AND date(t.created_at) <= ?"
                    params.append(end_date.isoformat())

                query += " GROUP BY je.account_name, acct_type ORDER BY acct_type DESC, je.account_name"

                cursor = conn.execute(query, params)

                revenue_accounts = []
                expense_accounts = []
                total_revenue = 0.0
                total_expenses = 0.0

                for row in cursor.fetchall():
                    account_type = AccountType(row["acct_type"])
                    debit = row["total_debit"] or 0.0
                    credit = row["total_credit"] or 0.0

                    if account_type == AccountType.REVENUE:
                        # Revenue: balance = credits - debits
                        balance = credit - debit
                        total_revenue += balance
                        revenue_accounts.append(
                            {
                                "name": row["name"],
                                "amount": balance,
                            }
                        )
                    else:
                        # Expense: balance = debits - credits
                        balance = debit - credit
                        total_expenses += balance
                        expense_accounts.append(
                            {
                                "name": row["name"],
                                "amount": balance,
                            }
                        )

                net_income = total_revenue - total_expenses

                return {
                    "revenue": revenue_accounts,
                    "expenses": expense_accounts,
                    "total_revenue": total_revenue,
                    "total_expenses": total_expenses,
                    "net_income": net_income,
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
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
        Assets = Liabilities + Equity (+ Retained Earnings from Revenue - Expenses)

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
                # Get account types
                cursor = conn.execute(
                    """
                    SELECT name, account_type FROM accounts
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )

                account_types = {
                    row["name"]: AccountType(row["account_type"])
                    for row in cursor.fetchall()
                }

            assets = []
            liabilities = []
            equity = []
            total_assets = 0.0
            total_liabilities = 0.0
            total_equity = 0.0

            for account_name, balance in balances.items():
                account_type = account_types.get(account_name, AccountType.ASSET)

                if account_type == AccountType.ASSET:
                    assets.append({"name": account_name, "amount": balance})
                    total_assets += balance
                elif account_type == AccountType.LIABILITY:
                    liabilities.append({"name": account_name, "amount": balance})
                    total_liabilities += balance
                elif account_type == AccountType.EQUITY:
                    equity.append({"name": account_name, "amount": balance})
                    total_equity += balance
                # Revenue and Expense accounts contribute to retained earnings
                elif account_type == AccountType.REVENUE:
                    total_equity += balance  # Add to retained earnings
                elif account_type == AccountType.EXPENSE:
                    total_equity -= balance  # Subtract from retained earnings

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


# Module-level repository instance
_repository: Optional[LedgerRepository] = None


def get_repository() -> LedgerRepository:
    """Get or create the global repository instance."""
    global _repository
    if _repository is None:
        _repository = LedgerRepository()
    return _repository

"""
Accounts repository module for account groups, aliases, and legacy accounts.

Handles all account-related database operations including:
- Account groups (canonical accounts)
- Account aliases (name mappings)
- Legacy accounts (backward compatibility)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from yuuka.models.account import AccountType

from .base import BaseRepository
from .models import Account, AccountAlias, AccountGroup

logger = logging.getLogger(__name__)


class AccountRepository(BaseRepository):
    """
    Repository for managing accounts, account groups, and aliases.

    This handles the account aliasing system where multiple input names
    can map to a single canonical account group.
    """

    def __init__(self, db_path=None, init_schema: bool = False):
        """
        Initialize the account repository.

        Args:
            db_path: Path to the SQLite database file
            init_schema: Whether to initialize schema (usually False,
                        as main repository handles this)
        """
        super().__init__(db_path, init_schema=init_schema)

    # =========================================================================
    # Account Groups
    # =========================================================================

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

    # =========================================================================
    # Account Aliases
    # =========================================================================

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

    # =========================================================================
    # System Account Groups
    # =========================================================================

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

    # =========================================================================
    # Legacy Accounts (for backward compatibility)
    # =========================================================================

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
                    SELECT id, name, account_type, user_id, description,
                           is_system, group_id
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

    # =========================================================================
    # Account Type Inference
    # =========================================================================

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

        # Default to asset for unknown accounts (most common for personal finance)
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

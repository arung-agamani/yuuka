"""
Account models for double-entry bookkeeping.

Defines account types, the Account model, and AccountGroup for aliasing
used in double-entry ledger.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class AccountType(str, Enum):
    """
    Standard accounting account types.

    In double-entry bookkeeping:
    - ASSET: Resources owned (cash, bank accounts, etc.) - Debit increases, Credit decreases
    - LIABILITY: Amounts owed to others - Credit increases, Debit decreases
    - EQUITY: Owner's stake in the business - Credit increases, Debit decreases
    - REVENUE: Income earned - Credit increases, Debit decreases
    - EXPENSE: Costs incurred - Debit increases, Credit decreases
    """

    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class EntryType(str, Enum):
    """Type of ledger entry in double-entry bookkeeping."""

    DEBIT = "debit"
    CREDIT = "credit"


@dataclass
class AccountGroup:
    """
    Represents a group of account aliases.

    An AccountGroup is the canonical account that multiple aliases can map to.
    For example, "main pocket", "jago main pocket", and "main wallet" could all
    be aliases that map to a single "Main Wallet" account group.

    Attributes:
        id: Database ID
        name: Canonical display name for the account group
        account_type: Type of account (asset, liability, etc.)
        user_id: Discord user ID who owns this group
        description: Optional description
        is_system: Whether this is a system-created account
        created_at: When the group was created
    """

    id: Optional[int]
    name: str
    account_type: AccountType
    user_id: str
    description: Optional[str] = None
    is_system: bool = False
    created_at: Optional[datetime] = None

    def __post_init__(self):
        """Normalize the canonical name (preserve case for display)."""
        if self.name:
            self.name = self.name.strip()

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "account_type": self.account_type.value,
            "user_id": self.user_id,
            "description": self.description,
            "is_system": self.is_system,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "AccountGroup":
        """Create an AccountGroup from a database row."""
        return cls(
            id=row[0],
            name=row[1],
            account_type=AccountType(row[2]),
            user_id=row[3],
            description=row[4],
            is_system=bool(row[5]),
            created_at=datetime.fromisoformat(row[6]) if row[6] else None,
        )


@dataclass
class AccountAlias:
    """
    Represents an alias that maps to an AccountGroup.

    When users input natural language like "main pocket" or "jago main pocket",
    the system looks up the alias to find the canonical AccountGroup.

    Attributes:
        id: Database ID
        alias: The alias string (normalized to lowercase)
        group_id: The AccountGroup this alias maps to
        user_id: Discord user ID who owns this alias
        created_at: When the alias was created
    """

    id: Optional[int]
    alias: str
    group_id: int
    user_id: str
    created_at: Optional[datetime] = None

    def __post_init__(self):
        """Normalize alias to lowercase for matching."""
        if self.alias:
            self.alias = self.alias.strip().lower()

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "alias": self.alias,
            "group_id": self.group_id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "AccountAlias":
        """Create an AccountAlias from a database row."""
        return cls(
            id=row[0],
            alias=row[1],
            group_id=row[2],
            user_id=row[3],
            created_at=datetime.fromisoformat(row[4]) if row[4] else None,
        )


@dataclass
class Account:
    """
    Represents an account in the chart of accounts.

    Each account has a type that determines how debits and credits affect its balance.

    Note: This is now primarily used for backward compatibility. New code should
    use AccountGroup and AccountAlias for better alias handling.
    """

    id: Optional[int]
    name: str
    account_type: AccountType
    user_id: str
    description: Optional[str] = None
    is_system: bool = False
    group_id: Optional[int] = None  # Link to AccountGroup

    def __post_init__(self):
        """Normalize account name."""
        if self.name:
            self.name = self.name.strip().lower()

    def get_balance_multiplier(self, entry_type: EntryType) -> int:
        """
        Get the multiplier for calculating balance based on account type and entry type.

        For ASSET and EXPENSE accounts:
            - Debit increases balance (+1)
            - Credit decreases balance (-1)

        For LIABILITY, EQUITY, and REVENUE accounts:
            - Credit increases balance (+1)
            - Debit decreases balance (-1)

        Returns:
            1 if the entry increases the account balance, -1 if it decreases
        """
        debit_normal_accounts = {AccountType.ASSET, AccountType.EXPENSE}

        if self.account_type in debit_normal_accounts:
            return 1 if entry_type == EntryType.DEBIT else -1
        else:
            return 1 if entry_type == EntryType.CREDIT else -1

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "account_type": self.account_type.value,
            "user_id": self.user_id,
            "description": self.description,
            "is_system": self.is_system,
            "group_id": self.group_id,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "Account":
        """Create an Account from a database row."""
        return cls(
            id=row[0],
            name=row[1],
            account_type=AccountType(row[2]),
            user_id=row[3],
            description=row[4],
            is_system=bool(row[5]),
            group_id=row[6] if len(row) > 6 else None,
        )


# Default system account groups that will be auto-created for each user
DEFAULT_SYSTEM_ACCOUNTS = [
    ("Income", AccountType.REVENUE, "Default income account"),
    ("Expense", AccountType.EXPENSE, "Default expense account"),
    ("Cash", AccountType.ASSET, "Default cash/wallet account"),
]

"""
Database models for Yuuka double-entry ledger.

Defines the schema for storing transactions and journal entries in SQLite
using proper double-entry bookkeeping principles.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from yuuka.models.account import AccountType, EntryType


@dataclass
class AccountGroup:
    """
    Represents a group of account aliases (canonical account).

    An AccountGroup is the canonical account that multiple aliases can map to.
    For example, "main pocket", "jago main pocket", and "main wallet" could all
    be aliases that map to a single "Main Wallet" account group.
    """

    id: Optional[int]
    name: str  # Canonical display name (preserves case)
    account_type: AccountType
    user_id: str
    description: Optional[str] = None
    is_system: bool = False
    created_at: Optional[datetime] = None

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
    """

    id: Optional[int]
    alias: str  # Normalized to lowercase for matching
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

    Note: This is maintained for backward compatibility. New transactions use
    AccountGroup for the canonical account and AccountAlias for name resolution.
    """

    id: Optional[int]
    name: str
    account_type: AccountType
    user_id: str
    description: Optional[str] = None
    is_system: bool = False
    group_id: Optional[int] = None  # Link to AccountGroup

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


@dataclass
class JournalEntry:
    """
    Represents a single journal entry (one side of a double-entry transaction).

    In double-entry bookkeeping, every transaction has at least two journal entries:
    one debit and one credit, which must balance.
    """

    id: Optional[int]
    transaction_id: int
    account_id: int  # References AccountGroup.id
    account_name: str  # Denormalized for display (canonical name from group)
    entry_type: EntryType
    amount: float

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "transaction_id": self.transaction_id,
            "account_id": self.account_id,
            "account_name": self.account_name,
            "entry_type": self.entry_type.value,
            "amount": self.amount,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "JournalEntry":
        """Create a JournalEntry from a database row."""
        return cls(
            id=row[0],
            transaction_id=row[1],
            account_id=row[2],
            account_name=row[3],
            entry_type=EntryType(row[4]),
            amount=row[5],
        )


@dataclass
class Transaction:
    """
    Represents a complete transaction in the double-entry ledger.

    A transaction groups related journal entries together. The sum of all
    debit entries must equal the sum of all credit entries.
    """

    id: Optional[int]
    description: Optional[str]
    raw_text: str
    confidence: float
    user_id: str
    guild_id: Optional[str]
    channel_id: str
    message_id: str
    created_at: datetime
    confirmed: bool = True
    entries: list[JournalEntry] = field(default_factory=list)

    def total_debits(self) -> float:
        """Calculate total debit amount."""
        return sum(e.amount for e in self.entries if e.entry_type == EntryType.DEBIT)

    def total_credits(self) -> float:
        """Calculate total credit amount."""
        return sum(e.amount for e in self.entries if e.entry_type == EntryType.CREDIT)

    def is_balanced(self) -> bool:
        """Check if debits equal credits (accounting equation)."""
        return abs(self.total_debits() - self.total_credits()) < 0.01

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "description": self.description,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "created_at": self.created_at.isoformat(),
            "confirmed": self.confirmed,
            "entries": [e.to_dict() for e in self.entries],
            "total_debits": self.total_debits(),
            "total_credits": self.total_credits(),
            "is_balanced": self.is_balanced(),
        }

    @classmethod
    def from_row(cls, row: tuple) -> "Transaction":
        """Create a Transaction from a database row (without entries)."""
        return cls(
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


# Legacy alias for backward compatibility during migration
@dataclass
class LedgerEntry:
    """
    Legacy ledger entry model - kept for backward compatibility.

    This represents the old single-entry format. New code should use
    Transaction and JournalEntry instead.
    """

    id: Optional[int]
    action: str  # 'incoming', 'outgoing', 'transfer'
    amount: float
    source: Optional[str]
    destination: Optional[str]
    description: Optional[str]
    raw_text: str
    confidence: float
    user_id: str
    guild_id: Optional[str]
    channel_id: str
    message_id: str
    created_at: datetime
    confirmed: bool = True
    # New field to link to double-entry transaction
    transaction_id: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "action": self.action,
            "amount": self.amount,
            "source": self.source,
            "destination": self.destination,
            "description": self.description,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "message_id": self.message_id,
            "created_at": self.created_at.isoformat(),
            "confirmed": self.confirmed,
            "transaction_id": self.transaction_id,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "LedgerEntry":
        """Create a LedgerEntry from a database row."""
        return cls(
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
            transaction_id=row[14] if len(row) > 14 else None,
        )

    @classmethod
    def from_transaction(cls, txn: Transaction) -> "LedgerEntry":
        """
        Create a LedgerEntry view from a Transaction for backward compatibility.

        This converts the double-entry transaction back to a single-entry format
        for display purposes.
        """
        # Determine action type and source/destination from journal entries
        debit_entries = [e for e in txn.entries if e.entry_type == EntryType.DEBIT]
        credit_entries = [e for e in txn.entries if e.entry_type == EntryType.CREDIT]

        # Default values
        action = "transfer"
        source = None
        destination = None
        amount = txn.total_debits()

        # Analyze entries to determine action type
        if len(debit_entries) == 1 and len(credit_entries) == 1:
            debit = debit_entries[0]
            credit = credit_entries[0]

            # Check account names to determine action
            debit_name = debit.account_name.lower()
            credit_name = credit.account_name.lower()

            if credit_name in ("income", "revenue", "salary"):
                # Income transaction: Debit Asset, Credit Revenue
                action = "incoming"
                destination = debit_name
                source = credit_name
            elif debit_name in ("expense", "expenses"):
                # Expense transaction: Debit Expense, Credit Asset
                action = "outgoing"
                source = credit_name
                destination = debit_name
            else:
                # Transfer between accounts
                action = "transfer"
                source = credit_name
                destination = debit_name

        return cls(
            id=txn.id,
            action=action,
            amount=amount,
            source=source,
            destination=destination,
            description=txn.description,
            raw_text=txn.raw_text,
            confidence=txn.confidence,
            user_id=txn.user_id,
            guild_id=txn.guild_id,
            channel_id=txn.channel_id,
            message_id=txn.message_id,
            created_at=txn.created_at,
            confirmed=txn.confirmed,
            transaction_id=txn.id,
        )

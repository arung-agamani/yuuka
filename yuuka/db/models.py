"""
Database models for Yuuka ledger entries.

Defines the schema for storing transaction records in SQLite.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from yuuka.models import TransactionAction


@dataclass
class LedgerEntry:
    """Represents a ledger entry stored in the database."""

    id: Optional[int]
    action: TransactionAction
    amount: float
    source: Optional[str]
    destination: Optional[str]
    description: Optional[str]
    raw_text: str
    confidence: float
    user_id: str  # Discord user ID
    guild_id: Optional[str]  # Discord guild ID (None for DMs)
    channel_id: str  # Discord channel ID
    message_id: str  # Discord message ID
    created_at: datetime
    confirmed: bool = True  # Whether user confirmed low-confidence parse

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "action": self.action.value,
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
        }

    @classmethod
    def from_row(cls, row: tuple) -> "LedgerEntry":
        """Create a LedgerEntry from a database row."""
        return cls(
            id=row[0],
            action=TransactionAction(row[1]),
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
        )

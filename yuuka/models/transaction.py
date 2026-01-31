from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TransactionAction(str, Enum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    TRANSFER = "transfer"


@dataclass
class ParsedTransaction:
    """Structured output from NLP parsing of transaction text."""

    action: TransactionAction
    amount: Optional[float] = None
    source: Optional[str] = None  # "from" - source of funds
    destination: Optional[str] = None  # "to" - destination of funds
    description: Optional[str] = None  # purpose/note for the transaction
    raw_text: str = ""  # original input text
    confidence: float = 0.0  # parsing confidence score

    def is_valid(self) -> bool:
        """Check if the parsed transaction has minimum required fields."""
        has_amount = self.amount is not None and self.amount > 0

        if self.action == TransactionAction.TRANSFER:
            return (
                has_amount and self.source is not None and self.destination is not None
            )
        elif self.action == TransactionAction.INCOMING:
            return has_amount and self.destination is not None
        elif self.action == TransactionAction.OUTGOING:
            return has_amount and self.source is not None

        return False

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "action": self.action.value,
            "amount": self.amount,
            "source": self.source,
            "destination": self.destination,
            "description": self.description,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
        }

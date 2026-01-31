"""
Yuuka - Transaction NLP Service

A natural language processing service for parsing transaction descriptions
into structured data, designed for ledger applications.
"""

from .bot import YuukaBot, create_bot
from .bot import run as run_bot
from .models import ParsedTransaction, TransactionAction
from .services import (
    AmountParser,
    TransactionNLPService,
    get_nlp_service,
    parse_transaction,
)

__version__ = "0.1.0"

__all__ = [
    "AmountParser",
    "ParsedTransaction",
    "TransactionAction",
    "TransactionNLPService",
    "YuukaBot",
    "create_bot",
    "get_nlp_service",
    "parse_transaction",
    "run_bot",
]

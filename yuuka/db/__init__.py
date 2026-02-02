"""
Database module for Yuuka ledger system.

This module provides the database layer for the double-entry bookkeeping system,
including repositories for accounts, transactions, and queries.

Structure:
- base.py: Base repository with connection management and schema
- models.py: Data models (Account, Transaction, JournalEntry, etc.)
- accounts.py: Account groups, aliases, and legacy accounts
- transactions.py: Transaction CRUD operations
- queries.py: Balance calculations and analytics
- repository.py: Main facade that composes all sub-repositories
- budget.py: Budget configuration for forecasting
"""

from .accounts import AccountRepository
from .base import DEFAULT_DB_PATH, BaseRepository
from .budget import BudgetConfig, BudgetRepository
from .models import (
    Account,
    AccountAlias,
    AccountGroup,
    JournalEntry,
    LedgerEntry,
    Transaction,
)
from .queries import QueryRepository
from .repository import LedgerRepository, get_repository
from .transactions import TransactionRepository

__all__ = [
    # Base
    "BaseRepository",
    "DEFAULT_DB_PATH",
    # Models
    "Account",
    "AccountAlias",
    "AccountGroup",
    "JournalEntry",
    "LedgerEntry",
    "Transaction",
    # Repositories
    "AccountRepository",
    "BudgetConfig",
    "BudgetRepository",
    "LedgerRepository",
    "QueryRepository",
    "TransactionRepository",
    # Utilities
    "get_repository",
]

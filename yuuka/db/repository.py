"""
Main repository module that composes all sub-repositories.

This is the primary entry point for database operations in the Yuuka ledger system.
It acts as a facade that delegates to specialized sub-repositories while maintaining
backward compatibility with existing code.
"""

import logging
from datetime import date
from pathlib import Path
from typing import Any, Optional

from yuuka.models import ParsedTransaction, TransactionAction
from yuuka.models.account import AccountType

from .accounts import AccountRepository
from .base import DEFAULT_DB_PATH, BaseRepository
from .models import (
    Account,
    AccountAlias,
    AccountGroup,
    LedgerEntry,
    Transaction,
)
from .queries import QueryRepository
from .transactions import TransactionRepository

logger = logging.getLogger(__name__)


class LedgerRepository(BaseRepository):
    """
    Main repository for managing the double-entry ledger in SQLite.

    This class acts as a facade that composes specialized sub-repositories:
    - AccountRepository: Account groups, aliases, and legacy accounts
    - TransactionRepository: Transaction CRUD operations
    - QueryRepository: Balance calculations and analytics

    All sub-repositories share the same database connection configuration.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the repository and all sub-repositories.

        Args:
            db_path: Path to the SQLite database file. Defaults to data/yuuka.db
        """
        self.db_path = db_path or DEFAULT_DB_PATH

        try:
            # Initialize base (creates schema)
            super().__init__(self.db_path, init_schema=True)

            # Initialize sub-repositories (they share the schema)
            self._account_repo = AccountRepository(self.db_path, init_schema=False)
            self._transaction_repo = TransactionRepository(
                self.db_path, init_schema=False, account_repo=self._account_repo
            )
            self._query_repo = QueryRepository(self.db_path, init_schema=False)

            logger.info(f"LedgerRepository initialized with db_path: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize LedgerRepository: {e}", exc_info=True)
            raise

    # =========================================================================
    # Account Group Methods (delegated to AccountRepository)
    # =========================================================================

    def create_account_group(
        self,
        name: str,
        user_id: str,
        account_type: AccountType,
        description: Optional[str] = None,
        is_system: bool = False,
    ) -> AccountGroup:
        """Create a new account group (canonical account)."""
        return self._account_repo.create_account_group(
            name, user_id, account_type, description, is_system
        )

    def get_account_group_by_id(
        self, group_id: int, user_id: str
    ) -> Optional[AccountGroup]:
        """Get an account group by ID."""
        return self._account_repo.get_account_group_by_id(group_id, user_id)

    def get_account_group_by_name(
        self, name: str, user_id: str
    ) -> Optional[AccountGroup]:
        """Get an account group by its canonical name."""
        return self._account_repo.get_account_group_by_name(name, user_id)

    def get_user_account_groups(self, user_id: str) -> list[AccountGroup]:
        """Get all account groups for a user."""
        return self._account_repo.get_user_account_groups(user_id)

    # =========================================================================
    # Account Alias Methods (delegated to AccountRepository)
    # =========================================================================

    def add_account_alias(
        self,
        alias: str,
        group_id: int,
        user_id: str,
    ) -> AccountAlias:
        """Add an alias to an account group."""
        return self._account_repo.add_account_alias(alias, group_id, user_id)

    def get_aliases_for_group(self, group_id: int, user_id: str) -> list[AccountAlias]:
        """Get all aliases for an account group."""
        return self._account_repo.get_aliases_for_group(group_id, user_id)

    def resolve_account_alias(self, alias: str, user_id: str) -> Optional[AccountGroup]:
        """Resolve an alias to its account group."""
        return self._account_repo.resolve_account_alias(alias, user_id)

    def remove_account_alias(self, alias: str, user_id: str) -> bool:
        """Remove an alias."""
        return self._account_repo.remove_account_alias(alias, user_id)

    def is_unresolved_account(self, name: str, user_id: str) -> bool:
        """Check if an account name is unresolved (no alias mapping exists)."""
        return self._account_repo.is_unresolved_account(name, user_id)

    def get_pending_account_names(self, user_id: str) -> list[str]:
        """Get account names that are used but not mapped to any group."""
        return self._account_repo.get_pending_account_names(user_id)

    def ensure_system_account_groups(self, user_id: str) -> dict[str, AccountGroup]:
        """Ensure all default system account groups exist for a user."""
        return self._account_repo.ensure_system_account_groups(user_id)

    # =========================================================================
    # Legacy Account Methods (delegated to AccountRepository)
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
        """Get an existing account or create a new one."""
        return self._account_repo.get_or_create_account(
            name, user_id, account_type, description, is_system, group_id
        )

    def ensure_system_accounts(self, user_id: str) -> dict[str, Account]:
        """Ensure all default system accounts exist for a user."""
        return self._account_repo.ensure_system_accounts(user_id)

    def get_user_accounts(self, user_id: str) -> list[Account]:
        """Get all accounts for a user."""
        return self._account_repo.get_user_accounts(user_id)

    def infer_account_type(self, name: str) -> AccountType:
        """Infer account type from account name."""
        return self._account_repo.infer_account_type(name)

    def resolve_or_flag_account(
        self,
        name: str,
        user_id: str,
        account_type: AccountType,
    ) -> tuple[Optional[AccountGroup], bool]:
        """Resolve an account name to a group, or flag it as needing user input."""
        return self._account_repo.resolve_or_flag_account(name, user_id, account_type)

    def auto_assign_account_to_group(
        self,
        name: str,
        user_id: str,
        group_id: int,
    ) -> AccountAlias:
        """Automatically assign an account name to a group (creates alias)."""
        return self._account_repo.auto_assign_account_to_group(name, user_id, group_id)

    # =========================================================================
    # Transaction CRUD Methods (delegated to TransactionRepository)
    # =========================================================================

    def insert(
        self,
        parsed: ParsedTransaction,
        user_id: str,
        channel_id: str,
        message_id: str,
        guild_id: Optional[str] = None,
        confirmed: bool = True,
    ) -> LedgerEntry:
        """Insert a new transaction using double-entry bookkeeping."""
        return self._transaction_repo.insert(
            parsed, user_id, channel_id, message_id, guild_id, confirmed
        )

    def get_transaction_by_id(self, transaction_id: int) -> Optional[Transaction]:
        """Get a transaction with its journal entries by ID."""
        return self._transaction_repo.get_transaction_by_id(transaction_id)

    def get_by_id(self, entry_id: int) -> Optional[LedgerEntry]:
        """Get a ledger entry by ID."""
        return self._transaction_repo.get_by_id(entry_id)

    def get_user_entries(
        self,
        user_id: str,
        limit: int = 10,
        offset: int = 0,
        action: Optional[TransactionAction] = None,
    ) -> list[LedgerEntry]:
        """Get ledger entries for a user."""
        return self._transaction_repo.get_user_entries(user_id, limit, offset, action)

    def get_user_summary(self, user_id: str) -> dict[str, Any]:
        """Get a summary of a user's ledger."""
        return self._transaction_repo.get_user_summary(user_id)

    def count_user_entries(
        self,
        user_id: str,
        action: Optional[TransactionAction] = None,
    ) -> int:
        """Count total entries for a user."""
        return self._transaction_repo.count_user_entries(user_id, action)

    def update_transaction(
        self,
        transaction_id: int,
        user_id: str,
        new_amount: Optional[float] = None,
        new_source: Optional[str] = None,
        new_destination: Optional[str] = None,
        new_description: Optional[str] = None,
    ) -> Optional[Transaction]:
        """Update an existing transaction."""
        return self._transaction_repo.update_transaction(
            transaction_id,
            user_id,
            new_amount,
            new_source,
            new_destination,
            new_description,
        )

    def delete_entry(self, entry_id: int, user_id: str) -> bool:
        """Delete a ledger entry and its associated double-entry transaction."""
        return self._transaction_repo.delete_entry(entry_id, user_id)

    # =========================================================================
    # Query Methods (delegated to QueryRepository)
    # =========================================================================

    def get_user_balance_by_account(self, user_id: str) -> dict[str, float]:
        """Calculate balance for each account using double-entry bookkeeping."""
        return self._query_repo.get_user_balance_by_account(user_id)

    def get_total_balance(self, user_id: str) -> float:
        """Get the total balance (sum of all asset accounts) for a user."""
        return self._query_repo.get_total_balance(user_id)

    def get_asset_balances(self, user_id: str) -> dict[str, float]:
        """Get balances for all asset accounts."""
        return self._query_repo.get_asset_balances(user_id)

    def get_account_ledger(
        self,
        user_id: str,
        account_name: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get ledger entries for a specific account."""
        return self._query_repo.get_account_ledger(user_id, account_name, limit)

    def get_entries_for_date_range(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[LedgerEntry]:
        """Get entries for a date range."""
        return self._query_repo.get_entries_for_date_range(
            user_id, start_date, end_date
        )

    def get_entries_for_today(self, user_id: str) -> list[LedgerEntry]:
        """Get all entries for today."""
        return self._query_repo.get_entries_for_today(user_id)

    def get_daily_totals(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, dict[str, float]]:
        """Get daily totals for incoming and outgoing transactions."""
        return self._query_repo.get_daily_totals(user_id, start_date, end_date)

    def get_spending_by_category(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, float]:
        """Get spending breakdown by expense category (account group)."""
        return self._query_repo.get_spending_by_category(user_id, start_date, end_date)

    def get_spending_since_date(self, user_id: str, since_date: date) -> float:
        """Get total spending (outgoing) since a specific date."""
        return self._query_repo.get_spending_since_date(user_id, since_date)

    # =========================================================================
    # Financial Report Methods (delegated to QueryRepository)
    # =========================================================================

    def get_trial_balance(self, user_id: str) -> dict[str, Any]:
        """Generate a trial balance report."""
        return self._query_repo.get_trial_balance(user_id)

    def get_income_statement(
        self,
        user_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """Generate an income statement (profit & loss)."""
        return self._query_repo.get_income_statement(user_id, start_date, end_date)

    def get_balance_sheet(self, user_id: str) -> dict[str, Any]:
        """Generate a balance sheet."""
        return self._query_repo.get_balance_sheet(user_id)


# Module-level singleton for convenience
_repository: Optional[LedgerRepository] = None


def get_repository(db_path: Optional[Path] = None) -> LedgerRepository:
    """
    Get or create the singleton repository instance.

    Args:
        db_path: Optional database path (only used on first call)

    Returns:
        LedgerRepository instance
    """
    global _repository
    if _repository is None:
        _repository = LedgerRepository(db_path)
    return _repository

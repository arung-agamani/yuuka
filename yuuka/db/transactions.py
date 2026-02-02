"""
Transactions repository module for transaction CRUD operations.

Handles all transaction-related database operations including:
- Creating transactions (insert)
- Reading transactions and ledger entries
- Updating transactions
- Deleting transactions
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from yuuka.models import ParsedTransaction, TransactionAction
from yuuka.models.account import AccountType, EntryType

from .base import BaseRepository
from .models import JournalEntry, LedgerEntry, Transaction

if TYPE_CHECKING:
    from .accounts import AccountRepository

logger = logging.getLogger(__name__)


class TransactionRepository(BaseRepository):
    """
    Repository for managing transactions and ledger entries.

    Handles CRUD operations for the double-entry bookkeeping system.
    """

    def __init__(
        self,
        db_path=None,
        init_schema: bool = False,
        account_repo: Optional["AccountRepository"] = None,
    ):
        """
        Initialize the transaction repository.

        Args:
            db_path: Path to the SQLite database file
            init_schema: Whether to initialize schema
            account_repo: Account repository for account operations
        """
        super().__init__(db_path, init_schema=init_schema)
        self._account_repo = account_repo

    def set_account_repo(self, account_repo: "AccountRepository"):
        """Set the account repository reference."""
        self._account_repo = account_repo

    # =========================================================================
    # Create Operations
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
        if not self._account_repo:
            raise RuntimeError("Account repository not set")

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
                self._account_repo.ensure_system_accounts(user_id)

                # Determine accounts and entry types based on transaction action
                debit_account_name: str
                credit_account_name: str
                debit_account_type: AccountType
                credit_account_type: AccountType

                if parsed.action == TransactionAction.INCOMING:
                    # Income: Debit Asset (destination), Credit Revenue (source)
                    debit_account_name = parsed.destination or "cash"
                    credit_account_name = parsed.source or "income"
                    debit_account_type = self._account_repo.infer_account_type(
                        debit_account_name
                    )
                    credit_account_type = AccountType.REVENUE
                    # Ensure debit is an asset
                    if debit_account_type not in (
                        AccountType.ASSET,
                        AccountType.EXPENSE,
                    ):
                        debit_account_type = AccountType.ASSET

                elif parsed.action == TransactionAction.OUTGOING:
                    # Expense: Debit Expense (destination), Credit Asset (source)
                    debit_account_name = parsed.destination or "expense"
                    credit_account_name = parsed.source or "cash"
                    debit_account_type = AccountType.EXPENSE
                    credit_account_type = self._account_repo.infer_account_type(
                        credit_account_name
                    )
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
                    debit_account_type = self._account_repo.infer_account_type(
                        debit_account_name
                    )
                    credit_account_type = self._account_repo.infer_account_type(
                        credit_account_name
                    )
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
                debit_group = self._account_repo.resolve_account_alias(
                    debit_account_name, user_id
                )
                credit_group = self._account_repo.resolve_account_alias(
                    credit_account_name, user_id
                )

                # Get or create legacy accounts (for backward compat)
                debit_account = self._account_repo.get_or_create_account(
                    name=debit_account_name,
                    user_id=user_id,
                    account_type=debit_account_type,
                    group_id=debit_group.id if debit_group else None,
                )
                credit_account = self._account_repo.get_or_create_account(
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
                    f"DR {debit_display_name} / CR {credit_display_name} "
                    f"= {parsed.amount}"
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

    # =========================================================================
    # Read Operations
    # =========================================================================

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
                    SELECT id, transaction_id, account_id, account_name,
                           entry_type, amount
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

    # =========================================================================
    # Update Operations
    # =========================================================================

    def update_transaction(
        self,
        transaction_id: int,
        user_id: str,
        new_amount: Optional[float] = None,
        new_source: Optional[str] = None,
        new_destination: Optional[str] = None,
        new_description: Optional[str] = None,
    ) -> Optional[Transaction]:
        """
        Update an existing transaction's amount, source, destination, or description.

        This updates both the double-entry journal entries and the legacy ledger entry.

        Args:
            transaction_id: Transaction ID to update
            user_id: User ID (for authorization)
            new_amount: New amount (if changing)
            new_source: New source account (if changing)
            new_destination: New destination account (if changing)
            new_description: New description (if changing)

        Returns:
            Updated Transaction if successful, None if not found/unauthorized

        Raises:
            ValueError: If validation fails
        """
        if not self._account_repo:
            raise RuntimeError("Account repository not set")

        if transaction_id <= 0:
            raise ValueError(f"Invalid transaction_id: {transaction_id}")
        if not user_id:
            raise ValueError("User ID is required")
        if new_amount is not None and new_amount <= 0:
            raise ValueError(f"Amount must be positive, got {new_amount}")

        try:
            with self._get_connection() as conn:
                # Get the transaction and verify ownership
                cursor = conn.execute(
                    """
                    SELECT id, description, raw_text, confidence, user_id,
                           guild_id, channel_id, message_id, created_at, confirmed
                    FROM transactions
                    WHERE id = ? AND user_id = ?
                    """,
                    (transaction_id, user_id),
                )
                txn_row = cursor.fetchone()

                if not txn_row:
                    logger.warning(
                        f"Transaction {transaction_id} not found or "
                        f"not owned by user {user_id}"
                    )
                    return None

                # Get the ledger entry for this transaction
                cursor = conn.execute(
                    """
                    SELECT id, action, amount, source, destination
                    FROM ledger_entries
                    WHERE transaction_id = ? AND user_id = ?
                    """,
                    (transaction_id, user_id),
                )
                ledger_row = cursor.fetchone()

                if not ledger_row:
                    logger.error(
                        f"No ledger entry found for transaction {transaction_id}"
                    )
                    return None

                # Get current values
                current_action = ledger_row["action"]
                current_amount = ledger_row["amount"]
                current_source = ledger_row["source"]
                current_destination = ledger_row["destination"]
                ledger_entry_id = ledger_row["id"]

                # Determine new values
                final_amount = new_amount if new_amount is not None else current_amount
                final_source = new_source if new_source is not None else current_source
                final_destination = (
                    new_destination
                    if new_destination is not None
                    else current_destination
                )
                final_description = (
                    new_description
                    if new_description is not None
                    else txn_row["description"]
                )

                # Resolve account groups for new source/destination
                source_group = None
                dest_group = None

                if final_source:
                    source_group = self._account_repo.resolve_account_alias(
                        final_source, user_id
                    )
                if final_destination:
                    dest_group = self._account_repo.resolve_account_alias(
                        final_destination, user_id
                    )

                # Determine account names for journal entries
                if current_action == "incoming":
                    debit_name = dest_group.name if dest_group else final_destination
                    credit_name = source_group.name if source_group else final_source
                elif current_action == "outgoing":
                    debit_name = dest_group.name if dest_group else final_destination
                    credit_name = source_group.name if source_group else final_source
                else:  # transfer
                    debit_name = dest_group.name if dest_group else final_destination
                    credit_name = source_group.name if source_group else final_source

                # Update journal entries
                cursor = conn.execute(
                    """
                    SELECT id, entry_type FROM journal_entries
                    WHERE transaction_id = ?
                    """,
                    (transaction_id,),
                )
                journal_entries = cursor.fetchall()

                for je in journal_entries:
                    if je["entry_type"] == "debit":
                        conn.execute(
                            """
                            UPDATE journal_entries
                            SET amount = ?, account_name = ?
                            WHERE id = ?
                            """,
                            (final_amount, debit_name or "Unknown", je["id"]),
                        )
                    else:  # credit
                        conn.execute(
                            """
                            UPDATE journal_entries
                            SET amount = ?, account_name = ?
                            WHERE id = ?
                            """,
                            (final_amount, credit_name or "Unknown", je["id"]),
                        )

                # Update the transaction description
                conn.execute(
                    """
                    UPDATE transactions
                    SET description = ?
                    WHERE id = ?
                    """,
                    (final_description, transaction_id),
                )

                # Update the legacy ledger entry
                conn.execute(
                    """
                    UPDATE ledger_entries
                    SET amount = ?, source = ?, destination = ?, description = ?
                    WHERE id = ?
                    """,
                    (
                        final_amount,
                        final_source,
                        final_destination,
                        final_description,
                        ledger_entry_id,
                    ),
                )

                logger.info(
                    f"Updated transaction {transaction_id} for user {user_id}: "
                    f"amount={final_amount}, src={final_source}, "
                    f"dest={final_destination}"
                )

                # Return the updated transaction
                return self.get_transaction_by_id(transaction_id)

        except ValueError:
            raise
        except Exception as e:
            logger.error(
                f"Error updating transaction {transaction_id}: {e}", exc_info=True
            )
            raise

    # =========================================================================
    # Delete Operations
    # =========================================================================

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
                        f"User {user_id} attempted to delete entry {entry_id} "
                        f"owned by {row['user_id']}"
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
                    f"Deleted entry {entry_id} and transaction {transaction_id} "
                    f"for user {user_id}"
                )
                return True
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error deleting entry {entry_id}: {e}", exc_info=True)
            raise

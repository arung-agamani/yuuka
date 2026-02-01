#!/usr/bin/env python
"""
Migration script to remove FOREIGN KEY constraint from journal_entries table.

This migration is needed because journal_entries.account_id can reference
either accounts.id OR account_groups.id, but the original schema had a
FOREIGN KEY constraint to only accounts(id), causing constraint violations
when using account groups.

Run this script once to migrate existing databases.
"""

import sqlite3
import sys
from pathlib import Path


def migrate_journal_entries(db_path: str) -> None:
    """
    Remove FOREIGN KEY constraint from journal_entries.account_id.

    Args:
        db_path: Path to the SQLite database file
    """
    print(f"Migrating database: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        # Check if migration is needed
        cursor = conn.execute("PRAGMA foreign_key_list(journal_entries)")
        fkeys = cursor.fetchall()

        has_account_fkey = any(
            row["table"] == "accounts" and row["from"] == "account_id" for row in fkeys
        )

        if not has_account_fkey:
            print("✓ Migration not needed - foreign key constraint already removed")
            return

        print("Starting migration...")

        # Disable foreign keys temporarily
        conn.execute("PRAGMA foreign_keys = OFF")

        # Start transaction
        conn.execute("BEGIN TRANSACTION")

        # Step 1: Create new table without the foreign key constraint
        print("  Creating new journal_entries table...")
        conn.execute("""
            CREATE TABLE journal_entries_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
                account_id INTEGER NOT NULL,
                account_name TEXT NOT NULL,
                entry_type TEXT NOT NULL CHECK(entry_type IN ('debit', 'credit')),
                amount REAL NOT NULL CHECK(amount > 0)
            )
        """)

        # Step 2: Copy all data from old table to new table
        print("  Copying data...")
        cursor = conn.execute("SELECT COUNT(*) as count FROM journal_entries")
        count = cursor.fetchone()["count"]
        print(f"  Found {count} journal entries to migrate")

        conn.execute("""
            INSERT INTO journal_entries_new
                (id, transaction_id, account_id, account_name, entry_type, amount)
            SELECT id, transaction_id, account_id, account_name, entry_type, amount
            FROM journal_entries
        """)

        # Step 3: Drop old table
        print("  Dropping old table...")
        conn.execute("DROP TABLE journal_entries")

        # Step 4: Rename new table
        print("  Renaming new table...")
        conn.execute("ALTER TABLE journal_entries_new RENAME TO journal_entries")

        # Step 5: Recreate indexes if they existed
        print("  Recreating indexes...")
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_journal_entries_transaction_id
            ON journal_entries(transaction_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_journal_entries_account_id
            ON journal_entries(account_id)
        """)

        # Commit transaction
        conn.commit()

        # Re-enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON")

        # Verify migration
        cursor = conn.execute("SELECT COUNT(*) as count FROM journal_entries")
        new_count = cursor.fetchone()["count"]

        if new_count != count:
            raise Exception(
                f"Migration failed: row count mismatch ({count} -> {new_count})"
            )

        print(f"✓ Migration completed successfully!")
        print(f"  Migrated {new_count} journal entries")

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    """Main entry point."""
    # Default database path
    default_db = Path(__file__).parent.parent / "data" / "yuuka.db"

    # Allow custom path as command line argument
    db_path = sys.argv[1] if len(sys.argv) > 1 else str(default_db)

    if not Path(db_path).exists():
        print(f"✗ Database not found: {db_path}")
        print(f"\nUsage: python -m yuuka.migrate_journal_entries [db_path]")
        print(f"  Default: {default_db}")
        sys.exit(1)

    print("=" * 60)
    print("Journal Entries Foreign Key Migration")
    print("=" * 60)
    print()

    # Create backup
    backup_path = f"{db_path}.backup"
    print(f"Creating backup: {backup_path}")

    import shutil

    shutil.copy2(db_path, backup_path)
    print(f"✓ Backup created")
    print()

    try:
        migrate_journal_entries(db_path)
        print()
        print("=" * 60)
        print("Migration completed successfully! ✓")
        print(f"Backup saved at: {backup_path}")
        print("=" * 60)
    except Exception as e:
        print()
        print("=" * 60)
        print("Migration failed! ✗")
        print(f"Error: {e}")
        print(f"Your original database is backed up at: {backup_path}")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()

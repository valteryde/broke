import os
import sys

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 005 Add parent_ticket_id to Ticket")

    rows = db.execute_sql("PRAGMA table_info(ticket);").fetchall()
    columns = [row[1] for row in rows]

    if "parent_ticket_id" in columns:
        print("Column 'parent_ticket_id' already exists on ticket table.")
        return

    db.execute_sql("ALTER TABLE ticket ADD COLUMN parent_ticket_id TEXT;")
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS ticket_parent_ticket_id ON ticket(parent_ticket_id);"
    )
    print("Successfully added 'parent_ticket_id' column to ticket table.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 021 Ticket time estimates")

    rows = db.execute_sql("PRAGMA table_info(ticket);").fetchall()
    columns = [row[1] for row in rows]
    if columns and "estimate_minutes" not in columns:
        db.execute_sql("ALTER TABLE ticket ADD COLUMN estimate_minutes INTEGER;")
        print("Added estimate_minutes to ticket table.")
    else:
        print("Column estimate_minutes already exists on ticket table (or ticket table missing).")

    print("Migration 021 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

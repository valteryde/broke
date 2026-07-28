import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 013 Error group event_meta for Sentry truncation annotations")

    rows = db.execute_sql("PRAGMA table_info(errorgroup);").fetchall()
    columns = [row[1] for row in rows]

    if "event_meta" not in columns:
        db.execute_sql("ALTER TABLE errorgroup ADD COLUMN event_meta TEXT;")
        print("Added event_meta column to errorgroup table.")
    else:
        print("Column event_meta already exists on errorgroup table.")

    print("Migration 013 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

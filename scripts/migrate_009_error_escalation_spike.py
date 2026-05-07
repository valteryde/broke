import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 009 Error group escalation spike email timestamp")

    rows = db.execute_sql("PRAGMA table_info(errorgroup);").fetchall()
    columns = [row[1] for row in rows]

    if "last_escalation_spike_email_at" not in columns:
        db.execute_sql(
            "ALTER TABLE errorgroup ADD COLUMN last_escalation_spike_email_at INTEGER;"
        )
        print("Added last_escalation_spike_email_at column to errorgroup table.")
    else:
        print("Column last_escalation_spike_email_at already exists on errorgroup table.")

    print("Migration 009 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 020 Meetings")

    db.execute_sql("""
        CREATE TABLE IF NOT EXISTS meeting (
            id INTEGER NOT NULL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            notes TEXT NOT NULL,
            created_by VARCHAR(255) NOT NULL,
            status VARCHAR(255) NOT NULL,
            result_json TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            done_at INTEGER
        );
        """)

    rows = db.execute_sql("PRAGMA table_info(ticket);").fetchall()
    columns = [row[1] for row in rows]
    if columns and "meeting_id" not in columns:
        db.execute_sql("ALTER TABLE ticket ADD COLUMN meeting_id INTEGER;")
        db.execute_sql("CREATE INDEX IF NOT EXISTS ticket_meeting_id ON ticket(meeting_id);")
        print("Added meeting_id to ticket table.")
    else:
        print("Column meeting_id already exists on ticket table (or ticket table missing).")

    print("Migration 020 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

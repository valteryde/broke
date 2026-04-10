import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 006 Work cycles")

    db.execute_sql(
        """
        CREATE TABLE IF NOT EXISTS workcycle (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            goal TEXT,
            project VARCHAR(255),
            starts_at INTEGER,
            ends_at INTEGER,
            created_at INTEGER NOT NULL
        );
        """
    )
    db.execute_sql("CREATE INDEX IF NOT EXISTS workcycle_project ON workcycle(project);")

    rows = db.execute_sql("PRAGMA table_info(ticket);").fetchall()
    columns = [row[1] for row in rows]

    if "work_cycle_id" not in columns:
        db.execute_sql("ALTER TABLE ticket ADD COLUMN work_cycle_id INTEGER;")
        db.execute_sql("CREATE INDEX IF NOT EXISTS ticket_work_cycle_id ON ticket(work_cycle_id);")
        print("Added work_cycle_id to ticket table.")
    else:
        print("Column work_cycle_id already exists on ticket table.")

    print("Migration 006 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

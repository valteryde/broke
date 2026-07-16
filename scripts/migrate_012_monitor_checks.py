import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 012 Monitor checks")

    db.execute_sql(
        """
        CREATE TABLE IF NOT EXISTS monitorcheck (
            id INTEGER NOT NULL PRIMARY KEY,
            monitor_id INTEGER NOT NULL,
            checked_at INTEGER NOT NULL,
            ok INTEGER NOT NULL,
            status_code INTEGER,
            response_ms INTEGER,
            error TEXT,
            FOREIGN KEY (monitor_id) REFERENCES monitor (id) ON DELETE CASCADE
        );
        """
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS monitorcheck_checked_at ON monitorcheck(checked_at);"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS monitorcheck_monitor_id_checked_at "
        "ON monitorcheck(monitor_id, checked_at);"
    )

    rows = db.execute_sql("PRAGMA table_info(monitor);").fetchall()
    columns = [row[1] for row in rows]
    if columns and "last_response_ms" not in columns:
        db.execute_sql("ALTER TABLE monitor ADD COLUMN last_response_ms INTEGER;")
        print("Added last_response_ms to monitor table.")
    else:
        print("Column last_response_ms already present or monitor table missing.")

    print("Migration 012 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

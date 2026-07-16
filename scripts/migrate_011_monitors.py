import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 011 Monitors")

    db.execute_sql(
        """
        CREATE TABLE IF NOT EXISTS monitor (
            id INTEGER NOT NULL PRIMARY KEY,
            project_id VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            url VARCHAR(255) NOT NULL,
            interval_seconds INTEGER NOT NULL,
            timeout_seconds INTEGER NOT NULL,
            expected_status INTEGER NOT NULL,
            enabled INTEGER NOT NULL,
            status VARCHAR(255) NOT NULL,
            last_checked_at INTEGER,
            last_status_change_at INTEGER,
            last_error TEXT,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (project_id) REFERENCES project (id)
        );
        """
    )
    db.execute_sql("CREATE INDEX IF NOT EXISTS monitor_project_id ON monitor(project_id);")
    db.execute_sql("CREATE INDEX IF NOT EXISTS monitor_enabled ON monitor(enabled);")

    print("Migration 011 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 014 Metrics (Telegraf) tokens and hosts")

    db.execute_sql("""
        CREATE TABLE IF NOT EXISTS metricstoken (
            id INTEGER NOT NULL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            token_hash VARCHAR(255) NOT NULL,
            token_preview VARCHAR(255) NOT NULL,
            created_at INTEGER NOT NULL,
            last_used INTEGER
        );
        """)
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS metricstoken_token_hash ON metricstoken(token_hash);"
    )

    db.execute_sql("""
        CREATE TABLE IF NOT EXISTS metricshost (
            id INTEGER NOT NULL PRIMARY KEY,
            hostname VARCHAR(255) NOT NULL,
            first_seen INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,
            series_count INTEGER NOT NULL
        );
        """)
    db.execute_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS metricshost_hostname ON metricshost(hostname);"
    )
    db.execute_sql("CREATE INDEX IF NOT EXISTS metricshost_last_seen ON metricshost(last_seen);")

    print("Migration 014 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

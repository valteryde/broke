import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 019 Usage site token")

    db.execute_sql("""
        CREATE TABLE IF NOT EXISTS usagetoken (
            id INTEGER NOT NULL PRIMARY KEY,
            token_hash VARCHAR(255) NOT NULL,
            token_preview VARCHAR(255) NOT NULL,
            created_at INTEGER NOT NULL,
            last_used INTEGER
        );
        """)
    db.execute_sql("CREATE INDEX IF NOT EXISTS usagetoken_token_hash ON usagetoken(token_hash);")

    print("Migration 019 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

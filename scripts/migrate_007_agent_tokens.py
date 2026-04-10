import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 007 Agent tokens")

    db.execute_sql(
        """
        CREATE TABLE IF NOT EXISTS agenttoken (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id VARCHAR(255) NOT NULL REFERENCES user (username),
            token_hash VARCHAR(255) NOT NULL,
            token_preview VARCHAR(255) NOT NULL,
            expires_at INTEGER NOT NULL,
            scopes TEXT NOT NULL,
            project VARCHAR(255),
            work_cycle_id INTEGER,
            created_at INTEGER NOT NULL
        );
        """
    )
    db.execute_sql("CREATE INDEX IF NOT EXISTS agenttoken_token_hash ON agenttoken(token_hash);")
    db.execute_sql("CREATE INDEX IF NOT EXISTS agenttoken_expires_at ON agenttoken(expires_at);")
    db.execute_sql("CREATE INDEX IF NOT EXISTS agenttoken_project ON agenttoken(project);")
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS agenttoken_work_cycle_id ON agenttoken(work_cycle_id);"
    )
    print("Migration 007 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

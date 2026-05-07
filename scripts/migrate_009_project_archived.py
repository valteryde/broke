import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 009 Project archived flag")

    rows = db.execute_sql("PRAGMA table_info(project);").fetchall()
    columns = [row[1] for row in rows]

    if "archived" not in columns:
        db.execute_sql("ALTER TABLE project ADD COLUMN archived INTEGER DEFAULT 0;")
        print("Added archived column to project table.")
    else:
        print("Column archived already exists on project table.")

    print("Migration 009 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

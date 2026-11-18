import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import AnonContact, AnonDraft, database as db


def run_migration():
    print("Running migration: 023 Anonymous intake drafts")
    AnonDraft.create_table(safe=True)
    AnonContact.create_table(safe=True)

    rows = db.execute_sql("PRAGMA table_info(ticketupdatemessage);").fetchall()
    columns = [row[1] for row in rows]
    if columns and "public" not in columns:
        db.execute_sql(
            "ALTER TABLE ticketupdatemessage ADD COLUMN public INTEGER NOT NULL DEFAULT 0;"
        )
        print("Added public to ticketupdatemessage.")
    else:
        print("Column public already exists on ticketupdatemessage (or table missing).")
    print("Migration 023 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

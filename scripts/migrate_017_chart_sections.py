import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db

# A section is carried on the charts inside it rather than in a table of its own, so
# adding one is two columns. Empty defaults describe exactly what a board meant before
# this migration: one ungrouped run of charts, which is still how it renders.
NEW_COLUMNS = (
    ("section", "VARCHAR(255) NOT NULL DEFAULT ''"),
    ("section_accent", "VARCHAR(32) NOT NULL DEFAULT ''"),
)


def run_migration():
    print("Running migration: 017 Chart sections (named, coloured groups on a board)")

    rows = db.execute_sql("PRAGMA table_info(metricschart);").fetchall()
    if not rows:
        print("No metricschart table yet; migration 015 will create it with these columns.")
        return

    columns = [row[1] for row in rows]
    for name, definition in NEW_COLUMNS:
        if name in columns:
            print(f"Column {name} already exists on metricschart table.")
            continue
        db.execute_sql(f"ALTER TABLE metricschart ADD COLUMN {name} {definition};")
        print(f"Added {name} column to metricschart table.")

    print("Migration 017 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

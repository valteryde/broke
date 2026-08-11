import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db

# Defaults describe exactly what a board row meant before this migration: a single series,
# plotted as stored, addressed by an exact tag set. Existing boards therefore keep drawing
# what they drew, and only charts saved from now on can be families.
NEW_COLUMNS = (
    ("kind", "VARCHAR(32) NOT NULL DEFAULT 'gauge'"),
    ("transform", "VARCHAR(32) NOT NULL DEFAULT 'raw'"),
    ("tag_mode", "VARCHAR(16) NOT NULL DEFAULT 'exact'"),
    ("options", "TEXT NOT NULL DEFAULT '{}'"),
)


def run_migration():
    print("Running migration: 016 Chart families (histograms, summaries, counter rates)")

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

    # The old index made a series unique per host, which would now stop one series being
    # both a chart of its own and part of a family read a different way. It arrives under
    # two names depending on whether the table came from migration 015 or from Peewee's
    # create_tables, so drop it by shape rather than by name.
    stale = ("hostname", "measurement", "field", "tags")
    for index in db.execute_sql("PRAGMA index_list(metricschart);").fetchall():
        name, unique = index[1], index[2]
        if not unique:
            continue
        columns = tuple(
            row[2] for row in db.execute_sql(f"PRAGMA index_info({name});").fetchall()
        )
        if columns == stale:
            db.execute_sql(f"DROP INDEX IF EXISTS {name};")
            print(f"Dropped stale unique index {name}.")

    db.execute_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS metricschart_hostname_measurement_field_tags_kind"
        " ON metricschart(hostname, measurement, field, tags, kind);"
    )

    print("Migration 016 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

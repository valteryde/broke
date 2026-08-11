import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db

# The unique index migration 016 puts on a board: one row per series per host.
INDEX = "metricschart_hostname_measurement_field_tags_kind"
KEY = "hostname, measurement, field, tags, kind"


def run_migration():
    """Rebuild the board's unique index from the rows it is supposed to describe.

    Installs have been found where ``PRAGMA integrity_check`` reports rows missing from this
    index. The table itself is intact, but SQLite has to update the index on every write, so
    while it is in that state a board cannot be saved and cannot even be cleared — both
    fail on ``DELETE`` with "database disk image is malformed", which reads to the operator
    as a bare 500 from the editor. Reads do not use the index, so the page renders normally
    and nothing looks wrong until someone tries to change a chart.

    Rebuilding rather than reindexing is deliberate: nothing here reads the existing index,
    so it does not matter how damaged it is.
    """
    print("Running migration: 018 Rebuild the metricschart unique index")

    if not db.execute_sql("PRAGMA table_info(metricschart);").fetchall():
        print("No metricschart table yet; migration 015 will create it.")
        return

    try:
        db.execute_sql(f"DROP INDEX IF EXISTS {INDEX};")

        before = db.execute_sql("SELECT count(*) FROM metricschart;").fetchone()[0]
        # Duplicates have to go before the index comes back, or creating it fails on the
        # second copy. With the index dropped a duplicate is just a row, so it can be
        # deleted — which is not true while the index is there and broken. A board holds a
        # series once and is replaced wholesale on save, so the extra copies are noise.
        db.execute_sql(
            "DELETE FROM metricschart WHERE id NOT IN"
            f" (SELECT MIN(id) FROM metricschart GROUP BY {KEY});"
        )
        removed = before - db.execute_sql("SELECT count(*) FROM metricschart;").fetchone()[0]
        if removed:
            print(f"Removed {removed} duplicate chart row(s).")

        db.execute_sql(f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON metricschart({KEY});")
        print("Rebuilt the metricschart unique index.")
    except Exception as exc:  # noqa: BLE001
        # This runs on every boot, on every install. A server that starts with a board
        # nobody can edit is a better outcome than a fleet that will not start at all, so
        # say what happened and let the rest of the migrations run.
        print(f"WARNING: could not rebuild the metricschart index: {exc}")
        print("WARNING: damage outside this index needs 'sqlite3 app.db .recover'.")
        return

    try:
        result = db.execute_sql("PRAGMA integrity_check(metricschart);").fetchone()
        print(f"metricschart integrity: {result[0] if result else 'unknown'}")
    except Exception as exc:  # noqa: BLE001
        # Table-scoped integrity_check wants a newer SQLite than some hosts ship.
        print(f"Skipped the integrity check: {exc}")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

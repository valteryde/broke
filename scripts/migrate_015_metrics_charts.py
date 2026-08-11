import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 015 Metrics chart boards")

    db.execute_sql(
        """
        CREATE TABLE IF NOT EXISTS metricschart (
            id INTEGER NOT NULL PRIMARY KEY,
            hostname VARCHAR(255) NOT NULL,
            measurement VARCHAR(255) NOT NULL,
            field VARCHAR(255) NOT NULL,
            tags TEXT NOT NULL,
            position INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        """
    )
    db.execute_sql("CREATE INDEX IF NOT EXISTS metricschart_hostname ON metricschart(hostname);")
    # One row per series per host: adding a chart twice is a no-op, not a duplicate panel.
    db.execute_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS metricschart_series"
        " ON metricschart(hostname, measurement, field, tags);"
    )

    print("Migration 015 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

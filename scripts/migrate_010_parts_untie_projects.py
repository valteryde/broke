import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db


def run_migration():
    print("Running migration: 010 Untie project parts from ticket projects")

    rows = db.execute_sql("PRAGMA table_info(projectpart);").fetchall()
    columns = [row[1] for row in rows]

    if not columns:
        print("Table projectpart does not exist yet; skipping.")
        return

    if "project_id" not in columns:
        print("Column project_id already removed from projectpart.")
        return

    duplicates = db.execute_sql(
        "SELECT name, COUNT(*) AS c FROM projectpart GROUP BY name HAVING c > 1"
    ).fetchall()
    if duplicates:
        names = ", ".join(f"{name} ({count})" for name, count in duplicates)
        raise RuntimeError(
            "Cannot untie parts from projects: duplicate part names across projects: "
            f"{names}. Rename colliding parts, then re-run migrations."
        )

    db.execute_sql("PRAGMA foreign_keys=OFF")
    try:
        with db.atomic():
            db.execute_sql(
                """
                CREATE TABLE projectpart_new (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL,
                    description VARCHAR(255) NOT NULL
                )
                """
            )
            db.execute_sql(
                """
                INSERT INTO projectpart_new (id, name, description)
                SELECT id, name, description FROM projectpart
                """
            )
            db.execute_sql("DROP TABLE projectpart")
            db.execute_sql("ALTER TABLE projectpart_new RENAME TO projectpart")
            db.execute_sql("CREATE UNIQUE INDEX IF NOT EXISTS projectpart_name ON projectpart (name)")
    finally:
        db.execute_sql("PRAGMA foreign_keys=ON")

    print("Migration 010 completed.")


if __name__ == "__main__":
    db.connect(reuse_if_open=True)
    run_migration()
    if not db.is_closed():
        db.close()

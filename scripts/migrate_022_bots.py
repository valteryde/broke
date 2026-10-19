import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import _ensure_user_bot_columns
from app.utils.models import database as db


def run_migration():
    print("Running migration: 022 Bot users")
    db.connect(reuse_if_open=True)
    _ensure_user_bot_columns()
    print("Migration 022 completed.")


if __name__ == "__main__":
    run_migration()
    if not db.is_closed():
        db.close()

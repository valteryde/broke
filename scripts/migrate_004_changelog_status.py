import os
import sys

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.utils.models import database as db, ChangelogRelease
from playhouse.migrate import SqliteMigrator, migrate
from peewee import CharField

def run_migration():
    print("Running migration: 004 Add Status to ChangelogRelease")
    
    migrator = SqliteMigrator(db)
    
    try:
        # Add the status column, defaulting to 'draft'
        status_field = CharField(default="draft")
        migrate(
            migrator.add_column("changelogrelease", "status", status_field)
        )
        print("Successfully added 'status' column to ChangelogRelease table.")
    except Exception as e:
        print(f"Error during migration: {e}")
        # Note: if column already exists, it will throw OperationalError which is fine to ignore if re-running

if __name__ == "__main__":
    db.connect()
    run_migration()
    db.close()

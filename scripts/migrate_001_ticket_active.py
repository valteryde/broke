
from peewee import SqliteDatabase
from playhouse.migrate import migrate, SqliteMigrator, IntegerField
import sys
import os

# Add parent directory to path to import utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.utils.models import Ticket, database

def run_migration():
    print("Running migration: Adding active column to Ticket table...")
    
    migrator = SqliteMigrator(database)
    
    active_field = IntegerField(default=1)
    
    try:
        with database.transaction():
            migrate(
                migrator.add_column('ticket', 'active', active_field)
            )
        print("Migration successful!")
    except Exception as e:
        if "duplicate column name" in str(e).lower():
            print("Column 'active' already exists. Skipping.")
        else:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    run_migration()

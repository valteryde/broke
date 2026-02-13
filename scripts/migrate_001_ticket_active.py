
from playhouse.migrate import migrate, SqliteMigrator, IntegerField
import sys
import os
import logging

# Add parent directory to path to import utils
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.models import database

def run_migration():
    logging.info("Running migration: Adding active column to Ticket table...")

    migrator = SqliteMigrator(database)
    
    active_field = IntegerField(default=1)
    
    try:
        with database.transaction():
            migrate(
                migrator.add_column('ticket', 'active', active_field)
            )
        logging.info("Migration successful!")
    except Exception as e:
        if "duplicate column name" in str(e).lower():
            logging.info("Column 'active' already exists. Skipping.")
        else:
            logging.error(f"Migration failed: {e}")
            raise e

if __name__ == "__main__":
    run_migration()

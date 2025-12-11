
from peewee import SqliteDatabase
from playhouse.migrate import SqliteMigrator, migrate 
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.models import Ticket, database, CharField, GlobalSetting

def run_migration():
    print("Running migration 002: Add anonymous_secret to Ticket")
    migrator = SqliteMigrator(database)

    # Check if column exists first to avoid errors if re-run
    cursor = database.cursor()
    cursor.execute("PRAGMA table_info(ticket)")
    columns = [info[1] for info in cursor.fetchall()]

    if 'anonymous_secret' not in columns:
        print("Adding anonymous_secret column...")
        # Define the field exactly as in the model
        secret_field = CharField(null=True, unique=True)
        
        migrate(
            migrator.add_column('ticket', 'anonymous_secret', secret_field)
        )
        print("Column added.")
    else:
        print("Column anonymous_secret already exists.")

    # Ensure global settings are updated if needed
    GlobalSetting.create_table(safe=True)

if __name__ == '__main__':
    run_migration()

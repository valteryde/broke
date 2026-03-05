import os
import sys

# Add parent directory to path to allow importing app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.models import database, ChangelogRelease

def migrate():
    print("Starting migration: 003_changelog_refactor")
    
    tables = database.get_tables()
    
    if "changelogentry" in tables:
        print("Dropping ChangelogEntry table...")
        database.execute_sql("DROP TABLE changelogentry")
    
    if "changelogrelease" in tables:
        print("Recreating ChangelogRelease table...")
        database.execute_sql("DROP TABLE changelogrelease")
        
    database.create_tables([ChangelogRelease], safe=True)
    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()

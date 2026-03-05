import os
import sys

# Add parent directory to path to allow importing app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.models import database, ChangelogRelease, ChangelogEntry

def migrate():
    print("Starting migration: 002_changelog_models")
    
    # Check if models already exist
    tables = database.get_tables()
    
    if "changelogrelease" not in tables:
        print("Creating ChangelogRelease table...")
        database.create_tables([ChangelogRelease], safe=True)
    else:
        print("ChangelogRelease table already exists.")
        
    if "changelogentry" not in tables:
        print("Creating ChangelogEntry table...")
        database.create_tables([ChangelogEntry], safe=True)
    else:
        print("ChangelogEntry table already exists.")
        
    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()

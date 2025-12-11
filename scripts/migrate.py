
import sys
import os

# Add parent directory to path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.migrate_001_ticket_active import run_migration as run_migration_001
from scripts.migrate_002_anon import run_migration as run_migration_002

if __name__ == '__main__':
    run_migration_001()
    run_migration_002()

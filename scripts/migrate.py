import os
import sys

# Add parent directory to path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.migrate_001_ticket_active import run_migration as run_migration_001
from scripts.migrate_002_anon import run_migration as run_migration_002
from scripts.migrate_005_ticket_parent import run_migration as run_migration_005
from scripts.migrate_006_work_cycles import run_migration as run_migration_006
from scripts.migrate_007_agent_tokens import run_migration as run_migration_007
from scripts.migrate_008_project_settings import run_migration as run_migration_008

if __name__ == "__main__":
    run_migration_001()
    run_migration_002()
    run_migration_005()
    run_migration_006()
    run_migration_007()
    run_migration_008()

import os
import sys

# Add parent directory to path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from app.utils.models import initialize_db
from scripts.migrate_001_ticket_active import run_migration as run_migration_001
from scripts.migrate_002_anon import run_migration as run_migration_002
from scripts.migrate_005_ticket_parent import run_migration as run_migration_005
from scripts.migrate_006_work_cycles import run_migration as run_migration_006
from scripts.migrate_007_agent_tokens import run_migration as run_migration_007
from scripts.migrate_008_project_settings import run_migration as run_migration_008
from scripts.migrate_009_error_escalation_spike import run_migration as run_migration_009
from scripts.migrate_010_parts_untie_projects import run_migration as run_migration_010
from scripts.migrate_011_monitors import run_migration as run_migration_011
from scripts.migrate_012_monitor_checks import run_migration as run_migration_012
from scripts.migrate_013_error_event_meta import run_migration as run_migration_013
from scripts.migrate_014_metrics import run_migration as run_migration_014
from scripts.migrate_015_metrics_charts import run_migration as run_migration_015
from scripts.migrate_016_chart_families import run_migration as run_migration_016
from scripts.migrate_017_chart_sections import run_migration as run_migration_017
from scripts.migrate_018_repair_chart_index import run_migration as run_migration_018
from scripts.migrate_019_usage import run_migration as run_migration_019
from scripts.migrate_020_meetings import run_migration as run_migration_020
from scripts.migrate_021_ticket_estimate import run_migration as run_migration_021

if __name__ == "__main__":
    # Docker entrypoint runs migrations before the app boots; create_tables only
    # happened inside create_app() otherwise, so a fresh volume had no tables yet.
    initialize_db()
    run_migration_001()
    run_migration_002()
    run_migration_005()
    run_migration_006()
    run_migration_007()
    run_migration_008()
    run_migration_009()
    run_migration_010()
    run_migration_011()
    run_migration_012()
    run_migration_013()
    run_migration_014()
    run_migration_015()
    run_migration_016()
    run_migration_017()
    run_migration_018()
    run_migration_019()
    run_migration_020()
    run_migration_021()

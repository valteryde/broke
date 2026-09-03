from .agent import agent_bp
from .anon import anon_bp
from .auth import auth_bp
from .bug import bug_bp
from .changelog import changelog_bp
from .desktop import desktop_bp
from .meetings import meetings_bp
from .metrics import metrics_bp
from .monitors import monitors_bp
from .news import news_bp
from .settings import settings_bp
from .status_page import status_bp
from .tickets import tickets_bp
from .usage import usage_bp
from .webhooks import webhooks_bp
from .work_cycles import work_cycles_bp

__all__ = [
    "tickets_bp",
    "usage_bp",
    "bug_bp",
    "settings_bp",
    "news_bp",
    "webhooks_bp",
    "auth_bp",
    "anon_bp",
    "changelog_bp",
    "desktop_bp",
    "work_cycles_bp",
    "meetings_bp",
    "agent_bp",
    "monitors_bp",
    "metrics_bp",
    "status_bp",
]

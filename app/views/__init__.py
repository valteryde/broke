from .tickets import tickets_bp
from .bug import bug_bp
from .settings import settings_bp
from .news import news_bp
from .webhooks import webhooks_bp
from .auth import auth_bp
from .anon import anon_bp

__all__ = ['tickets_bp', 'bug_bp', 'settings_bp', 'news_bp', 'webhooks_bp', 'auth_bp', 'anon_bp']

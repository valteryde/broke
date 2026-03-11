import flask
from datetime import datetime
from .path import path
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
import tomllib
import os
import secrets
from .path import data_path

# Global app instance (for backwards compatibility during migration)
_app = None
limiter = None
cache = None


def get_app():
    """Get the current Flask app instance"""
    return _app


def get_app_version_from_toml():
    """Reads the [project] version from pyproject.toml."""
    # Find the pyproject.toml file relative to the script location
    toml_path = path("..", "pyproject.toml")

    if not toml_path.exists():
        return "Version File Not Found"

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
            # Access the version key under the [project] table
            return data.get("project", {}).get("version", "Unknown Version (No Project Table)")
    except Exception as e:
        # Handle potential parsing errors
        print(f"Error reading pyproject.toml: {e}")
        return "Parsing Error"


def get_app_codename_from_toml():
    """Reads the [tool.broke] codename from pyproject.toml."""
    # Find the pyproject.toml file relative to the script location
    toml_path = path("..", "pyproject.toml")

    if not toml_path.exists():
        return "Codename File Not Found"

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
            # Access the codename key under the [tool.broke] table
            return (
                data.get("tool", {})
                .get("broke", {})
                .get("codename", "Unknown Codename (No Tool Table)")
            )
    except Exception as e:
        # Handle potential parsing errors
        print(f"Error reading pyproject.toml: {e}")
        return "Parsing Error"


def _persistent_fallback_secret_key() -> str:
    secret_path = data_path("flask-secret-key.txt")
    secret_path.parent.mkdir(parents=True, exist_ok=True)

    if secret_path.exists():
        existing = secret_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    generated = secrets.token_urlsafe(64)
    secret_path.write_text(generated, encoding="utf-8")
    return generated


def create_app():  # noqa: C901
    """
    Application factory function for creating Flask app instances.

    Args:
        config: Optional configuration dictionary or object

    Returns:
        Configured Flask application instance
    """
    global _app
    # Initialize database tables on app creation (but not during tests)
    if os.environ.get("FLASK_ENV") != "testing":
        from .models import initialize_db
        initialize_db()

    app = flask.Flask("Broke")

    # Secret key precedence: BROKE_SECRET_KEY -> FLASK_SECRET_KEY -> persisted local key.
    secret_key = (
        os.environ.get("BROKE_SECRET_KEY")
        or os.environ.get("FLASK_SECRET_KEY")
        or _persistent_fallback_secret_key()
    )
    app.secret_key = secret_key

    # Harden session cookie defaults while allowing secure cookies behind TLS deployments.
    session_cookie_secure = str(os.environ.get("BROKE_SESSION_COOKIE_SECURE", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=session_cookie_secure,
    )

    app.template_folder = path("templates")
    app.static_folder = path("static")

    # Register template filters
    @app.template_filter("timestamp_to_date")
    def timestamp_to_date(epoch):
        """Convert epoch timestamp to readable date string"""
        if not epoch:
            return ""
        try:
            dt = datetime.fromtimestamp(int(epoch))
            return dt.strftime("%b %d, %Y")
        except (ValueError, TypeError):
            return str(epoch)

    APP_VERSION = get_app_version_from_toml()
    APP_CODENAME = get_app_codename_from_toml()

    @app.template_global()
    def app_version():
        return APP_VERSION

    @app.template_global()
    def app_codename():
        return APP_CODENAME

    @app.template_global()
    def current_year():
        """Get the current year"""
        return datetime.now().year

    print(f"App Version: {APP_VERSION} {APP_CODENAME}")

    # Register error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return (
            flask.render_template(
                "error_message.jinja2", error_code=404, error_message="Page not found"
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_error(error):
        return (
            flask.render_template(
                "error_message.jinja2", error_code=500, error_message="Internal server error"
            ),
            500,
        )

    @app.errorhandler(403)
    def forbidden_error(error):
        return (
            flask.render_template(
                "error_message.jinja2", error_code=403, error_message="Forbidden"
            ),
            403,
        )

    @app.errorhandler(401)
    def unauthorized_error(error):
        return (
            flask.render_template(
                "error_message.jinja2", error_code=401, error_message="Unauthorized"
            ),
            401,
        )

    @app.errorhandler(400)
    def bad_request_error(error):
        return (
            flask.render_template(
                "error_message.jinja2", error_code=400, error_message="Bad request"
            ),
            400,
        )

    @app.errorhandler(429)
    def rate_limit_error(error):
        return (
            flask.render_template(
                "error_message.jinja2",
                error_code=429,
                error_message="Too many requests. Please try again later.",
            ),
            429,
        )

    @app.after_request
    def add_security_headers(response):
        # Keep CSP intentionally permissive for now because templates rely on inline assets.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https:; font-src 'self' data: https:; script-src 'self' 'unsafe-inline' 'unsafe-eval' https:",
        )
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    # Initialize Flask-Caching with Redis backend
    global cache, limiter

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    # Configure Flask-Caching with Redis
    cache_config = {
        "CACHE_TYPE": "RedisCache",
        "CACHE_REDIS_URL": redis_url,
        "CACHE_DEFAULT_TIMEOUT": 300,
    }

    app.config.from_mapping(cache_config)
    cache = Cache(app)

    # Initialize rate limiter using Redis storage
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        # default_limits=["2000 per day", "500 per hour"],
        storage_uri=redis_url,
    )

    # Sidebar Data Context Processor
    from .sidebar_data import get_sidebar_data

    @app.context_processor
    def inject_sidebar_news():
        # Cache key based on user if logged in, or global default
        # But context_processor runs before we might have 'current_user' easy access in some auth setups,
        # however flask_login or similar usually makes it available.
        # Here we assume 'g.user' or similar might be available if using our own auth.
        # Let's check how 'user' is passed to templates. It seems passed explicitly in views.
        # But we can try to get it from g or session if available.
        # For now, let's just use a simple caching strategy or no caching if user not easily accessible here without risk.
        # Wait, the views pass 'user' to render_template. Context processors add to that.
        # We can't easily access the 'user' variable being passed to render_template from within the context processor function itself
        # unless it's in g.user or session.

        # Let's try to fetch it safely.
        # Based on view files, 'user' object is passed explicitly.
        # We might need to make get_sidebar_data a helper available in template, rather than a variable.
        # That way we can pass 'user' to it from the template: {{ sidebar_news(user) }}

        @cache.memoize(timeout=60)
        def cached_sidebar_data(user_username):
            # We pass username to cache key, but need user object for logic.
            # Actually get_sidebar_data uses User models, but queries by user.
            # Let's re-retrieve user or just pass username if possible.
            # get_sidebar_data takes 'user' object.
            # Let's just wrapper it.
            from ..utils.models import User

            u = User.get_or_none(User.username == user_username)
            if u:
                return get_sidebar_data(u)
            return None

        def get_news(user):
            if not user or not hasattr(user, "username"):
                return None
            return cached_sidebar_data(user.username)

        return dict(sidebar_news=get_news)

    @app.context_processor
    def inject_csrf_token():
        from .security import get_csrf_token

        return {"csrf_token": get_csrf_token()}

    @app.context_processor
    def inject_client_runtime_flags():
        user_agent = str(flask.request.headers.get("User-Agent") or "")
        is_desktop_client = "BrokeDesktop/" in user_agent
        return {"is_desktop_client": is_desktop_client}

    # Register blueprints
    from ..views import tickets_bp, bug_bp, settings_bp, news_bp, webhooks_bp, auth_bp, anon_bp, changelog_bp, desktop_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(bug_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(anon_bp)
    app.register_blueprint(changelog_bp)
    app.register_blueprint(desktop_bp)

    # Initialize event subscriptions
    from . import mail  # noqa: F401
    from .notifications import initialize_notification_engine

    initialize_notification_engine()

    # Start background update checker
    if os.environ.get("FLASK_ENV") != "testing":
        from .updater import start_update_checker, get_update_info

        start_update_checker()

        @app.context_processor
        def inject_update_info():
            return {"update_info": get_update_info()}

    # Register core routes
    @app.route("/favicon.ico")
    def favicon():
        return app.send_static_file("images/favicon/favicon.ico")

    @app.route("/")
    def index():
        from flask import redirect

        return redirect("/news")

    # Store global reference
    _app = app

    # Add current_year to template context
    @app.context_processor
    def inject_current_year():
        return {"current_year": datetime.now().year}

    return app


# Legacy support: create default app instance
app = create_app()

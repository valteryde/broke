
import flask
from datetime import datetime
from .path import path
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
import tomllib

# Global app instance (for backwards compatibility during migration)
_app = None
limiter = None
cache = None

def get_app():
    """Get the current Flask app instance"""
    return _app

def get_limiter():
    """Get the current Limiter instance"""
    return limiter

def get_cache():
    """Get the current Cache instance"""
    return cache


def get_app_version_from_toml():
    """Reads the [project] version from pyproject.toml."""
    # Find the pyproject.toml file relative to the script location
    toml_path = path('..', 'pyproject.toml')

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
    toml_path = path('..', 'pyproject.toml')

    if not toml_path.exists():
        return "Codename File Not Found"

    try:
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
            # Access the codename key under the [tool.broke] table
            return data.get("tool", {}).get("broke", {}).get("codename", "Unknown Codename (No Tool Table)")
    except Exception as e:
        # Handle potential parsing errors
        print(f"Error reading pyproject.toml: {e}")
        return "Parsing Error"

def create_app(config=None):
    """
    Application factory function for creating Flask app instances.
    
    Args:
        config: Optional configuration dictionary or object
        
    Returns:
        Configured Flask application instance
    """
    global _app
    
    app = flask.Flask('Broke')
    app.secret_key = 'supersecretkey-i-swear-it-not-hardcoded-at-all-pls-dont-hack-me'
    app.template_folder = path('templates')
    app.static_folder = path('static')
    
    # Apply custom configuration if provided
    if config:
        if isinstance(config, dict):
            app.config.update(config)
        else:
            app.config.from_object(config)
    
    # Register template filters
    @app.template_filter('timestamp_to_date')
    def timestamp_to_date(epoch):
        """Convert epoch timestamp to readable date string"""
        if not epoch:
            return ''
        try:
            dt = datetime.fromtimestamp(int(epoch))
            return dt.strftime('%b %d, %Y')
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
        return flask.render_template('error_message.jinja2', error_code=404, error_message="Page not found"), 404

    @app.errorhandler(500)
    def internal_error(error):
        return flask.render_template('error_message.jinja2', error_code=500, error_message="Internal server error"), 500
    
    @app.errorhandler(403)
    def forbidden_error(error):
        return flask.render_template('error_message.jinja2', error_code=403, error_message="Forbidden"), 403
    
    @app.errorhandler(401)
    def unauthorized_error(error):
        return flask.render_template('error_message.jinja2', error_code=401, error_message="Unauthorized"), 401
    
    @app.errorhandler(400)
    def bad_request_error(error):
        return flask.render_template('error_message.jinja2', error_code=400, error_message="Bad request"), 400
    
    @app.errorhandler(429)
    def rate_limit_error(error):
        return flask.render_template('error_message.jinja2', error_code=429, error_message="Too many requests. Please try again later."), 429

    # Initialize Flask-Caching with Redis backend
    global cache, limiter
    import os

    redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379')

    # Configure Flask-Caching with Redis
    cache_config = {
        'CACHE_TYPE': 'RedisCache',
        'CACHE_REDIS_URL': redis_url,
        'CACHE_DEFAULT_TIMEOUT': 300
    }

    app.config.from_mapping(cache_config)
    cache = Cache(app)

    # Initialize rate limiter using Redis storage
    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        # default_limits=["2000 per day", "500 per hour"],
        storage_uri=redis_url
    )
    
    # Register blueprints
    from ..views import tickets_bp, bug_bp, settings_bp, news_bp, webhooks_bp, auth_bp, anon_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(bug_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(anon_bp)
    
    # Register core routes
    @app.route('/favicon.ico')
    def favicon():
        return app.send_static_file('images/favicon/favicon.ico')

    @app.route('/')
    def index():
        from flask import redirect
        return redirect('/news')
    
    # Store global reference
    _app = app
    
    return app


# Legacy support: create default app instance
app = None

def init_app():
    """Initialize the default app instance"""
    global app
    if app is None:
        app = create_app()
    return app

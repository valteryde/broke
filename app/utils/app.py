
import flask 
from datetime import datetime
from .path import path

# Global app instance (for backwards compatibility during migration)
_app = None

def get_app():
    """Get the current Flask app instance"""
    return _app


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
    
    # Register blueprints
    from ..views import tickets_bp, bug_bp, settings_bp, news_bp, webhooks_bp, auth_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(bug_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(webhooks_bp)
    
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

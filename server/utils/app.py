
import flask 
from datetime import datetime
from .path import path

app = flask.Flask('Broke')
app.secret_key = 'supersecretkey-i-swear-it-not-hardcoded-at-all-pls-dont-hack-me'
app.template_folder = path('templates')
app.static_folder = path('static')

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

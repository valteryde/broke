
import flask 
from .path import path

app = flask.Flask('Broke')
app.secret_key = 'supersecretkey-i-swear-it-not-hardcoded-at-all-pls-dont-hack-me'
app.template_folder = path('templates')
app.static_folder = path('static')

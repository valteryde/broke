"""
Authentication Blueprint
Handles login, logout, and callback routes
"""

from flask import Blueprint, render_template, request, redirect, session, flash
from app.utils.security import authenticate

# Create auth blueprint
auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET'])
def login():
    """Display login page"""
    next_url = request.args.get('next', '/news')
    return render_template('login.jinja2', next_url=next_url)


@auth_bp.route('/callback', methods=['POST'])
def callback():
    """Process login form submission"""
    username = request.form['username']
    password = request.form['password']

    # Authenticate user
    user = authenticate(username, password)
    if user:
        session['user_id'] = user.username
        next_url = request.args.get('next') or '/news'
        return redirect(next_url)
    else:
        flash('Invalid username or password', 'error')
        return redirect('/login')


@auth_bp.route('/logout')
def logout():
    """Log out the current user"""
    session.pop('user_id', None)
    return redirect('/login')

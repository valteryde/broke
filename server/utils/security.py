"""
Security utilities for the application.

Flow is simple 
- User accesses a protected route.
- If not authenticated, redirect to login.
- After login, redirect back to the originally requested route via callback.

"""


from flask import request, session, url_for, redirect
from utils.app import app
from .models import User
import pyargon2
from peewee import DoesNotExist


# Usage for the decorator could be like this:
# @secureroute('/protected')
# def protected_route(user: User):
#    return "This is a protected route."
# The decorator handles authentication and redirection.
def secureroute(route, methods=['GET']):
    def decorator(func):
        def wrapper(*args, **kwargs):
            user_id = session.get('user_id')
            login_url = url_for('login', next=request.path)
            if not user_id:
                # Not authenticated, redirect to login
                return redirect(login_url)
            # User is authenticated, proceed to the original function
            try:
                user:User = User.select().where(User.username == user_id).first()
                if not user:
                    raise DoesNotExist
            except DoesNotExist:
                # Invalid user in session, redirect to login
                return redirect(login_url)
            return func(user, *args, **kwargs)
        # Register the route with Flask
        app.route(route, methods=methods, endpoint=func.__name__)(wrapper)
        return wrapper
    return decorator


@app.route('/login', methods=['GET'])
def login():
    from flask import render_template
    next_url = request.args.get('next', '/news')
    return render_template('login.jinja2', next_url=next_url)

def authenticate(username, password) -> User | None:
    # Pseudo authentication function
    # In real application, verify username and password from database
    
    try:
        user:User = User.select().where(User.username == username).first()
        if not user:
            return None

        if user.password_hash == pyargon2.hash(password, str(user.salt)):
            return user
    except DoesNotExist:
        return None



@app.route('/callback', methods=['POST'])
def callback():
    from flask import flash
    
    # This route processes the login form submission
    username = request.form['username']
    password = request.form['password']
    # Authenticate user (pseudo code)
    user = authenticate(username, password)
    if user:
        session['user_id'] = user.username
        next_url = request.args.get('next') or '/news'
        return redirect(next_url)
    else:
        flash('Invalid username or password', 'error')
        return redirect('/login')
    



@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect('/login')


def get_current_user() -> User | None:
    """
    Get the currently authenticated user from the session.
    Returns None if no user is logged in.
    """
    user_id = session.get('user_id')
    if not user_id:
        return None
    
    try:
        user = User.select().where(User.username == user_id).first()
        return user
    except DoesNotExist:
        return None
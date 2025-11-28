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
def secureroute(route):
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
        app.route(route, endpoint=func.__name__)(wrapper)
        return wrapper
    return decorator


@app.route('/login', methods=['GET'])
def login():
    
    # Show login form
    return '''
        <form method="post" action="/callback?next={}">
            Username: <input type="text" name="username"><br>
            Password: <input type="password" name="password"><br>
            <input type="submit" value="Login">
        </form>
    '''.format(request.args.get('next', ''))

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
    
    # This route processes the login form submission
    username = request.form['username']
    password = request.form['password']
    # Authenticate user (pseudo code)
    user = authenticate(username, password)
    if user:
        session['user_id'] = user.username
        next_url = request.args.get('next') or url_for('index')
        return redirect(next_url)
    else:
        return "Invalid credentials", 401
    



@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return ''
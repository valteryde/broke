"""
Authentication Blueprint
Handles login, logout, and callback routes
"""

from flask import Blueprint, flash, redirect, render_template, request, session

from app.utils.security import authenticate, delete_csrf_cookie

# Create auth blueprint
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET"])
def login():
    """Display login page"""
    next_url = request.args.get("next", "/news")
    return render_template("login.jinja2", next_url=next_url)


@auth_bp.route("/callback", methods=["POST"])
def callback():
    """Process login form submission"""
    username = request.form["username"]
    password = request.form["password"]

    # Authenticate user
    user = authenticate(username, password)
    if user:
        session["user_id"] = user.username
        session.permanent = True
        next_url = request.args.get("next") or "/news"
        return redirect(next_url)
    else:
        flash("Invalid username or password", "error")
        return redirect("/login")


@auth_bp.route("/logout")
def logout():
    """Log out the current user"""
    session.pop("user_id", None)
    session.pop("_csrf_token", None)
    session.pop("_permanent", None)
    return delete_csrf_cookie(redirect("/login"))

"""
Authentication Blueprint
Handles login, logout, and callback routes
"""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.utils.security import (
    authenticate,
    delete_csrf_cookie,
    login_success_redirect_after_callback,
    sanitize_next_app_path,
)

# Create auth blueprint
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET"])
def login():
    """Display login page"""
    raw_next = request.args.get("next")
    next_url = sanitize_next_app_path(raw_next) or "/news"
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
        return login_success_redirect_after_callback(request.args.get("next"))
    else:
        flash("Invalid username or password", "error")
        return redirect(url_for("auth.login"))


@auth_bp.route("/logout")
def logout():
    """Log out the current user"""
    session.pop("user_id", None)
    session.pop("_csrf_token", None)
    session.pop("_permanent", None)
    return delete_csrf_cookie(redirect(url_for("auth.login")))

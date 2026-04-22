"""
Security utilities for the application.

Flow is simple
- User accesses a protected route.
- If not authenticated, redirect to login.
- After login, redirect back to the originally requested route via callback.

"""

import hmac
import secrets
from functools import wraps

import pyargon2
from flask import current_app, g, jsonify, redirect, request, session, url_for
from peewee import DoesNotExist

from .models import User

# CSRF lives in its own cookie so we never write _csrf_token into the signed session
# cookie (that caused extra re-signing, races with parallel requests, and empty sessions).
CSRF_COOKIE_NAME = "broke_csrf"

# Usage for the decorator could be like this:
# @secureroute('/protected')
# def protected_route(user: User):
#    return "This is a protected route."
# The decorator handles authentication and redirection.
# def secureroute(route=None, methods=['GET']):
#     """
#     Decorator for securing routes with authentication.
#     Can be used with or without blueprints.

#     Usage with blueprint:
#         @secureroute
#         def my_view(user: User):
#             pass

#     Usage with direct app (deprecated):
#         @secureroute('/route')
#         def my_view(user: User):
#             pass
#     """
#     def decorator(func):
#         @wraps(func)
#         def wrapper(*args, **kwargs):
#             user_id = session.get('user_id')
#             login_url = url_for('auth.login', next=request.path)
#             if not user_id:
#                 # Not authenticated, redirect to login
#                 return redirect(login_url)
#             # User is authenticated, proceed to the original function
#             try:
#                 user:User = User.select().where(User.username == user_id).first()
#                 if not user:
#                     raise DoesNotExist
#             except DoesNotExist:
#                 # Invalid user in session, redirect to login
#                 return redirect(login_url)
#             return func(user, *args, **kwargs)

#         # If route is provided, register with app directly (deprecated pattern)
#         if route is not None:
#             from .app import get_app
#             app = get_app()
#             if app:
#                 app.route(route, methods=methods, endpoint=func.__name__)(wrapper)

#         return wrapper

#     # Handle both @secureroute and @secureroute() usage
#     if callable(route):
#         # @secureroute (no parentheses)
#         func = route
#         route = None
#         return decorator(func)
#     else:
#         # @secureroute() or @secureroute('/route')
#         return decorator


def protected(func):
    """Decorator to protect routes with authentication."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            # JSON/fetch clients follow redirects and may treat the login HTML as a
            # successful response; return 401 so the body is predictable JSON.
            if request.path.startswith("/api/"):
                return jsonify({"error": "Not signed in"}), 401
            login_url = url_for("auth.login", next=request.path)
            return redirect(login_url)

        if not _csrf_valid_for_request():
            if request.path.startswith("/api/"):
                return jsonify({"error": "CSRF validation failed"}), 403
            return "CSRF validation failed", 403

        return func(user, *args, **kwargs)

    return wrapper


def get_csrf_token() -> str:
    """CSRF token for templates and X-CSRF-Token. Stored in ``broke_csrf`` cookie only."""
    if "_csrf_token_resolved" in g:
        return g._csrf_token_resolved

    # One-time migration off the signed session payload.
    if "_csrf_token" in session:
        session.pop("_csrf_token", None)

    existing = (request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
    if existing:
        g._csrf_token_resolved = existing
        return existing

    token = secrets.token_urlsafe(32)
    g._csrf_token_resolved = token
    g._csrf_cookie_needs_set = True
    return token


def delete_csrf_cookie(response):
    """Call on logout so stale CSRF values are not reused."""
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return response


def _request_method_needs_csrf() -> bool:
    return request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def _csrf_enabled() -> bool:
    # Keep compatibility with existing test configuration toggle.
    return bool(current_app.config.get("WTF_CSRF_ENABLED", True))


def _get_request_csrf_token() -> str:
    header_token = (request.headers.get("X-CSRF-Token") or "").strip()
    if header_token:
        return header_token

    form_token = (request.form.get("csrf_token") or "").strip()
    if form_token:
        return form_token

    data = request.get_json(silent=True)
    if isinstance(data, dict):
        json_token = str(data.get("csrf_token") or "").strip()
        if json_token:
            return json_token

    return ""


def _csrf_cookie_matches_request(cookie_token: str, request_token: str) -> bool:
    """Constant-time compare; mismatched lengths must not raise (would become a 500)."""
    if not cookie_token or not request_token or len(cookie_token) != len(request_token):
        return False
    return hmac.compare_digest(cookie_token, request_token)


def _csrf_same_site_bases() -> list[str]:
    """URL prefixes to treat as same-origin for CSRF fallback (Host / reverse-proxy aware)."""
    bases: list[str] = []
    seen: set[str] = set()

    def add(u: str) -> None:
        u = (u or "").strip().rstrip("/")
        if u and u not in seen:
            seen.add(u)
            bases.append(u)

    add(request.host_url.rstrip("/"))

    public = str(current_app.config.get("BROKE_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    add(public)

    if current_app.config.get("BROKE_TRUST_PROXY_HEADERS"):
        xf_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
        xf_host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
        if xf_proto in ("http", "https"):
            host = xf_host or (request.host or "").strip()
            if host:
                add(f"{xf_proto}://{host}".rstrip("/"))

    return bases


def _referer_matches_base(referer: str, base: str) -> bool:
    """True if referer is exactly base or a path under base (avoids https://evil.com spoofing base)."""
    if not referer or not base:
        return False
    return referer == base or referer.startswith(base + "/")


def _same_origin_request() -> bool:
    origin = (request.headers.get("Origin") or "").strip().rstrip("/")
    referer = (request.headers.get("Referer") or "").strip()

    for base in _csrf_same_site_bases():
        if origin and origin == base:
            return True
        if referer and _referer_matches_base(referer, base):
            return True
    return False


def _csrf_valid_for_request() -> bool:
    if not _request_method_needs_csrf():
        return True

    if not _csrf_enabled():
        return True

    cookie_token = (request.cookies.get(CSRF_COOKIE_NAME) or "").strip()
    request_token = _get_request_csrf_token()

    if _csrf_cookie_matches_request(cookie_token, request_token):
        return True

    # Compatibility fallback for existing browser forms/fetch calls.
    return _same_origin_request()


def init_auth_routes(app):
    """Initialize authentication routes on the app"""

    @app.route("/login", methods=["GET"])
    def login():
        from flask import render_template

        next_url = request.args.get("next", "/news")
        return render_template("login.jinja2", next_url=next_url)

    @app.route("/callback", methods=["POST"])
    def callback():
        from flask import flash

        # This route processes the login form submission
        username = request.form["username"]
        password = request.form["password"]
        # Authenticate user (pseudo code)
        user = authenticate(username, password)
        if user:
            session["user_id"] = user.username
            next_url = request.args.get("next") or "/news"
            return redirect(next_url)
        else:
            flash("Invalid username or password", "error")
            return redirect("/login")

    @app.route("/logout")
    def logout():
        session.pop("user_id", None)
        return redirect("/login")


def authenticate(username, password) -> User | None:
    """Authenticate user with username and password"""
    # Pseudo authentication function
    # In real application, verify username and password from database

    try:
        user: User = User.select().where(User.username == username).first()
        if not user:
            return None

        if user.password_hash == pyargon2.hash(password, str(user.salt)):
            return user
    except DoesNotExist:
        return None


def get_current_user() -> User | None:
    """
    Get the currently authenticated user from the session.
    Returns None if no user is logged in.
    """
    user_id = session.get("user_id")
    if not user_id:
        return None

    try:
        user = User.select().where(User.username == user_id).first()
        return user
    except DoesNotExist:
        return None

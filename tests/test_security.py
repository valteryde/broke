"""Tests for security utilities"""
from ward import test
from tests.fixtures import fake
import os


@test("create_user creates user with hashed password")
def _(f=fake):
    """Test user creation with password hashing"""
    from app.utils.models import create_user, User
    
    username = f.user_name()
    password = f.password()
    email = f.email()
    
    user = create_user(username, password, email)
    
    assert user.username == username
    assert user.email == email
    assert user.password_hash != password  # Should be hashed
    assert len(user.salt) > 0


@test("password verification works")
def _(f=fake):
    """Test password hashing and verification"""
    import pyargon2
    from app.utils.models import create_user
    
    username = f.user_name()
    password = "test_password_123"
    user = create_user(username, password, f.email())
    
    # Verify correct password
    assert pyargon2.hash(password, str(user.salt)) == user.password_hash
    
    # Verify incorrect password fails
    assert pyargon2.hash("wrong_password", str(user.salt)) != user.password_hash


@test("get_current_user returns None without session")
def _():
    """Test get_current_user without authentication"""
    from app.utils.security import get_current_user
    from flask import Flask
    
    app = Flask(__name__)
    app.secret_key = 'test'
    
    with app.test_request_context():
        user = get_current_user()
        assert user is None


@test("Users have unique usernames")
def _(f=fake):
    """Test username uniqueness constraint"""
    from app.utils.models import create_user, User
    from peewee import IntegrityError
    
    username = f.user_name()
    create_user(username, f.password(), f.email())
    
    # Try to create another user with same username
    try:
        create_user(username, f.password(), f.email())
        assert False, "Should have raised IntegrityError"
    except IntegrityError:
        pass  # Expected


@test("create_app uses BROKE_SECRET_KEY when configured")
def _():
    """App should honor explicit secret key configuration from environment."""
    from app.utils.app import create_app

    key = "test-secret-key-from-env"
    previous = os.environ.get("BROKE_SECRET_KEY")
    previous_env = os.environ.get("FLASK_ENV")
    os.environ["BROKE_SECRET_KEY"] = key
    os.environ["FLASK_ENV"] = "testing"

    try:
        app = create_app()
        assert app.secret_key == key
    finally:
        if previous is None:
            os.environ.pop("BROKE_SECRET_KEY", None)
        else:
            os.environ["BROKE_SECRET_KEY"] = previous
        if previous_env is None:
            os.environ.pop("FLASK_ENV", None)
        else:
            os.environ["FLASK_ENV"] = previous_env


@test("create_app hardens session cookie defaults")
def _():
    """Session cookie defaults should follow secure baseline settings."""
    from app.utils.app import create_app

    previous_env = os.environ.get("FLASK_ENV")
    os.environ["FLASK_ENV"] = "testing"

    try:
        app = create_app()
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
        assert app.config["SESSION_COOKIE_SECURE"] is False
    finally:
        if previous_env is None:
            os.environ.pop("FLASK_ENV", None)
        else:
            os.environ["FLASK_ENV"] = previous_env


@test("create_app enables secure session cookie when configured")
def _():
    """Session cookie secure flag should be configurable by environment."""
    from app.utils.app import create_app

    previous = os.environ.get("BROKE_SESSION_COOKIE_SECURE")
    previous_env = os.environ.get("FLASK_ENV")
    os.environ["BROKE_SESSION_COOKIE_SECURE"] = "true"
    os.environ["FLASK_ENV"] = "testing"

    try:
        app = create_app()
        assert app.config["SESSION_COOKIE_SECURE"] is True
    finally:
        if previous is None:
            os.environ.pop("BROKE_SESSION_COOKIE_SECURE", None)
        else:
            os.environ["BROKE_SESSION_COOKIE_SECURE"] = previous
        if previous_env is None:
            os.environ.pop("FLASK_ENV", None)
        else:
            os.environ["FLASK_ENV"] = previous_env


@test("create_app adds baseline security headers")
def _():
    """Security headers should be present on app responses by default."""
    from app.utils.app import create_app

    previous_env = os.environ.get("FLASK_ENV")
    os.environ["FLASK_ENV"] = "testing"

    try:
        app = create_app()
        with app.test_client() as client:
            response = client.get("/login")

        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert response.headers.get("Content-Security-Policy") is not None
    finally:
        if previous_env is None:
            os.environ.pop("FLASK_ENV", None)
        else:
            os.environ["FLASK_ENV"] = previous_env


@test("Users have unique emails")
def _(f=fake):
    """Test email uniqueness constraint"""
    from app.utils.models import create_user
    from peewee import IntegrityError
    
    email = f.email()
    create_user(f.user_name(), f.password(), email)
    
    # Try to create another user with same email
    try:
        create_user(f.user_name(), f.password(), email)
        assert False, "Should have raised IntegrityError"
    except IntegrityError:
        pass  # Expected

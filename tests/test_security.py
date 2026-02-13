"""Tests for security utilities"""
from ward import test
from tests.fixtures import fake


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

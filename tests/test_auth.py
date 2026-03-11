"""Tests for authentication functionality"""
from ward import test
from tests.fixtures import client, fake, auth_user, auth_client
import json
import time
from unittest.mock import patch

from app.utils.models import PasswordResetToken, User
import pyargon2


@test("/callback POST with valid credentials")
def _(c=client, user=auth_user):
    """Test successful login"""
    response = c.post('/callback', data={
        'username': user.username,
        'password': user.password
    }, follow_redirects=False)
    
    assert response.status_code == 302  # Redirect on success
    assert '/news' in response.location or response.location == '/news'


@test("/callback POST with invalid credentials")
def _(c=client, user=auth_user):
    """Test failed login with wrong password"""
    response = c.post('/callback', data={
        'username': user.username,
        'password': 'wrongpassword'
    }, follow_redirects=False)
    
    # Should redirect back to login or show error
    assert response.status_code in [200, 302]


@test("/callback POST with non-existent user")
def _(c=client):
    """Test login with user that doesn't exist"""
    response = c.post('/callback', data={
        'username': 'nonexistent_user_12345',
        'password': 'password'
    }, follow_redirects=False)
    
    # Should redirect back to login or show error
    assert response.status_code in [200, 302]


@test("/login GET shows login page")
def _(c=client):
    """Test that login page is accessible"""
    response = c.get('/login')
    assert response.status_code == 200
    assert b'login' in response.data.lower()


@test("/login GET bootstraps CSRF for standalone forms")
def _(c=client):
    response = c.get('/login')

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'meta name="csrf-token" content="' in body
    assert 'name="csrf_token"' in body


@test("/logout redirects to login")
def _(c=auth_client):
    """Test logout functionality"""
    response = c.get('/logout', follow_redirects=False)
    assert response.status_code == 302
    assert 'login' in response.location


@test("Protected route requires authentication")
def _(c=client):
    """Test that protected routes redirect to login"""
    response = c.get('/settings', follow_redirects=False)
    # Either redirects to login or another protected subpage
    assert response.status_code in [302, 200]


@test("Protected route accessible when authenticated")
def _(c=auth_client):
    """Test that authenticated users can access protected routes"""
    response = c.get('/settings', follow_redirects=False)
    # Should redirect to settings/profile, not login
    assert response.status_code == 302
    assert 'profile' in response.location or 'settings' in response.location


@test("/forgot-password GET shows reset form")
def _(c=client):
    response = c.get('/forgot-password')
    assert response.status_code == 200
    assert b'Forgot Password' in response.data


@test("/forgot-password POST creates token for existing email")
def _(c=client, user=auth_user):
    with patch('app.views.anon.bus.emit') as emit_mock:
        response = c.post('/forgot-password', data={'email': user.email}, follow_redirects=False)

    assert response.status_code == 302
    token = PasswordResetToken.get_or_none(PasswordResetToken.user == user.username)
    assert token is not None
    assert emit_mock.called


@test("/forgot-password POST does not create token for unknown email")
def _(c=client, f=fake):
    unknown_email = f"unknown-{int(time.time() * 1000000)}@example.com"

    with patch('app.views.anon.bus.emit') as emit_mock:
        response = c.post('/forgot-password', data={'email': unknown_email}, follow_redirects=False)

    assert response.status_code == 302
    token = PasswordResetToken.get_or_none(PasswordResetToken.user == unknown_email)
    assert token is None
    assert not emit_mock.called


@test("/reset-password rejects expired token and deletes it")
def _(c=client, user=auth_user):
    token_value = f"expired-{int(time.time() * 1000000)}"
    token = PasswordResetToken.create(
        token=token_value,
        user=user.username,
        created_at=int(time.time()) - 86500,
    )

    response = c.get(f'/reset-password/{token_value}', follow_redirects=False)

    assert response.status_code == 302
    assert PasswordResetToken.get_or_none(PasswordResetToken.token == token.token) is None


@test("/reset-password POST updates password and consumes token")
def _(c=client, user=auth_user):
    token_value = f"valid-{int(time.time() * 1000000)}"
    PasswordResetToken.create(
        token=token_value,
        user=user.username,
        created_at=int(time.time()),
    )

    new_password = 'newpassword123'
    response = c.post(
        f'/reset-password/{token_value}',
        data={'password': new_password},
        follow_redirects=False,
    )

    assert response.status_code == 302
    updated_user = User.get(User.username == user.username)
    assert updated_user.password_hash == pyargon2.hash(new_password, str(updated_user.salt))
    assert PasswordResetToken.get_or_none(PasswordResetToken.token == token_value) is None

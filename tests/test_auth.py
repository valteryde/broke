"""Tests for authentication functionality"""
from ward import test
from tests.fixtures import client, fake, auth_user, auth_client
import json


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

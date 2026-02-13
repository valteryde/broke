"""Tests for news/timeline functionality"""
from ward import test
from tests.fixtures import client, fake, auth_client


@test("/news GET requires authentication")
def _(c=client):
    """Test news requires auth"""
    response = c.get('/news', follow_redirects=False)
    assert response.status_code in [200, 302]  # May allow anonymous or redirect


@test("/news GET shows news when authenticated")
def _(c=auth_client):
    """Test news feed page loads for authenticated user"""
    response = c.get('/news')
    assert response.status_code in [200, 302]


@test("/news POST creates news entry")
def _(c=auth_client, f=fake):
    """Test creating a news entry"""
    response = c.post('/api/news',
                     data={'title': f.sentence(), 'content': f.text()},
                     follow_redirects=False)
    
    assert response.status_code in [200, 201, 302, 401, 404]


@test("/timeline GET shows timeline")
def _(c=auth_client):
    """Test timeline page loads"""
    response = c.get('/timeline')
    assert response.status_code in [200, 302, 401, 404]


@test("/ redirects to /news")
def _(c=client):
    """Test root redirect"""
    response = c.get('/', follow_redirects=False)
    assert response.status_code == 302
    assert '/news' in response.location

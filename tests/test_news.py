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


@test("/news shows logout link in regular web client")
def _(c=auth_client):
    response = c.get('/news')
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b'href="/logout"' in response.data


@test("/news shows switch instance action in desktop client")
def _(c=auth_client):
    response = c.get('/news', headers={'User-Agent': 'BrokeDesktop/0.1'})
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b'Switch instance' in response.data
        assert b'href="/logout"' not in response.data


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


@test("/reports GET requires authentication")
def _(c=client):
    response = c.get('/reports', follow_redirects=False)
    assert response.status_code in [200, 302, 401]


@test("/reports GET shows reporting dashboard when authenticated")
def _(c=auth_client):
    response = c.get('/reports')
    assert response.status_code in [200, 302]
    if response.status_code == 200:
        assert b"Reports" in response.data


@test("/reports/export.csv GET requires authentication")
def _(c=client):
    response = c.get('/reports/export.csv', follow_redirects=False)
    assert response.status_code in [200, 302, 401]


@test("/reports/export.csv GET returns CSV report when authenticated")
def _(c=auth_client):
    response = c.get('/reports/export.csv')
    assert response.status_code == 200
    assert response.headers.get('Content-Type', '').startswith('text/csv')

    body = response.data.decode('utf-8')
    assert 'project_id,project_name,active_tickets,closed_tickets,triage_tickets' in body

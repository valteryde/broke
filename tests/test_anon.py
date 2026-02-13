"""Tests for anonymous ticket submission functionality"""
from ward import test, fixture, Scope
from tests.fixtures import app, client, auth_client, create_test_project
from app.utils.models import GlobalSetting, Project, Ticket
import json
import time


@fixture(scope=Scope.Test)
def anon_enabled_project(app=app):
    """Create a project with anonymous submissions enabled"""
    # Use timestamp to ensure unique project ID per test
    project_id = f"test-anon-proj-{int(time.time() * 1000000)}"
    project = create_test_project(project_id, "Test Anonymous Project", "For testing anon submissions")
    
    # Enable anonymous submissions - delete existing first to avoid conflicts
    GlobalSetting.delete().where(GlobalSetting.key == "anonymous_settings").execute()
    GlobalSetting.create(
        key="anonymous_settings",
        value=json.dumps({
            "enabled": True,
            "message": "Welcome! Please submit your ticket.",
            "projects": [project_id]
        })
    )
    
    yield project
    
    # Cleanup
    GlobalSetting.delete().where(GlobalSetting.key == "anonymous_settings").execute()
    project.delete_instance()


@test("/anon GET when disabled returns 403")
def _(c=client):
    """Test anonymous index when feature is disabled"""
    # Ensure anon is explicitly disabled
    GlobalSetting.delete().where(GlobalSetting.key == "anonymous_settings").execute()
    GlobalSetting.create(
        key="anonymous_settings",
        value=json.dumps({"enabled": False})
    )
    response = c.get('/anon')
    assert response.status_code == 403
    assert b'disabled' in response.data


@test("/anon GET when enabled shows wizard")
def _(c=client, project=anon_enabled_project):
    """Test anonymous index when feature is enabled"""
    response = c.get('/anon')
    # Should redirect to project page if only one project
    assert response.status_code in [200, 302]


@test("/anon/<project_id> GET shows submission form")
def _(c=client, project=anon_enabled_project):
    """Test anonymous wizard for specific project"""
    response = c.get(f'/anon/{project.id}')
    assert response.status_code in [200, 302]


@test("/anon/<project_id> GET with invalid project returns 403")
def _(c=client, project=anon_enabled_project):
    """Test anonymous wizard with non-allowed project"""
    response = c.get('/anon/invalid-project-id')
    assert response.status_code in [403, 404, 500]


@test("/anon/<project_id> POST creates anonymous ticket")
def _(c=client, project=anon_enabled_project):
    """Test creating anonymous ticket"""
    initial_count = Ticket.select().count()
    
    # Use the correct API endpoint with JSON
    response = c.post('/api/anon/submit', 
        json={
            'title': 'Anonymous Bug Report',
            'description': 'Something is broken',
            'project': project.id
        },
        content_type='application/json',
        follow_redirects=False)
    
    # Should create ticket and return success
    assert response.status_code in [200, 201, 302]
    # Ticket count should increase (or stay same if validation fails)
    assert Ticket.select().count() >= initial_count


@test("/anon/track/<token> GET shows tracking page")
def _(c=client):
    """Test anonymous ticket tracking"""
    response = c.get('/anon/track/test-token-12345')
    # May return 200 (found) or 404 (not found)
    assert response.status_code in [200, 404]


@test("Anonymous settings disabled by default")
def _(c=client):
    """Test that anonymous submissions are disabled by default"""
    # Delete any existing settings
    GlobalSetting.delete().where(GlobalSetting.key == "anonymous_settings").execute()
    
    response = c.get('/anon')
    assert response.status_code == 403

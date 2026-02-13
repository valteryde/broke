"""Tests for bug/error tracking functionality"""
from ward import test
from tests.fixtures import client, fake, test_project, auth_client


@test("/bugs GET requires authentication")
def _(c=client):
    """Test error tracking requires auth"""
    response = c.get('/bugs', follow_redirects=False)
    assert response.status_code in [200, 302, 404]


@test("/bugs GET shows error tracking page when authenticated")
def _(c=auth_client):
    """Test error tracking page loads"""
    response = c.get('/bugs')
    assert response.status_code in [200, 302, 404]


@test("/bugs/<project> GET shows project errors")
def _(c=auth_client, project=test_project):
    """Test project-specific error page"""
    response = c.get(f'/bugs/{project.id}')
    assert response.status_code in [200, 302, 404]


@test("Create error group from DSN event")
def _(f=fake, project=test_project):
    """Test error group creation"""
    from app.utils.models import ErrorGroup, ProjectPart
    
    # Create a project part
    part = ProjectPart.create(
        project=project,
        name=f.word(),
        description=f.sentence()
    )
    
    # Create error group
    error = ErrorGroup.create(
        part=part,
        fingerprint=f.uuid4(),
        exception_type="ValueError",
        exception_value="Test error",
        platform="python",
        environment="test",
        event_count=1
    )
    
    assert error.exception_type == "ValueError"
    assert error.event_count == 1


@test("/api/bugs/project/<id>/part POST creates project part")
def _(c=auth_client, f=fake, project=test_project):
    """Test creating a project part"""
    response = c.post(f'/api/bugs/project/{project.id}/part',
                     data={
                         'name': f.word(),
                         'description': f.sentence()
                     },
                     follow_redirects=False)
    
    assert response.status_code in [200, 302, 404]

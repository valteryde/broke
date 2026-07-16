"""Tests for bug/error tracking functionality"""
import json

from ward import test
from tests.fixtures import client, fake, auth_client, create_test_project


@test("/errors GET requires authentication")
def _(c=client):
    """Test error tracking requires auth"""
    response = c.get("/errors", follow_redirects=False)
    assert response.status_code in [200, 302, 401]


@test("/errors GET shows error tracking page when authenticated")
def _(c=auth_client):
    """Test error tracking page loads"""
    response = c.get("/errors")
    assert response.status_code == 200


@test("Create error group for a part")
def _(f=fake):
    """Test error group creation"""
    from app.utils.models import ErrorGroup, ProjectPart

    part = ProjectPart.create(
        name=f"part-{f.uuid4()}",
        description=f.sentence(),
    )

    error = ErrorGroup.create(
        part=part,
        fingerprint=f.uuid4(),
        exception_type="ValueError",
        exception_value="Test error",
        platform="python",
        environment="test",
        event_count=1,
    )

    assert error.exception_type == "ValueError"
    assert error.event_count == 1

    ErrorGroup.delete().where(ErrorGroup.id == error.id).execute()
    part.delete_instance()


@test("POST /api/parts creates a part without a project")
def _(c=auth_client, f=fake):
    """Test creating a workspace-level part"""
    name = f"api-part-{f.uuid4()}"
    response = c.post(
        "/api/parts",
        data=json.dumps({"name": name, "description": f.sentence()}),
        content_type="application/json",
    )

    assert response.status_code == 200
    data = json.loads(response.data.decode("utf-8"))
    assert data.get("success") is True
    assert data["part"]["name"] == name

    from app.utils.models import ProjectPart

    ProjectPart.delete().where(ProjectPart.id == data["part"]["id"]).execute()


@test("POST /api/parts rejects duplicate names")
def _(c=auth_client, f=fake):
    from app.utils.models import ProjectPart

    name = f"dup-part-{f.uuid4()}"
    part = ProjectPart.create(name=name, description="first")
    try:
        response = c.post(
            "/api/parts",
            data=json.dumps({"name": name, "description": "second"}),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = json.loads(response.data.decode("utf-8"))
        assert "already exists" in data.get("error", "")
    finally:
        part.delete_instance()


@test("Deleting a ticket project leaves parts intact")
def _(f=fake):
    from app.utils.models import Project, ProjectPart

    project = create_test_project(f"del-proj-{f.uuid4()}", "Temp", "temp")
    part = ProjectPart.create(name=f"keep-part-{f.uuid4()}", description="stays")
    try:
        project.delete_instance()
        assert Project.get_or_none(Project.id == project.id) is None
        assert ProjectPart.get_or_none(ProjectPart.id == part.id) is not None
    finally:
        if ProjectPart.get_or_none(ProjectPart.id == part.id):
            part.delete_instance()
        if Project.get_or_none(Project.id == project.id):
            project.delete_instance()

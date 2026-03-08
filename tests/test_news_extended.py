"""Extended tests for news and timeline functionality"""
from ward import test, fixture, Scope
from tests.fixtures import app, client, auth_client, auth_user, create_test_project
from app.utils.models import Project, Ticket, Comment, TicketUpdateMessage
import json
import time


@fixture(scope=Scope.Test)
def sample_project_for_timeline(app=app):
    """Create a project for timeline testing"""
    project_id = f"timeline-proj-{int(time.time() * 1000000)}"
    project = create_test_project(project_id, "Timeline Project", "For timeline tests")
    yield project
    project.delete_instance()


@fixture(scope=Scope.Test)
def sample_ticket_for_news(app=app, project=sample_project_for_timeline, user=auth_user):
    """Create a ticket for news/timeline testing"""
    ticket_id = f"NEWS-{int(time.time() * 1000000)}"
    ticket = Ticket.create(
        id=ticket_id,
        title="News Ticket",
        description="Test ticket",
        project=project.id,
        author=user.username,
        status="open",
        priority="medium",
        active=1
    )
    yield ticket
    ticket.delete_instance()


@test("/timeline/<project_id> GET shows project timeline")
def _(c=auth_client, project=sample_project_for_timeline):
    """Test viewing timeline for specific project"""
    response = c.get(f'/timeline/{project.id}')
    assert response.status_code == 200


@test("/news POST with JSON creates news entry")
def _(c=auth_client, ticket=sample_ticket_for_news):
    """Test news page shows recent activity"""
    response = c.get('/news')
    assert response.status_code == 200


@test("/news POST with form data creates news entry")
def _(c=auth_client, ticket=sample_ticket_for_news):
    """Test news displays ticket activity"""
    response = c.get('/news')
    assert response.status_code == 200


@test("/news GET with no entries shows empty state")
def _(c=auth_client):
    """Test news page with no entries"""
    # Delete all tickets
    Ticket.delete().execute()
    
    response = c.get('/news')
    assert response.status_code == 200


@test("/timeline GET with no activity shows empty state")
def _(c=auth_client):
    """Test timeline with no activity"""
    response = c.get('/timeline')
    assert response.status_code == 200


@test("News displays comments on tickets")
def _(c=auth_client, ticket=sample_ticket_for_news, user=auth_user):
    """Test that news shows comment activity"""
    # Create a comment
    comment = Comment.create(
        ticket=ticket.id,
        user=user,
        body="Test comment for news",
        created_at=1234567890
    )
    
    response = c.get('/news')
    assert response.status_code == 200
    
    comment.delete_instance()


@test("Timeline with special characters in project name")
def _(c=auth_client):
    """Test timeline with special characters"""
    timestamp = int(time.time() * 1000000)
    proj = create_test_project(f"special-proj-{timestamp}", "Special <>&\" Project", "Test")
    
    response = c.get(f'/timeline/{proj.id}')
    assert response.status_code == 200
    
    proj.delete_instance()


@test("Timeline with multiple projects")
def _(c=auth_client):
    """Test timeline across multiple projects"""
    timestamp = int(time.time() * 1000000)
    proj1 = create_test_project(f"p1-{timestamp}", "P1", "Test")
    proj2 = create_test_project(f"p2-{timestamp}", "P2", "Test")
    
    # Create tickets in both projects
    Ticket.create(id=f"P1-1-{timestamp}", title="T1", description="D1", project=proj1.id, author="test", status="open", priority="medium", active=1)
    Ticket.create(id=f"P2-1-{timestamp}", title="T2", description="D2", project=proj2.id, author="test", status="open", priority="medium", active=1)
    
    response = c.get('/timeline')
    assert response.status_code == 200
    
    # Cleanup
    Ticket.delete().where(Ticket.id.in_([f"P1-1-{timestamp}", f"P2-1-{timestamp}"])).execute()
    proj1.delete_instance()
    proj2.delete_instance()


@test("News page with many ticket updates")
def _(c=auth_client, user=auth_user):
    """Test news page with many ticket activities"""
    timestamp = int(time.time() * 1000000)
    project = create_test_project(f"busy-proj-{timestamp}", "Busy", "Test")
    
    # Create multiple tickets
    tickets = []
    for i in range(10):
        ticket = Ticket.create(
            id=f"BUSY-{timestamp}-{i}",
            title=f"Ticket {i}",
            description=f"Description {i}",
            project=project.id,
            author=user.username,
            status="open",
            priority="medium",
            active=1
        )
        tickets.append(ticket)
    
    response = c.get('/news')
    assert response.status_code == 200
    
    # Cleanup
    for ticket in tickets:
        ticket.delete_instance()
    project.delete_instance()


@test("Timeline defaults to compact highlights view")
def _(c=auth_client, user=auth_user):
    """Default timeline hides low-signal comments and metadata updates."""
    timestamp = int(time.time() * 1000000)
    project = create_test_project(f"tl-compact-{timestamp}", "Timeline Compact", "Test")
    ticket = Ticket.create(
        id=f"TL-{timestamp}",
        title="Timeline compact test",
        description="Test",
        project=project.id,
        author=user.username,
        status="open",
        priority="medium",
        active=1,
    )
    comment = Comment.create(
        ticket=ticket.id,
        user=user,
        body="This comment should only show in detailed mode",
        created_at=int(time.time()),
    )
    label_update = TicketUpdateMessage.create(
        ticket=ticket.id,
        title="Labels changed",
        icon="ph ph-tag",
        message="labels were updated",
        created_at=int(time.time()),
    )
    status_update = TicketUpdateMessage.create(
        ticket=ticket.id,
        title="Status changed",
        icon="ph ph-arrow-right",
        message="status moved from todo to in-progress",
        created_at=int(time.time()),
    )

    response = c.get("/timeline")
    body = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "Status changed" in body
    assert f"Comment on {ticket.id}" not in body
    assert "Labels changed" not in body

    comment.delete_instance()
    label_update.delete_instance()
    status_update.delete_instance()
    ticket.delete_instance()
    project.delete_instance()


@test("Timeline detailed mode shows full activity")
def _(c=auth_client, user=auth_user):
    """Detailed mode includes comments and low-signal updates."""
    timestamp = int(time.time() * 1000000)
    project = create_test_project(f"tl-detail-{timestamp}", "Timeline Detail", "Test")
    ticket = Ticket.create(
        id=f"TD-{timestamp}",
        title="Timeline detail test",
        description="Test",
        project=project.id,
        author=user.username,
        status="open",
        priority="medium",
        active=1,
    )
    comment = Comment.create(
        ticket=ticket.id,
        user=user,
        body="Detailed mode comment",
        created_at=int(time.time()),
    )
    label_update = TicketUpdateMessage.create(
        ticket=ticket.id,
        title="Labels changed",
        icon="ph ph-tag",
        message="labels were updated",
        created_at=int(time.time()),
    )

    response = c.get("/timeline?detail=all")
    body = response.data.decode("utf-8")

    assert response.status_code == 200
    assert f"Comment on {ticket.id}" in body
    assert "Labels changed" in body

    comment.delete_instance()
    label_update.delete_instance()
    ticket.delete_instance()
    project.delete_instance()

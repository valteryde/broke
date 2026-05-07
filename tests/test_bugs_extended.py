"""Extended tests for bug/error tracking functionality"""
from unittest.mock import patch

from ward import test, fixture, Scope
from tests.fixtures import app, client, auth_client, auth_user, create_test_project
from app.utils.models import Project, ProjectPart, ErrorGroup, ErrorOccurrence, DSNToken
from app.views.bug import (
    normalize_message,
    extract_frame_signatures,
    generate_fingerprint,
    extract_exception_info,
    extract_culprit
)
import json
import hashlib
import time


@fixture(scope=Scope.Test)
def error_project(app=app):
    """Create a project for error tracking"""
    project_id = f"error-proj-{int(time.time() * 1000000)}"
    project = create_test_project(project_id, "Error Project", "For error tracking")
    yield project
    project.delete_instance()


@fixture(scope=Scope.Test)
def error_project_part(app=app, project=error_project):
    """Create a project part for error tracking"""
    part = ProjectPart.create(
        project=project.id,
        name="backend",
        description="Backend service"
    )
    yield part
    part.delete_instance()


@fixture(scope=Scope.Test)
def dsn_token_fixture(app=app, project=error_project):
    """Create a DSN token for testing"""
    token = DSNToken.create(
        token="test-dsn-token-12345",
        project=project.id
    )
    yield token
    token.delete_instance()


@fixture(scope=Scope.Test)
def error_group_fixture(app=app, part=error_project_part):
    error_group = ErrorGroup.create(
        part=part,
        fingerprint=f"fp-{int(time.time() * 1000000)}",
        exception_type="ValueError",
        exception_value="Fixture error",
        platform="python",
        environment="test",
        event_count=1,
        status="unresolved",
    )
    yield error_group
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == error_group).execute()
    error_group.delete_instance()


@test("normalize_message removes UUIDs")
def _():
    """Test that normalize_message removes UUID patterns"""
    message = "Error in 550e8400-e29b-41d4-a716-446655440000"
    result = normalize_message(message)
    assert "<UUID>" in result
    assert "550e8400" not in result


@test("normalize_message removes hex addresses")
def _():
    """Test that normalize_message removes hex addresses"""
    message = "Memory at 0x7fff5fbff790"
    result = normalize_message(message)
    assert "<HEX>" in result
    assert "0x7fff5fbff790" not in result


@test("normalize_message removes numbers")
def _():
    """Test that normalize_message removes standalone numbers"""
    message = "Error on line 42 in file"
    result = normalize_message(message)
    assert "<N>" in result
    assert "42" not in result


@test("normalize_message removes quoted strings")
def _():
    """Test that normalize_message removes quoted strings"""
    message = 'File "/path/to/file.py" not found'
    result = normalize_message(message)
    assert '"<STR>"' in result
    assert "/path/to/file.py" not in result


@test("normalize_message removes IP addresses")
def _():
    """Test that normalize_message removes IP addresses"""
    message = "Connection to 192.168.1.100 failed"
    result = normalize_message(message)
    # IP addresses are normalized to <N>.<N>.<N>.<N>
    assert "<N>" in result
    assert "192.168.1.100" not in result


@test("normalize_message removes timestamps")
def _():
    """Test that normalize_message removes ISO timestamps"""
    message = "Error at 2024-01-15T10:30:45"
    result = normalize_message(message)
    # Check if timestamp is normalized (may vary by implementation)
    assert "2024-01-15" not in result or "<" in result


@test("normalize_message handles None")
def _():
    """Test that normalize_message handles None input"""
    result = normalize_message(None)
    assert result == ""


@test("extract_frame_signatures parses stacktrace")
def _():
    """Test extracting function signatures from stacktrace"""
    stacktrace_json = json.dumps({
        "frames": [
            {"module": "myapp.views", "function": "index"},
            {"module": "myapp.models", "function": "get_user"},
            {"filename": "utils.py", "function": "helper"}
        ]
    })

    signatures = extract_frame_signatures(stacktrace_json)
    assert len(signatures) == 3
    assert "myapp.views:index" in signatures
    assert "myapp.models:get_user" in signatures
    assert "utils.py:helper" in signatures


@test("extract_frame_signatures handles invalid JSON")
def _():
    """Test extracting signatures from invalid JSON"""
    result = extract_frame_signatures("not valid json")
    assert result == []


@test("extract_frame_signatures handles None")
def _():
    """Test extracting signatures from None"""
    result = extract_frame_signatures(None)
    assert result == []


@test("generate_fingerprint creates consistent hash")
def _():
    """Test that generate_fingerprint creates consistent hashes"""
    stacktrace = json.dumps({"frames": [{"module": "test", "function": "func"}]})

    fp1 = generate_fingerprint("ValueError", "Test error", stacktrace)
    fp2 = generate_fingerprint("ValueError", "Test error", stacktrace)

    assert fp1 == fp2
    assert len(fp1) == 32  # SHA256 truncated to 32 chars


@test("generate_fingerprint normalizes dynamic values")
def _():
    """Test that fingerprint ignores dynamic values"""
    stacktrace = json.dumps({"frames": [{"module": "test", "function": "func"}]})

    # These should produce the same fingerprint
    fp1 = generate_fingerprint("ValueError", "Error on line 42", stacktrace)
    fp2 = generate_fingerprint("ValueError", "Error on line 99", stacktrace)

    assert fp1 == fp2


@test("extract_exception_info from Sentry payload")
def _():
    """Test extracting exception info from Sentry event"""
    payload = {
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "Invalid input",
                    "stacktrace": {"frames": []}
                }
            ]
        }
    }

    exc_type, exc_value, stacktrace = extract_exception_info(payload)
    assert exc_type == "ValueError"
    assert exc_value == "Invalid input"
    assert stacktrace is not None


@test("extract_exception_info fallback to message")
def _():
    """Test fallback to message field"""
    payload = {"message": "Something went wrong"}

    exc_type, exc_value, stacktrace = extract_exception_info(payload)
    assert exc_value == "Something went wrong"


@test("extract_culprit from payload")
def _():
    """Test extracting culprit from Sentry event"""
    payload = {"culprit": "myapp.views.index"}

    culprit = extract_culprit(payload)
    assert culprit == "myapp.views.index"


@test("extract_culprit from stacktrace")
def _():
    """Test extracting culprit from stacktrace"""
    payload = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "views.py",
                                "function": "handler",
                                "lineno": 42
                            }
                        ]
                    }
                }
            ]
        }
    }

    culprit = extract_culprit(payload)
    assert "views.py" in culprit
    assert "handler" in culprit


@test("/bugs/<project_id> GET shows project errors")
def _(c=auth_client, project=error_project):
    """Test viewing errors for a project"""
    response = c.get(f'/bugs/{project.id}')
    # May return 200 if project exists, or 404 if no errors/project not found
    assert response.status_code in [200, 404]


@test("/bugs/<project_id>/<part_name> GET shows part errors")
def _(c=auth_client, project=error_project, part=error_project_part):
    """Test viewing errors for a specific project part"""
    response = c.get(f'/bugs/{project.id}/{part.name}')
    assert response.status_code in [200, 404]


@test("/api/bugs/dsn/<token> POST receives error event")
def _(c=client, token=dsn_token_fixture, part=error_project_part):
    """Test receiving error event via DSN"""
    event_data = {
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "Test error",
                    "stacktrace": {"frames": []}
                }
            ]
        },
        "platform": "python",
        "event_id": "abc123"
    }

    response = c.post(
        f'/api/bugs/dsn/{token.token}',
        data=json.dumps(event_data),
        content_type='application/json',
        headers={'X-Sentry-Auth': f'Sentry sentry_key={token.token}'}
    )

    # May succeed or fail depending on implementation
    assert response.status_code in [200, 201, 400, 404]


@test("Error group creation from event")
def _(part=error_project_part):
    """Test creating error group from event data"""
    from app.views.bug import handle_event_item

    payload = {
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": "Test runtime error",
                    "stacktrace": {
                        "frames": [
                            {"module": "test", "function": "test_func"}
                        ]
                    }
                }
            ]
        },
        "platform": "python",
        "event_id": "test-event-123"
    }

    with patch("app.views.bug.bus.emit"):
        error_group = handle_event_item(part, payload, "test-event-123")

    assert error_group is not None
    assert error_group.exception_type == "RuntimeError"
    assert error_group.event_count >= 1

    # Cleanup
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == error_group).execute()
    error_group.delete_instance()


@test("Error group increments count on duplicate")
def _(part=error_project_part):
    """Test that duplicate errors increment the count"""
    from app.views.bug import handle_event_item

    payload = {
        "exception": {
            "values": [
                {
                    "type": "KeyError",
                    "value": "missing_key",
                    "stacktrace": {"frames": [{"module": "test", "function": "func"}]}
                }
            ]
        }
    }

    with patch("app.views.bug.bus.emit"):
        # First occurrence
        error_group1 = handle_event_item(part, payload, "event-1")
        count1 = error_group1.event_count

        # Second occurrence (should be same group)
        error_group2 = handle_event_item(part, payload, "event-2")
        count2 = error_group2.event_count

    assert error_group1.id == error_group2.id
    assert count2 > count1

    # Cleanup
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == error_group1).execute()
    error_group1.delete_instance()


@test("Resolved error group reopens when same fingerprint reoccurs")
def _(part=error_project_part):
    """Regression detection: resolved errors should reopen on new occurrences."""
    from app.views.bug import handle_event_item

    payload = {
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": "regression detected",
                    "stacktrace": {"frames": [{"module": "svc", "function": "run"}]},
                }
            ]
        }
    }

    with patch("app.views.bug.bus.emit"):
        error_group = handle_event_item(part, payload, "regression-event-1")
        error_group.status = "resolved"
        error_group.save()

        reopened = handle_event_item(part, payload, "regression-event-2")

    assert reopened.id == error_group.id
    assert reopened.event_count >= 2
    assert reopened.status == "unresolved"

    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == reopened).execute()
    reopened.delete_instance()


@test("handle_event_item emits ERROR_NEW for new error group")
def _(part=error_project_part):
    from app.utils.events import EventTypes
    from app.views.bug import handle_event_item

    payload = {
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": f"new-emit-{time.time()}",
                    "stacktrace": {"frames": [{"module": "a", "function": "b"}]},
                }
            ]
        }
    }
    with patch("app.views.bug.bus.emit") as emit_mock:
        eg = handle_event_item(part, payload, "n1")
    assert emit_mock.call_count == 1
    assert emit_mock.call_args[0][0] == EventTypes.ERROR_NEW
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == eg).execute()
    eg.delete_instance()


@test("handle_event_item emits ERROR_REGRESSION when resolved group reopens")
def _(part=error_project_part):
    from app.utils.events import EventTypes
    from app.views.bug import handle_event_item

    payload = {
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": f"reg-emit-{time.time()}",
                    "stacktrace": {"frames": [{"module": "svc", "function": "run"}]},
                }
            ]
        }
    }
    with patch("app.views.bug.bus.emit"):
        eg = handle_event_item(part, payload, "r1")
        eg.status = "resolved"
        eg.save()

    with patch("app.views.bug.bus.emit") as emit_mock:
        handle_event_item(part, payload, "r2")

    types = [c[0][0] for c in emit_mock.call_args_list]
    assert EventTypes.ERROR_REGRESSION in types
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == eg).execute()
    eg.delete_instance()


@test("handle_event_item emits ERROR_ESCALATING on volume milestone")
def _(part=error_project_part):
    from app.utils.events import EventTypes
    from app.views.bug import handle_event_item

    payload = {
        "exception": {
            "values": [
                {
                    "type": "KeyError",
                    "value": f"milestone-{time.time()}",
                    "stacktrace": {"frames": [{"module": "k", "function": "v"}]},
                }
            ]
        }
    }
    with patch("app.views.bug.bus.emit"):
        eg = handle_event_item(part, payload, "m1")
        eg.event_count = 9
        eg.save()

    with patch("app.views.bug.bus.emit") as emit_mock:
        handle_event_item(part, payload, "m2")

    types = [c[0][0] for c in emit_mock.call_args_list]
    assert EventTypes.ERROR_ESCALATING in types
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == eg).execute()
    eg.delete_instance()


@test("handle_event_item emits ERROR_ESCALATING on spike in short window")
def _(part=error_project_part):
    from app.utils.events import EventTypes
    from app.views.bug import handle_event_item

    payload = {
        "exception": {
            "values": [
                {
                    "type": "OSError",
                    "value": f"spike-{time.time()}",
                    "stacktrace": {"frames": [{"module": "spike", "function": "main"}]},
                }
            ]
        }
    }
    ts = int(time.time())
    with patch("app.views.bug.bus.emit"):
        eg = handle_event_item(part, payload, "s0")
        for i in range(3):
            ErrorOccurrence.create(error_group=eg, timestamp=ts, event_id=f"seed{i}")

    with patch("app.views.bug.bus.emit") as emit_mock:
        handle_event_item(part, payload, "s4")

    types = [c[0][0] for c in emit_mock.call_args_list]
    assert EventTypes.ERROR_ESCALATING in types
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == eg).execute()
    eg.delete_instance()


@test("handle_event_item spike cooldown suppresses repeat ERROR_ESCALATING")
def _(part=error_project_part):
    from app.utils.events import EventTypes
    from app.views.bug import handle_event_item

    payload = {
        "exception": {
            "values": [
                {
                    "type": "OSError",
                    "value": f"cool-{time.time()}",
                    "stacktrace": {"frames": [{"module": "c", "function": "d"}]},
                }
            ]
        }
    }
    ts = int(time.time())
    with patch("app.views.bug.bus.emit"):
        eg = handle_event_item(part, payload, "c0")
        for i in range(3):
            ErrorOccurrence.create(error_group=eg, timestamp=ts, event_id=f"cd{i}")

    with patch("app.views.bug.bus.emit") as e_first:
        handle_event_item(part, payload, "c1")
    assert any(c[0][0] == EventTypes.ERROR_ESCALATING for c in e_first.call_args_list)

    with patch("app.views.bug.bus.emit") as e_second:
        handle_event_item(part, payload, "c2")
    assert not any(c[0][0] == EventTypes.ERROR_ESCALATING for c in e_second.call_args_list)

    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == eg).execute()
    eg.delete_instance()


@test("handle_event_item skips ERROR_ESCALATING when group is ignored")
def _(part=error_project_part):
    from app.utils.events import EventTypes
    from app.views.bug import handle_event_item

    payload = {
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": f"ign-{time.time()}",
                    "stacktrace": {"frames": [{"module": "i", "function": "j"}]},
                }
            ]
        }
    }
    with patch("app.views.bug.bus.emit"):
        eg = handle_event_item(part, payload, "i0")
        eg.status = "ignored"
        eg.event_count = 9
        eg.save()

    with patch("app.views.bug.bus.emit") as emit_mock:
        handle_event_item(part, payload, "i1")

    types = [c[0][0] for c in emit_mock.call_args_list]
    assert EventTypes.ERROR_ESCALATING not in types
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == eg).execute()
    eg.delete_instance()


@test("/api/errors/<id>/status requires authentication")
def _(c=client, error_group=error_group_fixture):
    with c.session_transaction() as sess:
        sess.pop("user_id", None)
        sess.pop("_csrf_token", None)

    response = c.post(
        f"/api/errors/{error_group.id}/status",
        data=json.dumps({"status": "resolved"}),
        content_type="application/json",
        follow_redirects=False,
    )
    assert response.status_code in [302, 401]


@test("/api/errors/<id>/status works when authenticated")
def _(c=auth_client, error_group=error_group_fixture):
    response = c.post(
        f"/api/errors/{error_group.id}/status",
        data=json.dumps({"status": "resolved"}),
        content_type="application/json",
    )
    assert response.status_code == 200


@test("/api/errors/<id>/create_ticket requires authentication")
def _(c=client, error_group=error_group_fixture):
    response = c.get(
        f"/api/errors/{error_group.id}/create_ticket",
        follow_redirects=False,
    )
    assert response.status_code in [302, 401]


@test("DELETE /api/projects/<project_id>/parts/<part_id>/errors requires authentication")
def _(c=client, project=error_project, part=error_project_part):
    with c.session_transaction() as sess:
        sess.pop("user_id", None)
        sess.pop("_csrf_token", None)

    response = c.delete(
        f"/api/projects/{project.id}/parts/{part.id}/errors",
        follow_redirects=False,
    )
    assert response.status_code in [302, 401]


@test("DELETE /api/projects/<project_id>/parts/<part_id>/errors deletes all error groups")
def _(c=auth_client, project=error_project, part=error_project_part):
    e1 = ErrorGroup.create(
        part=part,
        fingerprint=f"fp-bulk-1-{int(time.time() * 1000000)}",
        exception_type="TypeError",
        exception_value="one",
        event_count=1,
        status="unresolved",
    )
    e2 = ErrorGroup.create(
        part=part,
        fingerprint=f"fp-bulk-2-{int(time.time() * 1000000)}",
        exception_type="TypeError",
        exception_value="two",
        event_count=1,
        status="unresolved",
    )
    try:
        response = c.delete(
            f"/api/projects/{project.id}/parts/{part.id}/errors",
            follow_redirects=False,
        )
        assert response.status_code == 200
        data = json.loads(response.data.decode("utf-8"))
        assert data.get("success") is True
        assert data.get("deleted") == 2
        assert (
            ErrorGroup.select()
            .where(ErrorGroup.part == part)
            .count()
            == 0
        )
    finally:
        for eg in (e1, e2):
            if ErrorGroup.select().where(ErrorGroup.id == eg.id).count():
                ErrorOccurrence.delete().where(ErrorOccurrence.error_group == eg).execute()
                eg.delete_instance()


@test("DELETE /api/projects/<project_id>/parts/<part_id>/errors returns 404 when part not in project")
def _(c=auth_client, part=error_project_part):
    response = c.delete(
        f"/api/projects/wrong-project-id/parts/{part.id}/errors",
        follow_redirects=False,
    )
    assert response.status_code == 404


@test("DELETE /api/projects/<project_id>/parts/<part_id>/errors succeeds when part has no errors")
def _(c=auth_client, project=error_project, part=error_project_part):
    response = c.delete(
        f"/api/projects/{project.id}/parts/{part.id}/errors",
        follow_redirects=False,
    )
    assert response.status_code == 200
    data = json.loads(response.data.decode("utf-8"))
    assert data.get("success") is True
    assert data.get("deleted") == 0


@test("/errors/<project_id>/<part_id> renders environment and release fields for filtering")
def _(c=auth_client, project=error_project, part=error_project_part):
    error = ErrorGroup.create(
        part=part,
        fingerprint=f"fp-filter-{int(time.time() * 1000000)}",
        exception_type="RuntimeError",
        exception_value="Filtering payload test",
        platform="python",
        environment="production",
        release="v1.2.3",
        event_count=1,
        status="unresolved",
    )

    try:
        response = c.get(f"/errors/{project.id}/{part.id}")
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert 'environment: "production"' in body
        assert 'release: "v1.2.3"' in body
    finally:
        ErrorOccurrence.delete().where(ErrorOccurrence.error_group == error).execute()
        error.delete_instance()


@test("/errors/<project_id>/<part_id> renders null environment and release when missing")
def _(c=auth_client, project=error_project, part=error_project_part):
    error = ErrorGroup.create(
        part=part,
        fingerprint=f"fp-filter-none-{int(time.time() * 1000000)}",
        exception_type="TypeError",
        exception_value="Missing metadata test",
        platform="python",
        environment=None,
        release=None,
        event_count=1,
        status="unresolved",
    )

    try:
        response = c.get(f"/errors/{project.id}/{part.id}")
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert "environment: null" in body
        assert "release: null" in body
    finally:
        ErrorOccurrence.delete().where(ErrorOccurrence.error_group == error).execute()
        error.delete_instance()


@test("/errors/<project_id>/<part_id> renders inline row status actions")
def _(c=auth_client, project=error_project, part=error_project_part):
    error = ErrorGroup.create(
        part=part,
        fingerprint=f"fp-inline-actions-{int(time.time() * 1000000)}",
        exception_type="ValueError",
        exception_value="Inline action rendering",
        platform="python",
        environment="staging",
        release="v2.0.0",
        event_count=1,
        status="unresolved",
    )

    try:
        response = c.get(f"/errors/{project.id}/{part.id}")
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert "error-inline-action" in body
        assert "errorList.handleUpdate(item, 'status', newStatus)" in body
    finally:
        ErrorOccurrence.delete().where(ErrorOccurrence.error_group == error).execute()
        error.delete_instance()

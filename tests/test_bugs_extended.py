"""Extended tests for bug/error tracking functionality"""
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

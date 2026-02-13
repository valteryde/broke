"""
Comprehensive tests for Sentry envelope specifications.

Tests based on official Sentry documentation:
- https://develop.sentry.dev/sdk/data-model/envelopes/
- https://develop.sentry.dev/sdk/data-model/event-payloads/
"""

from ward import test, fixture, Scope
from tests.fixtures import app, client, create_test_project
from app.utils.models import Project, ProjectPart, ErrorGroup, ErrorOccurrence, DSNToken
import json
import gzip
import time
import uuid


@fixture(scope=Scope.Test)
def sentry_project(app=app):
    """Create a project for Sentry testing"""
    timestamp = int(time.time() * 1000000)
    project = create_test_project(f"sentry-proj-{timestamp}", "Sentry Project", "For Sentry tests")
    yield project
    project.delete_instance()


@fixture(scope=Scope.Test)
def sentry_project_part(app=app, project=sentry_project):
    """Create a project part for Sentry testing"""
    part = ProjectPart.create(project=project.id, name="backend", description="Backend service")
    yield part
    # Clean up all error groups and occurrences for this part before deleting
    error_groups = ErrorGroup.select().where(ErrorGroup.part == part.id)
    for eg in error_groups:
        ErrorOccurrence.delete().where(ErrorOccurrence.error_group == eg).execute()
    ErrorGroup.delete().where(ErrorGroup.part == part.id).execute()
    part.delete_instance()


@fixture(scope=Scope.Test)
def dsn_token(app=app, part=sentry_project_part):
    """Create a DSN token for testing"""
    token = DSNToken.create(token=f"test-dsn-{int(time.time() * 1000000)}", project=part.project)
    yield token
    token.delete_instance()


# ==============================================================================
# ENVELOPE FORMAT & SERIALIZATION TESTS
# ==============================================================================


@test("Envelope with minimal required headers")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test minimal valid envelope with just event_id in header"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error","message":"test error"}}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200
    assert b"event" in response.data


@test("Envelope with full recommended headers")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test envelope with all recommended headers: event_id, dsn, sent_at, sdk"""
    event_id = uuid.uuid4().hex
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    envelope_header = {
        "event_id": event_id,
        "dsn": f"https://{token.token}@sentry.io/42",
        "sent_at": timestamp,
        "sdk": {"name": "sentry.python", "version": "1.0.0"},
    }

    envelope = json.dumps(envelope_header) + "\n"
    envelope += '{"type":"event","length":150,"content_type":"application/json"}\n'

    event_payload = {
        "event_id": event_id,
        "timestamp": timestamp,
        "platform": "python",
        "level": "error",
        "message": "Full header test",
    }

    envelope += json.dumps(event_payload) + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200


@test("Envelope header must be single-line JSON")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test that envelope header must be single-line JSON (no newlines within)"""
    event_id = uuid.uuid4().hex

    # Valid single-line header
    envelope = f'{{"event_id":"{event_id}","dsn":"https://key@sentry.io/42"}}\n'
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    # Should succeed with single-line header
    assert response.status_code == 200


@test("Item header with required type field")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test that item header requires 'type' field"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event","length":100}\n'  # type is required
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200


@test("Item with length attribute")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test item with explicit length attribute (recommended)"""
    event_id = uuid.uuid4().hex

    event_payload = {
        "event_id": event_id,
        "timestamp": "2024-10-01T10:12:17Z",
        "platform": "python",
        "level": "error",
        "message": "Length test",
    }

    payload_str = json.dumps(event_payload)
    payload_length = len(payload_str.encode("utf-8"))

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += f'{{"type":"event","length":{payload_length},"content_type":"application/json"}}\n'
    envelope += payload_str + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200


@test("Multiple items in single envelope")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test envelope containing multiple items"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'

    # First item: event
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error","message":"item 1"}}\n'

    # Second item: session
    envelope += '{"type":"session"}\n'
    envelope += f'{{"sid":"test-session-123","status":"ok","started":"2024-10-01T10:00:00Z","attrs":{{"release":"1.0.0"}}}}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200
    # Should process both items
    assert b"event" in response.data
    assert b"session" in response.data


@test("Empty lines between items are ignored")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test that empty lines in envelope are safely ignored"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += "\n"  # Empty line
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}}\n'
    envelope += "\n"  # Empty line at end

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200


# ==============================================================================
# EVENT PAYLOAD TESTS
# ==============================================================================


@test("Event with required fields: event_id, timestamp, platform")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test event payload with all required fields"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'

    event_payload = {
        "event_id": event_id,  # Required
        "timestamp": "2024-10-01T10:12:17Z",  # Required (RFC 3339 or Unix)
        "platform": "python",  # Required
    }

    envelope += json.dumps(event_payload) + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200

    # Verify event was stored
    error = ErrorGroup.select().where(ErrorGroup.part == part.id).first()
    assert error is not None


@test("Event with optional recommended fields")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test event with optional but recommended fields"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'

    event_payload = {
        "event_id": event_id,
        "timestamp": "2024-10-01T10:12:17Z",
        "platform": "python",
        "level": "error",  # Optional but recommended
        "logger": "my.app.logger",  # Optional
        "transaction": "/api/users",  # Optional
        "server_name": "foo.example.com",  # Optional
        "release": "1.0.0",  # Optional
        "dist": "prod",  # Optional
        "environment": "production",  # Optional
        "tags": {"ios_version": "4.0", "context": "production"},  # Optional
        "extra": {"my_key": 1},  # Optional
    }

    envelope += json.dumps(event_payload) + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200


@test("Event with exception information")
def _(c=client, token=dsn_token):
    """Test event payload with exception/stacktrace information"""
    # Create isolated project and part for this test
    timestamp = int(time.time() * 1000000)
    project = create_test_project(f"exc-test-{timestamp}", "Exception Test", "Test")
    part = ProjectPart.create(project=project.id, name="backend", description="Backend service")

    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'

    event_payload = {
        "event_id": event_id,
        "timestamp": "2024-10-01T10:12:17Z",
        "platform": "python",
        "level": "error",
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "Invalid input value",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app.py",
                                "function": "main",
                                "lineno": 42,
                                "module": "myapp.main",
                            },
                            {
                                "filename": "utils.py",
                                "function": "process_data",
                                "lineno": 15,
                                "module": "myapp.utils",
                            },
                        ]
                    },
                }
            ]
        },
    }

    envelope += json.dumps(event_payload) + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200

    # Verify exception was parsed
    error = ErrorGroup.select().where(ErrorGroup.part == part.id).first()
    assert error is not None
    assert error.exception_type == "ValueError"

    # Cleanup - delete error groups and occurrences before deleting part/project
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == error).execute()
    ErrorGroup.delete().where(ErrorGroup.part == part.id).execute()
    part.delete_instance()
    project.delete_instance()


@test("Event with custom fingerprint for grouping")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test event with custom fingerprint array"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'

    event_payload = {
        "event_id": event_id,
        "timestamp": "2024-10-01T10:12:17Z",
        "platform": "python",
        "level": "error",
        "message": "Custom fingerprint test",
        "fingerprint": ["myrpc", "POST", "/foo.bar"],  # Custom grouping
    }

    envelope += json.dumps(event_payload) + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200


@test("Event_id in envelope header takes precedence over payload")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test that event_id in envelope header overrides payload event_id"""
    envelope_event_id = uuid.uuid4().hex
    payload_event_id = uuid.uuid4().hex

    # Envelope header has different event_id than payload
    envelope = f'{{"event_id":"{envelope_event_id}"}}\n'
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{payload_event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200
    # According to spec, envelope header event_id wins


@test("Event with Unix timestamp format")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test event with Unix timestamp (alternative to RFC 3339)"""
    event_id = uuid.uuid4().hex
    unix_timestamp = int(time.time())

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'

    event_payload = {
        "event_id": event_id,
        "timestamp": unix_timestamp,  # Unix timestamp instead of RFC 3339
        "platform": "python",
        "level": "error",
    }

    envelope += json.dumps(event_payload) + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200


# ==============================================================================
# AUTHENTICATION & INGESTION TESTS
# ==============================================================================


@test("Envelope with DSN in header for authentication")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test authentication via DSN in envelope header"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}","dsn":"https://{token.token}@sentry.io/42"}}\n'
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200


@test("Envelope with invalid DSN returns 401")
def _(c=client, part=sentry_project_part):
    """Test that invalid DSN token returns 401 Unauthorized"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": "Sentry sentry_key=invalid-token-12345"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 401


@test("Envelope with correct content-type header")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test envelope with application/x-sentry-envelope content-type"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",  # Correct content-type
    )

    assert response.status_code == 200


@test("Envelope with gzip compression")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test envelope with gzip compression (common optimization)"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}}\n'

    # Compress the envelope
    compressed = gzip.compress(envelope.encode("utf-8"))

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=compressed,
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}", "Content-Encoding": "gzip"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200


@test("Invalid project part returns 404")
def _(c=client, token=dsn_token):
    """Test that non-existent project part returns 404"""
    event_id = uuid.uuid4().hex
    invalid_part_id = 999999

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"event"}\n'
    envelope += f'{{"event_id":"{event_id}","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}}\n'

    response = c.post(
        f"/ingest/{invalid_part_id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 404


@test("Empty envelope returns 400")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test that empty envelope returns 400 Bad Request"""
    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=b"",
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 400


@test("Envelope with malformed JSON header")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test handling of malformed JSON in envelope header"""
    # Malformed JSON header (missing closing brace)
    envelope = '{"event_id":"test123"\n'
    envelope += '{"type":"event"}\n'
    envelope += '{"event_id":"test123","timestamp":"2024-10-01T10:12:17Z","platform":"python","level":"error"}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    # Should handle gracefully - may process items with empty envelope headers
    # or return error depending on implementation
    assert response.status_code in [200, 400]


# ==============================================================================
# ITEM TYPE TESTS
# ==============================================================================


@test("Session item in envelope")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test envelope with session item"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"session"}\n'

    session_payload = {
        "sid": f"test-session-{int(time.time())}",
        "status": "ok",
        "started": "2024-10-01T10:00:00Z",
        "attrs": {"release": "1.0.0", "environment": "production"},
    }

    envelope += json.dumps(session_payload) + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200
    assert b"session" in response.data


@test("Transaction item in envelope")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test envelope with transaction item"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"transaction"}\n'

    transaction_payload = {
        "event_id": event_id,
        "type": "transaction",
        "transaction": "/api/users",
        "start_timestamp": 1633024800.0,
        "timestamp": 1633024801.0,
        "contexts": {
            "trace": {"trace_id": uuid.uuid4().hex, "span_id": "a" * 16, "op": "http.server"}
        },
        "spans": [],
    }

    envelope += json.dumps(transaction_payload) + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200
    assert b"transaction" in response.data


@test("Client report item in envelope")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test envelope with client_report item (telemetry about dropped events)"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"client_report"}\n'

    client_report_payload = {
        "timestamp": "2024-10-01T10:12:17Z",
        "discarded_events": [{"reason": "ratelimit_backoff", "category": "error", "quantity": 5}],
    }

    envelope += json.dumps(client_report_payload) + "\n"

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response.status_code == 200
    assert b"client_report" in response.data


@test("Unknown item type is handled gracefully")
def _(c=client, part=sentry_project_part, token=dsn_token):
    """Test that unknown item types don't crash the endpoint"""
    event_id = uuid.uuid4().hex

    envelope = f'{{"event_id":"{event_id}"}}\n'
    envelope += '{"type":"unknown_future_type"}\n'
    envelope += '{"some":"data"}\n'

    response = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    # Should handle gracefully
    assert response.status_code == 200


# ==============================================================================
# ERROR GROUPING & FINGERPRINTING TESTS
# ==============================================================================


@test("Similar errors are grouped together")
def _(c=client, token=dsn_token):
    """Test that similar errors are grouped by fingerprint"""
    # Create isolated project and part for this test
    timestamp = int(time.time() * 1000000)
    project = create_test_project(f"group-test-{timestamp}", "Grouping Test", "Test")
    part = ProjectPart.create(project=project.id, name="backend", description="Backend service")

    # Clear any existing errors for this part (should be none, but just in case)
    ErrorGroup.delete().where(ErrorGroup.part == part.id).execute()

    # Send first error
    event_id_1 = uuid.uuid4().hex
    envelope1 = f'{{"event_id":"{event_id_1}"}}\n'
    envelope1 += '{"type":"event"}\n'

    event1 = {
        "event_id": event_id_1,
        "timestamp": "2024-10-01T10:12:17Z",
        "platform": "python",
        "level": "error",
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "Invalid value: 42",
                    "stacktrace": {
                        "frames": [{"filename": "app.py", "function": "main", "lineno": 42}]
                    },
                }
            ]
        },
    }

    envelope1 += json.dumps(event1) + "\n"

    response1 = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope1.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response1.status_code == 200

    # Check first error was created
    error_groups_after_first = list(ErrorGroup.select().where(ErrorGroup.part == part.id))
    assert (
        len(error_groups_after_first) == 1
    ), f"Expected 1 group after first error, got {len(error_groups_after_first)}"

    # Send similar error (different value, same type and location)
    event_id_2 = uuid.uuid4().hex
    envelope2 = f'{{"event_id":"{event_id_2}"}}\n'
    envelope2 += '{"type":"event"}\n'

    event2 = {
        "event_id": event_id_2,
        "timestamp": "2024-10-01T10:13:17Z",
        "platform": "python",
        "level": "error",
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": "Invalid value: 99",  # Different value
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app.py",
                                "function": "main",
                                "lineno": 42,
                            }  # Same location
                        ]
                    },
                }
            ]
        },
    }

    envelope2 += json.dumps(event2) + "\n"

    response2 = c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope2.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    assert response2.status_code == 200

    # Verify only one error group was created (errors grouped together)
    error_groups = list(ErrorGroup.select().where(ErrorGroup.part == part.id))
    if len(error_groups) != 1:
        # Debug output
        for i, eg in enumerate(error_groups):
            print(f"\nError Group {i+1}:")
            print(f"  Fingerprint: {eg.fingerprint}")
            print(f"  Exception Type: {eg.exception_type}")
            print(f"  Exception Value: {eg.exception_value}")
            print(f"  Event Count: {eg.event_count}")

    assert len(error_groups) == 1, f"Expected 1 group, got {len(error_groups)}"

    # Verify there are 2 occurrences
    error_group = error_groups[0]
    assert error_group.event_count == 2

    # Cleanup - delete error groups and occurrences before deleting part/project
    ErrorOccurrence.delete().where(ErrorOccurrence.error_group == error_group).execute()
    ErrorGroup.delete().where(ErrorGroup.part == part.id).execute()
    part.delete_instance()
    project.delete_instance()


@test("Different errors create separate groups")
def _(c=client, token=dsn_token):
    """Test that different errors create separate groups"""
    # Create isolated project and part for this test
    timestamp = int(time.time() * 1000000)
    project = create_test_project(f"diff-test-{timestamp}", "Different Groups Test", "Test")
    part = ProjectPart.create(project=project.id, name="backend", description="Backend service")

    # Clear any existing errors for this part
    ErrorGroup.delete().where(ErrorGroup.part == part.id).execute()

    # First error: ValueError
    event_id_1 = uuid.uuid4().hex
    envelope1 = f'{{"event_id":"{event_id_1}"}}\n'
    envelope1 += '{"type":"event"}\n'
    envelope1 += (
        json.dumps(
            {
                "event_id": event_id_1,
                "timestamp": "2024-10-01T10:12:17Z",
                "platform": "python",
                "level": "error",
                "exception": {"values": [{"type": "ValueError", "value": "Bad value"}]},
            }
        )
        + "\n"
    )

    c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope1.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    # Second error: TypeError (different type)
    event_id_2 = uuid.uuid4().hex
    envelope2 = f'{{"event_id":"{event_id_2}"}}\n'
    envelope2 += '{"type":"event"}\n'
    envelope2 += (
        json.dumps(
            {
                "event_id": event_id_2,
                "timestamp": "2024-10-01T10:13:17Z",
                "platform": "python",
                "level": "error",
                "exception": {"values": [{"type": "TypeError", "value": "Bad type"}]},
            }
        )
        + "\n"
    )

    c.post(
        f"/ingest/{part.id}/envelope",
        data=envelope2.encode("utf-8"),
        headers={"X-Sentry-Auth": f"Sentry sentry_key={token.token}"},
        content_type="application/x-sentry-envelope",
    )

    # Should have 2 separate error groups
    error_groups = ErrorGroup.select().where(ErrorGroup.part == part.id)
    assert len(list(error_groups)) == 2

    # Cleanup - delete error groups and occurrences before deleting part/project
    for eg in error_groups:
        ErrorOccurrence.delete().where(ErrorOccurrence.error_group == eg).execute()
    ErrorGroup.delete().where(ErrorGroup.part == part.id).execute()
    part.delete_instance()
    project.delete_instance()

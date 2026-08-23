"""Unit tests for error markdown export (no agent token)."""

from ward import test

from app.utils.error_markdown import error_payload_to_markdown


@test("error markdown includes exception, frames, and locals")
def _():
    md = error_payload_to_markdown(
        {
            "id": 42,
            "status": "unresolved",
            "exception_type": "TypeError",
            "exception_value": "NoneType is not callable",
            "culprit": "handlers.py in run",
            "platform": "python",
            "environment": "production",
            "release": "1.2.3",
            "fingerprint": "abc",
            "event_count": 2,
            "first_seen": 1_700_000_000,
            "last_seen": 1_700_000_100,
            "part": {"id": 1, "name": "api"},
            "ticket": None,
            "tags": {"browser": "Chrome"},
            "contexts": {"os": {"name": "Linux", "version": "6.1"}},
            "extra": {"request_id": "r1"},
            "stacktrace": {
                "frames": [
                    {
                        "filename": "handlers.py",
                        "function": "run",
                        "lineno": 9,
                        "in_app": True,
                        "pre_context": ["def run():"],
                        "context_line": "fn()",
                        "post_context": ["return"],
                        "vars": {"fn": None},
                    }
                ]
            },
            "occurrences": [{"timestamp": 1_700_000_100, "event_id": "evt1"}],
        }
    )
    assert "# TypeError" in md
    assert "NoneType is not callable" in md
    assert "**Part:** `api`" in md
    assert "handlers.py:9" in md
    assert " (in-app)" in md
    assert ">  9 | fn()" in md
    assert "`fn`: `null`" in md
    assert "**os:** Linux 6.1" in md
    assert "Chrome" in md
    assert "r1" in md
    assert "evt1" in md
    assert "Bearer" not in md


@test("compact stacktrace omits locals")
def _():
    from app.utils.error_markdown import compact_stacktrace_text

    text = compact_stacktrace_text(
        {
            "frames": [
                {
                    "filename": "handlers.py",
                    "function": "run",
                    "lineno": 9,
                    "context_line": "fn()",
                    "vars": {"password": "secret"},
                }
            ]
        }
    )
    assert "handlers.py:9" in text
    assert "fn()" in text
    assert "password" not in text
    assert "secret" not in text


@test("error markdown handles missing stacktrace")
def _():
    md = error_payload_to_markdown(
        {
            "id": 1,
            "status": "ignored",
            "exception_type": "Error",
            "exception_value": "",
            "event_count": 0,
            "part": None,
            "ticket": None,
            "tags": {},
            "contexts": {},
            "stacktrace": None,
            "occurrences": [],
        }
    )
    assert "No stacktrace available." in md
    assert "No occurrences recorded." in md
    assert "_(no message)_" in md

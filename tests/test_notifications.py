"""Tests for notification utilities."""

from unittest.mock import patch
from ward import test


@test("Slack dispatch rejects non-HTTPS webhook URLs")
def _():
    from app.utils.notifications import _dispatch_slack

    with patch("app.utils.notifications.requests.post") as mock_post:
        try:
            _dispatch_slack({"event_type": "test"}, "file:///etc/passwd")
            assert False, "Expected ValueError for unsupported webhook scheme"
        except ValueError as exc:
            assert "https" in str(exc).lower()

        assert mock_post.called is False


@test("Slack dispatch allows HTTPS webhook URLs")
def _():
    from app.utils.notifications import _dispatch_slack

    with patch("app.utils.notifications.requests.post") as mock_post:
        mock_response = mock_post.return_value
        mock_response.raise_for_status = lambda: None

        _dispatch_slack(
            {"event_type": "test"},
            "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX",
        )

        assert mock_post.called is True

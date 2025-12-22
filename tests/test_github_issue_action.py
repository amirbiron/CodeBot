"""
Tests for GitHub Issue Action
"""

import pytest
from unittest.mock import AsyncMock, patch

from services.github_issue_action import GitHubIssueAction


class TestGitHubIssueAction:
    """בדיקות ל-GitHub Issue Action."""

    @pytest.fixture
    def action(self):
        return GitHubIssueAction(token="test_token", repo="test/repo")

    @pytest.fixture
    def sample_alert(self):
        return {
            "alert_type": "error",
            "service_name": "api-gateway",
            "environment": "production",
            "error_message": "Connection refused",
            "error_signature": "abc123def456",
            "stack_trace": "Traceback...",
            "error_rate": 0.05,
            "latency_avg_ms": 200,
            "occurrence_count": 1,
            "rule_name": "Test Rule",
        }

    @pytest.fixture
    def sample_action_config(self):
        return {
            "type": "create_github_issue",
            "labels": ["auto-generated", "bug"],
            "title_template": "🐛 {{service_name}}: {{error_message}}",
        }

    def test_render_template(self, action):
        template = "Error in {{service_name}}: {{error_message}}"
        data = {"service_name": "api", "error_message": "timeout"}

        result = action._render_template(template, data)

        assert result == "Error in api: timeout"

    def test_render_template_preserves_long_values_by_default(self, action):
        """ודא שערכים ארוכים נשמרים בגוף (stack trace וכו')."""
        template = "{{stack_trace}}"
        long_trace = "x" * 5000
        data = {"stack_trace": long_trace}

        result = action._render_template(template, data)

        assert result == long_trace  # לא מקוצר!
        assert len(result) == 5000

    def test_render_template_truncates_when_requested(self, action):
        """ודא שקיצור עובד כשמתבקש (לכותרות)."""
        template = "{{error_message}}"
        data = {"error_message": "x" * 200}

        result = action._render_template(template, data, truncate_long_values=True, max_length=100)

        assert len(result) == 100  # 97 + "..."
        assert result.endswith("...")

    def test_build_issue_body(self, action, sample_action_config, sample_alert):
        triggered = ["is_new_error eq true", "environment eq production"]

        body = action._build_issue_body(sample_action_config, sample_alert, triggered)

        assert "api-gateway" in body
        assert "Connection refused" in body
        assert "abc123def456" in body
        assert "✅" in body  # triggered conditions

    @pytest.mark.asyncio
    async def test_execute_creates_issue(self, action, sample_action_config, sample_alert):
        with patch("aiohttp.ClientSession") as mock_session:
            # Mock session as async context manager
            from unittest.mock import MagicMock

            session = MagicMock()
            mock_session.return_value = session
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)

            # Mock search response (no existing issues)
            search_resp = AsyncMock()
            search_resp.status = 200
            search_resp.json = AsyncMock(return_value={"total_count": 0})
            search_ctx = AsyncMock()
            search_ctx.__aenter__.return_value = search_resp
            search_ctx.__aexit__ = AsyncMock(return_value=None)
            session.get = MagicMock(return_value=search_ctx)

            # Mock create issue response
            create_resp = AsyncMock()
            create_resp.status = 201
            create_resp.json = AsyncMock(
                return_value={"number": 42, "html_url": "https://github.com/test/repo/issues/42"}
            )
            create_ctx = AsyncMock()
            create_ctx.__aenter__.return_value = create_resp
            create_ctx.__aexit__ = AsyncMock(return_value=None)
            session.post = MagicMock(return_value=create_ctx)

            result = await action.execute(sample_action_config, sample_alert, [])

            assert result["success"] is True
            assert result["issue_number"] == 42

    @pytest.mark.asyncio
    async def test_execute_without_token(self):
        action = GitHubIssueAction(token="", repo="test/repo")

        result = await action.execute({}, {}, [])

        assert result["success"] is False
        assert "token" in result["error"].lower()


class TestErrorSignature:
    """בדיקות לחישוב חתימת שגיאה."""

    def test_compute_signature_consistency(self):
        from monitoring.alerts_storage import compute_error_signature

        error1 = {
            "error_type": "ConnectionError",
            "file": "api.py",
            "line": 42,
            "stack_trace": "Line 1\nLine 2\nLine 3",
        }

        sig1 = compute_error_signature(error1)
        sig2 = compute_error_signature(error1)

        assert sig1 == sig2  # Same input = same signature

    def test_different_errors_different_signatures(self):
        from monitoring.alerts_storage import compute_error_signature

        error1 = {"error_type": "ConnectionError", "file": "api.py"}
        error2 = {"error_type": "TimeoutError", "file": "api.py"}

        assert compute_error_signature(error1) != compute_error_signature(error2)


"""בדיקות ל-services/claude_dispatch_service.py.

מחליפים את ‎http_async.request‎ בכפול אסינכרוני, כדי לבדוק את הטיפול בסטטוסים
ובשגיאות בלי לגעת ברשת.
"""

import json

import pytest

from services import claude_dispatch_service as dispatch


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """קונפיג מינימלי תקין לכל טסט; טסטים בודדים משנים אותו."""
    monkeypatch.setenv("CLAUDE_DISPATCH_ENABLED", "true")
    monkeypatch.setenv("CLAUDE_DISPATCH_REPO", "owner/repo")
    monkeypatch.setenv("CLAUDE_DISPATCH_TOKEN", "ghp_test_token")
    monkeypatch.setenv("CLAUDE_TASK_LABEL", "claude-task")


class _FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status = status
        self._payload = payload if payload is not None else {}
        self._text = text

    async def json(self):
        return self._payload

    async def text(self):
        return self._text


class _FakeRequestContext:
    def __init__(self, response, recorder):
        self._response = response
        self._recorder = recorder

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc_info):
        return False


def _install_fake_request(monkeypatch, response, recorder=None):
    """מחליף את http_async.request. ה-import במודול הוא lazy, אז מספיק לתקן שם."""
    import http_async

    calls = recorder if recorder is not None else []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return _FakeRequestContext(response, calls)

    monkeypatch.setattr(http_async, "request", fake_request)
    return calls


# ── בניית ה-Issue ──────────────────────────────────────────────────────────

class TestIssueBuilders:
    def test_title_uses_first_line_only(self):
        title = dispatch.build_issue_title("שורה ראשונה\nשורה שנייה")
        assert title == "[claude] שורה ראשונה"
        assert "\n" not in title

    def test_title_is_truncated(self):
        title = dispatch.build_issue_title("א" * 200)
        assert len(title) <= dispatch.MAX_TITLE_LEN + len("[claude] ")

    def test_title_falls_back_when_empty(self):
        assert "משימה מטלגרם" in dispatch.build_issue_title("   ")

    def test_body_mentions_claude_once_on_first_line(self):
        body = dispatch.build_issue_body("תקן את הבאג", {"v": 1, "chat_id": 1})
        assert body.splitlines()[0].strip() == "@claude"
        assert body.count("@claude") == 1

    def test_body_wraps_prompt_in_delimiters(self):
        body = dispatch.build_issue_body("תקן את הבאג", {"v": 1})
        assert "<task-from-telegram>" in body
        assert "</task-from-telegram>" in body

    def test_body_contains_parsable_meta(self):
        meta = {"v": 1, "chat_id": 555, "message_id": 42, "request_id": "abc123"}
        body = dispatch.build_issue_body("משימה", meta)
        assert dispatch.parse_meta(body) == meta

    def test_meta_is_valid_json_inside_html_comment(self):
        body = dispatch.build_issue_body("משימה", {"v": 1, "chat_id": 7})
        raw = body.split(dispatch.META_PREFIX, 1)[1].split("-->", 1)[0].strip()
        assert json.loads(raw)["chat_id"] == 7

    def test_parse_meta_returns_empty_on_garbage(self):
        assert dispatch.parse_meta("<!-- codebot-claude-meta:not-json -->") == {}
        assert dispatch.parse_meta("no meta here") == {}


# ── preflight ──────────────────────────────────────────────────────────────

class TestPreflight:
    @pytest.mark.asyncio
    async def test_disabled_feature_short_circuits(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_DISPATCH_ENABLED", "false")
        calls = _install_fake_request(monkeypatch, _FakeResponse(201))
        result = await dispatch.dispatch_claude_task(
            prompt="משימה", chat_id=1, message_id=2, user_id=3, request_id="r1"
        )
        assert result["success"] is False
        assert calls == []  # לא נגענו ברשת בכלל

    @pytest.mark.asyncio
    async def test_missing_token_short_circuits(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_DISPATCH_TOKEN", "")
        monkeypatch.setenv("GITHUB_TOKEN", "")
        calls = _install_fake_request(monkeypatch, _FakeResponse(201))
        result = await dispatch.dispatch_claude_task(
            prompt="משימה", chat_id=1, message_id=2, user_id=3, request_id="r1"
        )
        assert result["success"] is False
        assert "טוקן" in result["error"]
        assert calls == []

    @pytest.mark.asyncio
    async def test_missing_repo_short_circuits(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_DISPATCH_REPO", "")
        monkeypatch.setenv("GITHUB_REPO", "")
        calls = _install_fake_request(monkeypatch, _FakeResponse(201))
        result = await dispatch.dispatch_claude_task(
            prompt="משימה", chat_id=1, message_id=2, user_id=3, request_id="r1"
        )
        assert result["success"] is False
        assert calls == []


# ── dispatch ───────────────────────────────────────────────────────────────

class TestDispatch:
    @pytest.mark.asyncio
    async def test_successful_dispatch(self, monkeypatch):
        response = _FakeResponse(201, {"number": 123, "html_url": "https://gh/issues/123"})
        calls = _install_fake_request(monkeypatch, response)

        result = await dispatch.dispatch_claude_task(
            prompt="תקן את הבאג", chat_id=555, message_id=42, user_id=555, request_id="abc123"
        )

        assert result == {
            "success": True,
            "issue_number": 123,
            "issue_url": "https://gh/issues/123",
        }
        assert calls[0]["method"] == "POST"
        assert calls[0]["url"].endswith("/repos/owner/repo/issues")

    @pytest.mark.asyncio
    async def test_dispatch_sends_label_and_meta(self, monkeypatch):
        calls = _install_fake_request(monkeypatch, _FakeResponse(201, {"number": 1}))
        await dispatch.dispatch_claude_task(
            prompt="תקן את הבאג", chat_id=555, message_id=42, user_id=555, request_id="abc123"
        )
        payload = calls[0]["json"]
        assert payload["labels"] == ["claude-task"]
        meta = dispatch.parse_meta(payload["body"])
        assert meta["chat_id"] == 555
        assert meta["message_id"] == 42
        assert meta["request_id"] == "abc123"

    @pytest.mark.asyncio
    async def test_authorization_header_uses_token(self, monkeypatch):
        calls = _install_fake_request(monkeypatch, _FakeResponse(201, {"number": 1}))
        await dispatch.dispatch_claude_task(
            prompt="משימה כלשהי", chat_id=1, message_id=2, user_id=3, request_id="r"
        )
        assert calls[0]["headers"]["Authorization"] == "token ghp_test_token"

    @pytest.mark.parametrize(
        "status,expected",
        [(401, "401"), (403, "403"), (404, "404"), (422, "422")],
    )
    @pytest.mark.asyncio
    async def test_api_errors_are_reported(self, monkeypatch, status, expected):
        _install_fake_request(monkeypatch, _FakeResponse(status, text="boom"))
        result = await dispatch.dispatch_claude_task(
            prompt="משימה כלשהי", chat_id=1, message_id=2, user_id=3, request_id="r"
        )
        assert result["success"] is False
        assert expected in result["error"]

    @pytest.mark.asyncio
    async def test_error_does_not_leak_token(self, monkeypatch):
        _install_fake_request(monkeypatch, _FakeResponse(403, text="ghp_test_token rejected"))
        result = await dispatch.dispatch_claude_task(
            prompt="משימה כלשהי", chat_id=1, message_id=2, user_id=3, request_id="r"
        )
        assert "ghp_test_token" not in result["error"]

    @pytest.mark.asyncio
    async def test_network_exception_is_caught(self, monkeypatch):
        import http_async

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(http_async, "request", boom)
        result = await dispatch.dispatch_claude_task(
            prompt="משימה כלשהי", chat_id=1, message_id=2, user_id=3, request_id="r"
        )
        assert result["success"] is False
        assert "network down" in result["error"]


# ── קריאות עזר ─────────────────────────────────────────────────────────────

class TestQueries:
    @pytest.mark.asyncio
    async def test_last_bot_comment_picks_latest_bot(self, monkeypatch):
        comments = [
            {"body": "human first", "user": {"type": "User"}, "html_url": "u1"},
            {"body": "bot early", "user": {"type": "Bot"}, "html_url": "b1"},
            {"body": "bot latest", "user": {"type": "Bot"}, "html_url": "b2"},
            {"body": "human last", "user": {"type": "User"}, "html_url": "u2"},
        ]
        _install_fake_request(monkeypatch, _FakeResponse(200, comments))
        result = await dispatch.get_last_bot_comment(5)
        assert result["body"] == "bot latest"
        assert result["url"] == "b2"

    @pytest.mark.asyncio
    async def test_last_bot_comment_when_none(self, monkeypatch):
        _install_fake_request(monkeypatch, _FakeResponse(200, []))
        result = await dispatch.get_last_bot_comment(5)
        assert result["success"] is True
        assert result["body"] == ""

    @pytest.mark.asyncio
    async def test_find_pr_extracts_url(self, monkeypatch):
        comments = [
            {
                "body": "פתחתי PR: https://github.com/owner/repo/pull/45 בהצלחה",
                "user": {"type": "Bot"},
                "html_url": "b1",
            }
        ]
        _install_fake_request(monkeypatch, _FakeResponse(200, comments))
        assert await dispatch.find_pr_for_issue(5) == "https://github.com/owner/repo/pull/45"

    @pytest.mark.asyncio
    async def test_find_pr_returns_none_when_absent(self, monkeypatch):
        _install_fake_request(
            monkeypatch, _FakeResponse(200, [{"body": "אין PR", "user": {"type": "Bot"}}])
        )
        assert await dispatch.find_pr_for_issue(5) is None

    @pytest.mark.asyncio
    async def test_find_workflow_run_matches_by_name(self, monkeypatch):
        payload = {
            "workflow_runs": [
                {"name": "CI/CD Pipeline", "id": 1, "html_url": "u1"},
                {"name": "Claude Code", "id": 2, "html_url": "u2", "status": "in_progress"},
            ]
        }
        _install_fake_request(monkeypatch, _FakeResponse(200, payload))
        run = await dispatch.find_workflow_run_for_issue(5)
        assert run["run_id"] == 2
        assert run["run_url"] == "u2"

    @pytest.mark.asyncio
    async def test_find_workflow_run_returns_none_when_missing(self, monkeypatch):
        _install_fake_request(monkeypatch, _FakeResponse(200, {"workflow_runs": []}))
        assert await dispatch.find_workflow_run_for_issue(5) is None

    @pytest.mark.asyncio
    async def test_cancel_closes_issue(self, monkeypatch):
        calls = _install_fake_request(monkeypatch, _FakeResponse(200, {"state": "closed"}))
        result = await dispatch.cancel_claude_task(9)
        assert result["success"] is True
        assert calls[0]["method"] == "PATCH"
        assert calls[0]["json"]["state"] == "closed"

    @pytest.mark.asyncio
    async def test_follow_up_posts_comment(self, monkeypatch):
        calls = _install_fake_request(monkeypatch, _FakeResponse(201, {"html_url": "c1"}))
        result = await dispatch.add_follow_up(9, "עוד משימה")
        assert result["success"] is True
        assert calls[0]["url"].endswith("/repos/owner/repo/issues/9/comments")
        assert calls[0]["json"]["body"].startswith("@claude")

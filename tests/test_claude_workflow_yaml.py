"""בדיקות ל-.github/workflows/claude.yml.

טסט זול שמגן על ההגדרות שקל לשבור בטעות ושהמחיר שלהן גבוה:
טריגר מסוכן, לולאה אינסופית, ריצה בלי timeout, או ביטול הודעת הסיום.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "claude.yml"


@pytest.fixture(scope="module")
def workflow():
    assert WORKFLOW_PATH.exists(), "חסר .github/workflows/claude.yml"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def raw():
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def triggers(workflow):
    # PyYAML מפרש את המפתח "on" כבוליאני True
    return workflow.get("on") or workflow.get(True)


class TestTriggers:
    def test_only_issue_events(self, triggers):
        assert set(triggers) == {"issues", "issue_comment"}
        assert triggers["issues"]["types"] == ["opened"]
        assert triggers["issue_comment"]["types"] == ["created"]

    def test_no_pull_request_target(self, triggers):
        """pull_request_target חושף secrets ל-forks — אסור כאן."""
        assert "pull_request_target" not in triggers

    def test_concurrency_is_per_issue(self, workflow):
        group = workflow["concurrency"]["group"]
        assert "github.event.issue.number" in group


class TestGuard:
    def test_guard_requires_label_and_mention(self, workflow):
        condition = workflow["jobs"]["guard"]["if"]
        assert "@claude" in condition
        assert "claude-task" in condition

    def test_guard_blocks_bots(self, workflow):
        """בלי זה התגובה של Claude מפעילה את ה-workflow שוב, בלולאה."""
        condition = workflow["jobs"]["guard"]["if"]
        assert "github.event.sender.type != 'Bot'" in condition
        assert "[bot]" in condition

    def test_guard_checks_author_permission(self, raw):
        assert "getCollaboratorPermissionLevel" in raw

    def test_guard_outputs_chat_id(self, workflow):
        outputs = workflow["jobs"]["guard"]["outputs"]
        assert "chat_id" in outputs
        assert "allowed" in outputs

    def test_meta_chat_id_is_validated_against_secret(self, raw):
        """chat_id מגוף ה-Issue לא נאמן בלי אימות מול הסוד."""
        assert "FALLBACK_CHAT_ID" in raw
        assert "chat_id mismatch" in raw


class TestClaudeJob:
    def test_has_timeout(self, workflow):
        assert workflow["jobs"]["claude"]["timeout-minutes"] > 0

    def test_gated_on_guard(self, workflow):
        assert workflow["jobs"]["claude"]["needs"] == "guard"
        assert "needs.guard.outputs.allowed == 'true'" in workflow["jobs"]["claude"]["if"]

    def test_uses_claude_action(self, raw):
        assert "anthropics/claude-code-action" in raw

    def test_permissions_are_scoped(self, workflow):
        permissions = workflow["jobs"]["claude"]["permissions"]
        assert permissions["contents"] == "write"
        assert permissions["pull-requests"] == "write"

    def test_top_level_permissions_are_read_only(self, workflow):
        assert workflow["permissions"] == {"contents": "read"}


class TestNotifications:
    def test_result_runs_even_on_failure(self, workflow):
        condition = workflow["jobs"]["notify-result"]["if"]
        assert condition.startswith("always()")

    def test_result_needs_claude(self, workflow):
        assert set(workflow["jobs"]["notify-result"]["needs"]) == {"guard", "claude"}

    def test_start_notification_exists(self, workflow):
        assert "notify-start" in workflow["jobs"]

    def test_messages_are_sent_without_parse_mode(self, raw):
        """MarkdownV2 נשבר על תשובות אמיתיות של Claude ומאבד את ההודעה."""
        code = "\n".join(
            line for line in raw.splitlines() if not line.lstrip().startswith("#")
        )
        assert "parse_mode" not in code

    def test_reply_threading_allows_missing_message(self, raw):
        assert "allow_sending_without_reply" in raw

    def test_payload_is_built_with_jq(self, raw):
        """jq --arg מונע injection דרך תוכן ההודעה."""
        assert "jq -nc" in raw


class TestSecrets:
    def test_no_hardcoded_tokens(self, raw):
        for marker in ("ghp_", "sk-ant-", "github_pat_"):
            assert marker not in raw

    def test_secrets_come_from_context(self, raw):
        assert "secrets.ANTHROPIC_API_KEY" in raw
        assert "secrets.BOT_TOKEN" in raw

import types
import pytest
from datetime import datetime, timedelta


class _StubPR:
    def __init__(self, updated_at, state="open", merged=False, created_at=None, url_id=1):
        self.updated_at = updated_at
        self.state = state
        self.merged = merged
        self.created_at = created_at or updated_at
        self.html_url = f"https://example.com/pr/{url_id}"
        self.title = f"PR {url_id}"


class _StubIssue:
    def __init__(self, updated_at, state="open", created_at=None, url_id=1, is_pr=False):
        self.updated_at = updated_at
        self.state = state
        self.created_at = created_at or updated_at
        self.html_url = f"https://example.com/issue/{url_id}"
        self.title = f"Issue {url_id}"
        self.pull_request = {} if is_pr else None


class _StubRepo:
    def __init__(self, pulls_list, issues_list):
        self._pulls = pulls_list
        self._issues = issues_list

    def get_pulls(self, state="all", sort="updated", direction="desc"):
        return list(self._pulls)

    def get_issues(self, state="all", sort="updated", direction="desc"):
        return list(self._issues)


class _StubGithub:
    def __init__(self, repo):
        self._repo = repo

    def get_repo(self, name):
        return self._repo


class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)


class _App:
    def __init__(self):
        self.user_data = {}


@pytest.mark.asyncio
async def test_breaks_when_updated_is_none(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    uid = 42
    session = handler.get_user_session(uid)
    session["selected_repo"] = "o/r"
    session["github_token"] = "x"

    # First run baseline
    bot = _Bot()
    app = _App()
    ctx = types.SimpleNamespace(application=app, bot=bot, user_data={})

    # Set last pr baseline in session to a known time in past
    # by running once with force (will set baseline without sending)
    await handler._notifications_job(ctx, user_id=uid, force=True)

    # Now feed pulls/issues where first item has updated_at=None
    pulls = [_StubPR(updated_at=None, url_id=1)]
    issues = [_StubIssue(updated_at=None, url_id=1)]
    repo = _StubRepo(pulls, issues)
    monkeypatch.setattr(gh, "Github", lambda tok: _StubGithub(repo))

    await handler._notifications_job(ctx, user_id=uid, force=True)

    # Should not attempt to send messages due to break on None
    assert bot.sent == []

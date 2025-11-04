import types
import pytest
from datetime import datetime, timedelta, timezone


class _StubPR:
    def __init__(self, state, merged, created_at, updated_at, html_url, title):
        self.state = state
        self.merged = merged
        self.created_at = created_at
        self.updated_at = updated_at
        self.html_url = html_url
        self.title = title


class _StubIssue:
    def __init__(self, state, created_at, updated_at, html_url, title, is_pr=False):
        self.state = state
        self.created_at = created_at
        self.updated_at = updated_at
        self.html_url = html_url
        self.title = title
        # PyGithub marks PR-issues via pull_request attr
        self.pull_request = {} if is_pr else None


class _StubRepo:
    def __init__(self, pulls_holder, issues_holder):
        self._pulls_holder = pulls_holder
        self._issues_holder = issues_holder

    def get_pulls(self, state="all", sort="updated", direction="desc"):
        return list(self._pulls_holder["list"])  # slicing-safe

    def get_issues(self, state="all", sort="updated", direction="desc"):
        return list(self._issues_holder["list"])  # iterable


class _StubGithub:
    def __init__(self, token, repo):
        self._token = token
        self._repo = repo

    def get_repo(self, repo_name):
        return self._repo


class _StubBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, parse_mode=None, disable_web_page_preview=None):
        self.sent.append({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        })


class _StubApp:
    def __init__(self):
        self.user_data = {}


@pytest.mark.asyncio
async def test_notifications_job_handles_naive_datetimes_and_sends_messages(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    user_id = 123

    # Prepare session with repo and token
    session = handler.get_user_session(user_id)
    session["selected_repo"] = "owner/name"
    session["github_token"] = "t0ken"

    # Holders for dynamic lists between runs
    pulls_holder = {"list": []}
    issues_holder = {"list": []}
    stub_repo = _StubRepo(pulls_holder, issues_holder)

    # Patch Github factory to return our stub repo
    monkeypatch.setattr(gh, "Github", lambda token: _StubGithub(token, stub_repo))

    # Build context with bot and application
    bot = _StubBot()
    app = _StubApp()
    ctx = types.SimpleNamespace(application=app, bot=bot, user_data={})

    # First run (baseline set, nothing sent)
    await handler._notifications_job(ctx, user_id=user_id, force=True)
    assert bot.sent == []

    # Second run with naive datetimes later than baseline
    future_naive = datetime.utcnow() + timedelta(minutes=1)
    # PR: created == updated -> should yield status "נפתח"
    pr_open_created = future_naive
    pr_open_updated = future_naive
    pulls_holder["list"] = [
        _StubPR(
            state="open",
            merged=False,
            created_at=pr_open_created,  # naive
            updated_at=pr_open_updated,  # naive
            html_url="https://example.com/pr/1",
            title="PR one",
        )
    ]

    # Issue: created < updated -> should yield status "עודכן"
    issue_created = future_naive - timedelta(minutes=5)
    issue_updated = future_naive
    issues_holder["list"] = [
        _StubIssue(
            state="open",
            created_at=issue_created,  # naive
            updated_at=issue_updated,  # naive
            html_url="https://example.com/issue/1",
            title="Issue one",
            is_pr=False,
        )
    ]

    await handler._notifications_job(ctx, user_id=user_id, force=True)

    # Validate one combined message with both PR and Issue lines
    assert len(bot.sent) == 1
    text = bot.sent[0]["text"]
    assert "PR נפתח" in text
    assert "Issue עודכן" in text


@pytest.mark.asyncio
async def test_to_utc_aware_normalizes_naive_and_preserves_aware():
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    naive_dt = datetime.utcnow()
    aware_dt = datetime.now(timezone.utc)

    norm_naive = handler._to_utc_aware(naive_dt)
    norm_aware = handler._to_utc_aware(aware_dt)

    assert norm_naive is not None and norm_naive.tzinfo is timezone.utc
    assert norm_aware is not None and norm_aware.tzinfo is timezone.utc
    # Same instant when converting aware -> aware
    assert int(norm_aware.timestamp()) == int(aware_dt.timestamp())


@pytest.mark.asyncio
async def test_notifications_job_deduplicates_same_pr_update(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    user_id = 456

    session = handler.get_user_session(user_id)
    session["selected_repo"] = "owner/name"
    session["github_token"] = "tok"

    pulls_holder = {"list": []}
    issues_holder = {"list": []}

    stub_repo = _StubRepo(pulls_holder, issues_holder)
    monkeypatch.setattr(gh, "Github", lambda token: _StubGithub(token, stub_repo))

    bot = _StubBot()
    app = _StubApp()
    ctx = types.SimpleNamespace(application=app, bot=bot, user_data={})

    # Run once to set baseline
    await handler._notifications_job(ctx, user_id=user_id, force=True)

    future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    pr = _StubPR(
        state="open",
        merged=False,
        created_at=future_time - timedelta(minutes=1),
        updated_at=future_time,
        html_url="https://example.com/pr/99",
        title="PR dup",
    )
    pr.number = 99  # PyGithub PRs מספקים שדה מספר
    pulls_holder["list"] = [pr]

    # החזרת קו הבסיס מעט אחורה כדי לדמות מרווח זמן קצר בין ריצות
    session.setdefault("notifications_last", {})["pr"] = future_time - timedelta(minutes=1)

    await handler._notifications_job(ctx, user_id=user_id, force=True)
    assert len(bot.sent) == 1

    # דמיון מצב שבו זמן הבסיס שוב מאחר ביחס ל- updated, ללא שינוי ב-PR
    session["notifications_last"]["pr"] = future_time - timedelta(minutes=1)

    await handler._notifications_job(ctx, user_id=user_id, force=True)
    assert len(bot.sent) == 1


@pytest.mark.asyncio
async def test_notifications_seen_pr_cleanup_handles_mixed_storage(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    user_id = 789

    session = handler.get_user_session(user_id)
    session["selected_repo"] = "owner/name"
    session["github_token"] = "tok"

    seen = session.setdefault("notifications_seen_prs", {})
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    for idx in range(70):
        dt = base + timedelta(minutes=idx)
        key = f"{idx}"
        if idx % 2 == 0:
            seen[key] = dt
        else:
            seen[key] = dt.isoformat()

    session["notifications_last"] = {"pr": datetime.now(timezone.utc) - timedelta(minutes=10)}

    pulls_holder = {"list": []}
    issues_holder = {"list": []}
    stub_repo = _StubRepo(pulls_holder, issues_holder)
    monkeypatch.setattr(gh, "Github", lambda token: _StubGithub(token, stub_repo))

    bot = _StubBot()
    app = _StubApp()
    ctx = types.SimpleNamespace(application=app, bot=bot, user_data={})

    await handler._notifications_job(ctx, user_id=user_id, force=True)

    seen_after = session.get("notifications_seen_prs", {})
    assert len(seen_after) <= 50
    assert all(isinstance(value, str) for value in seen_after.values())


@pytest.mark.asyncio
async def test_notifications_job_skips_when_already_running(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    user_id = 901

    session = handler.get_user_session(user_id)
    session["selected_repo"] = "owner/name"
    session["github_token"] = "tok"
    session["_notifications_running"] = True

    # Even if Github were called, ensure it resolves to stub
    pulls_holder = {"list": []}
    issues_holder = {"list": []}
    stub_repo = _StubRepo(pulls_holder, issues_holder)
    monkeypatch.setattr(gh, "Github", lambda token: _StubGithub(token, stub_repo))

    bot = _StubBot()
    app = _StubApp()
    ctx = types.SimpleNamespace(application=app, bot=bot, user_data={})

    await handler._notifications_job(ctx, user_id=user_id, force=True)

    assert bot.sent == []
    assert session.get("_notifications_running") is True


@pytest.mark.asyncio
async def test_notifications_job_clears_running_flag_on_success(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    user_id = 902

    session = handler.get_user_session(user_id)
    session["selected_repo"] = "owner/name"
    session["github_token"] = "tok"
    baseline = datetime.now(timezone.utc) - timedelta(minutes=5)
    session["notifications_last"] = {"pr": baseline}

    pulls_holder = {"list": []}
    issues_holder = {"list": []}
    pr_updated = baseline + timedelta(minutes=1)
    pr = _StubPR(
        state="open",
        merged=False,
        created_at=pr_updated - timedelta(minutes=1),
        updated_at=pr_updated,
        html_url="https://example.com/pr/clear",
        title="Needs check",
    )
    pr.number = 77
    pulls_holder["list"] = [pr]
    stub_repo = _StubRepo(pulls_holder, issues_holder)
    monkeypatch.setattr(gh, "Github", lambda token: _StubGithub(token, stub_repo))

    bot = _StubBot()
    app = _StubApp()
    ctx = types.SimpleNamespace(application=app, bot=bot, user_data={})

    await handler._notifications_job(ctx, user_id=user_id, force=True)

    assert "_notifications_running" not in session
    assert len(bot.sent) == 1


class _FixedDateTime(datetime):
    _now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    @classmethod
    def set_now(cls, value: datetime) -> None:
        cls._now = value

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        if tz is None:
            return cls._now.replace(tzinfo=None)
        return cls._now.astimezone(tz)

    @classmethod
    def utcnow(cls):  # type: ignore[override]
        return cls._now.astimezone(timezone.utc).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_notifications_job_pr_update_cooldown(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    user_id = 903

    session = handler.get_user_session(user_id)
    session["selected_repo"] = "owner/name"
    session["github_token"] = "tok"

    pulls_holder = {"list": []}
    issues_holder = {"list": []}

    stub_repo = _StubRepo(pulls_holder, issues_holder)
    monkeypatch.setattr(gh, "Github", lambda token: _StubGithub(token, stub_repo))

    monkeypatch.setattr(gh, "datetime", _FixedDateTime)

    bot = _StubBot()
    app = _StubApp()
    # קבע הגדרות התראות עם מקצב של 120 שניות
    app.user_data[user_id] = {
        "notifications": {
            "enabled": True,
            "interval": 120,
            "pr": True,
            "issues": False,
        }
    }
    ctx = types.SimpleNamespace(application=app, bot=bot, user_data={})

    # Initial baseline run
    _FixedDateTime.set_now(datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc))
    await handler._notifications_job(ctx, user_id=user_id, force=True)

    baseline = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    first_update = baseline + timedelta(minutes=5)
    pr = _StubPR(
        state="open",
        merged=False,
        created_at=first_update - timedelta(minutes=1),
        updated_at=first_update,
        html_url="https://example.com/pr/cooldown",
        title="Cooldown PR",
    )
    pr.number = 100
    pulls_holder["list"] = [pr]

    _FixedDateTime.set_now(first_update + timedelta(seconds=10))
    await handler._notifications_job(ctx, user_id=user_id, force=True)
    assert len(bot.sent) == 1

    # Update within cooldown window (90 שניות לאחר ההודעה הראשונה)
    second_update = first_update + timedelta(seconds=90)
    pr.updated_at = second_update
    _FixedDateTime.set_now(second_update + timedelta(seconds=10))
    await handler._notifications_job(ctx, user_id=user_id, force=True)
    assert len(bot.sent) == 1  # no additional message

    # Update after cooldown (5 דקות לאחר ההודעה הראשונה)
    third_update = first_update + timedelta(minutes=5)
    pr.updated_at = third_update
    _FixedDateTime.set_now(third_update + timedelta(seconds=10))
    await handler._notifications_job(ctx, user_id=user_id, force=True)
    assert len(bot.sent) == 2


@pytest.mark.asyncio
async def test_notifications_job_future_baseline_clamped(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    user_id = 904

    session = handler.get_user_session(user_id)
    session["selected_repo"] = "owner/name"
    session["github_token"] = "tok"

    pulls_holder = {"list": []}
    issues_holder = {"list": []}

    stub_repo = _StubRepo(pulls_holder, issues_holder)
    monkeypatch.setattr(gh, "Github", lambda token: _StubGithub(token, stub_repo))

    monkeypatch.setattr(gh, "datetime", _FixedDateTime)

    bot = _StubBot()
    app = _StubApp()
    app.user_data[user_id] = {
        "notifications": {
            "enabled": True,
            "interval": 120,
            "pr": True,
            "issues": False,
        }
    }
    ctx = types.SimpleNamespace(application=app, bot=bot, user_data={})

    baseline = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    _FixedDateTime.set_now(baseline)
    await handler._notifications_job(ctx, user_id=user_id, force=True)

    future_update = baseline + timedelta(minutes=10)
    pr = _StubPR(
        state="open",
        merged=False,
        created_at=future_update - timedelta(minutes=1),
        updated_at=future_update,
        html_url="https://example.com/pr/future",
        title="Future PR",
    )
    pr.number = 55
    pulls_holder["list"] = [pr]

    now_after = baseline + timedelta(minutes=2)
    _FixedDateTime.set_now(now_after)
    await handler._notifications_job(ctx, user_id=user_id, force=True)

    stored = session.get("notifications_last", {}).get("pr")
    assert stored is not None
    assert stored <= now_after

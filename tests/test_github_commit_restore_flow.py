import types
from datetime import datetime, timezone

import pytest


class DummyMessage:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, **kwargs):
        self.texts.append((text, kwargs))
        return self


class DummyQuery:
    def __init__(self, user_id=1):
        self.message = DummyMessage()
        self.data = ""
        self.from_user = types.SimpleNamespace(id=user_id)
        self.edited_texts = []

    async def edit_message_text(self, text, **kwargs):
        self.edited_texts.append((text, kwargs))
        return self.message

    async def answer(self, *args, **kwargs):
        return None


class DummyUpdate:
    def __init__(self, query=None):
        self.callback_query = query or DummyQuery()
        self.effective_user = types.SimpleNamespace(id=self.callback_query.from_user.id)


class DummyContext:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


def make_commit(sha, message, *, url=None, tree_sha=None):
    author = types.SimpleNamespace(name="Dev", date=datetime(2025, 1, 1, tzinfo=timezone.utc))
    commit = types.SimpleNamespace(message=message, author=author)
    if tree_sha:
        commit.tree = types.SimpleNamespace(sha=tree_sha)
    obj = types.SimpleNamespace(sha=sha, commit=commit)
    if url:
        obj.html_url = url
    return obj


@pytest.mark.asyncio
async def test_restore_commit_menu_uses_branch_and_cache(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = DummyUpdate()
    context = DummyContext()

    session = handler.get_user_session(update.callback_query.from_user.id)
    session["selected_repo"] = "owner/repo"
    context.user_data["browse_ref"] = "feature/x"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    call_counter = {"count": 0}
    commits = [
        make_commit("abc123456789", "Fix bug"),
        make_commit("def987654321", "Add feature"),
    ]

    class FakeRepo:
        default_branch = "main"

        def get_commits(self, sha):
            call_counter["count"] += 1
            assert sha == "feature/x"
            return list(commits)

    class FakeGithub:
        def __init__(self, token):
            self.repo = FakeRepo()

        def get_repo(self, full):
            assert full == "owner/repo"
            return self.repo

    monkeypatch.setattr(gh, "Github", FakeGithub)

    await handler.show_commit_restore_menu(update, context)
    assert context.user_data["restore_commits_branch"] == "feature/x"
    assert call_counter["count"] == 1
    assert any("feature/x" in text for text, _ in update.callback_query.edited_texts)

    # Second call should hit the cache path and avoid another repo call
    await handler.show_commit_restore_menu(update, context)
    assert call_counter["count"] == 1


@pytest.mark.asyncio
async def test_restore_commit_actions_show_details_and_link(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = DummyUpdate()
    context = DummyContext()

    session = handler.get_user_session(update.callback_query.from_user.id)
    session["selected_repo"] = "owner/repo"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    commit_url = "https://example.com/commit/abc123"
    commit_obj = make_commit("abc123456789", "Fix bug", url=commit_url)

    class FakeRepo:
        def get_commit(self, sha):
            assert sha == commit_obj.sha
            return commit_obj

    class FakeGithub:
        def __init__(self, token):
            self.repo = FakeRepo()

        def get_repo(self, full):
            return self.repo

    buttons = []

    def fake_button(*args, **kwargs):
        buttons.append({"args": args, "kwargs": kwargs})
        return (args, kwargs)

    monkeypatch.setattr(gh, "Github", FakeGithub)
    monkeypatch.setattr(gh, "InlineKeyboardButton", fake_button)
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    await handler.show_commit_restore_actions(update, context, commit_obj.sha)

    assert buttons[0]["kwargs"]["url"] == commit_url
    assert "Fix bug" in update.callback_query.edited_texts[-1][0]


@pytest.mark.asyncio
async def test_restore_commit_actions_truncate_long_commit_message(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = DummyUpdate()
    context = DummyContext()

    session = handler.get_user_session(update.callback_query.from_user.id)
    session["selected_repo"] = "owner/repo"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    long_message = "שורה ארוכה מאוד " * 400
    commit_obj = make_commit("abc123456789", long_message, url="https://example.com")

    class FakeRepo:
        def get_commit(self, sha):
            assert sha == commit_obj.sha
            return commit_obj

    class FakeGithub:
        def __init__(self, token):
            pass

        def get_repo(self, full):
            assert full == "owner/repo"
            return FakeRepo()

    monkeypatch.setattr(gh, "Github", FakeGithub)
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    await handler.show_commit_restore_actions(update, context, commit_obj.sha)

    text = update.callback_query.edited_texts[-1][0]
    assert len(text) <= gh.TELEGRAM_SAFE_TEXT_LIMIT
    assert "קוצרה" in text
    assert "שורה ארוכה מאוד" in text


@pytest.mark.asyncio
async def test_restore_commit_actions_truncation_preserves_entities(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = DummyUpdate()
    context = DummyContext()

    session = handler.get_user_session(update.callback_query.from_user.id)
    session["selected_repo"] = "owner/repo"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    long_message = "<" * 2000
    commit_obj = make_commit("abc123456789", long_message, url="https://example.com")

    class FakeRepo:
        def get_commit(self, sha):
            assert sha == commit_obj.sha
            return commit_obj

    class FakeGithub:
        def __init__(self, token):
            pass

        def get_repo(self, full):
            assert full == "owner/repo"
            return FakeRepo()

    monkeypatch.setattr(gh, "Github", FakeGithub)
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    await handler.show_commit_restore_actions(update, context, commit_obj.sha)

    text = update.callback_query.edited_texts[-1][0]
    assert gh.TELEGRAM_TRUNCATION_NOTICE in text
    before_notice, sep, _ = text.partition(gh.TELEGRAM_TRUNCATION_NOTICE)
    assert sep == gh.TELEGRAM_TRUNCATION_NOTICE
    last_amp = before_notice.rfind("&")
    if last_amp != -1:
        assert ";" in before_notice[last_amp:], "HTML entity was cut mid-way before notice"

@pytest.mark.asyncio
async def test_create_branch_from_commit_reports_branch_name(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = DummyUpdate()
    context = DummyContext()

    session = handler.get_user_session(update.callback_query.from_user.id)
    session["selected_repo"] = "owner/repo"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    commit_obj = make_commit("abc123456789", "Fix bug")

    class FakeRepo:
        def __init__(self):
            self.created_refs = []

        def get_commit(self, sha):
            assert sha == commit_obj.sha
            return commit_obj

        def create_git_ref(self, ref, sha):
            self.created_refs.append((ref, sha))

    fake_repo = FakeRepo()

    class FakeGithub:
        def __init__(self, token):
            pass

        def get_repo(self, full):
            assert full == "owner/repo"
            return fake_repo

    monkeypatch.setattr(gh, "Github", FakeGithub)
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    await handler.create_branch_from_commit(update, context, commit_obj.sha)

    assert fake_repo.created_refs[0][0] == "refs/heads/restore-abc1234"
    assert "restore-abc1234" in update.callback_query.edited_texts[-1][0]


@pytest.mark.asyncio
async def test_create_revert_pr_from_commit_uses_selected_branch(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = DummyUpdate()
    context = DummyContext()

    session = handler.get_user_session(update.callback_query.from_user.id)
    session["selected_repo"] = "owner/repo"
    context.user_data["restore_commits_branch"] = "feature/x"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    commit_obj = make_commit("abc123456789", "Fix bug", tree_sha="tree123")

    class FakeRepo:
        default_branch = "main"

        def __init__(self):
            self.pull_args = None
            self.edited_refs = []

        def get_commit(self, sha):
            return commit_obj

        def get_branch(self, name):
            assert name == "feature/x"
            return types.SimpleNamespace(commit=types.SimpleNamespace(sha="baseabc"))

        def create_git_ref(self, ref, sha):
            self.created_ref = (ref, sha)

        def get_git_commit(self, sha):
            return types.SimpleNamespace(sha=sha)

        def get_git_tree(self, sha):
            return types.SimpleNamespace(sha=sha)

        def create_git_commit(self, message, tree, parents):
            self.created_commit = (message, tree.sha, [p.sha for p in parents])
            return types.SimpleNamespace(sha="newsha321")

        def get_git_ref(self, ref):
            class _Ref:
                def __init__(self, outer, name):
                    self.outer = outer
                    self.name = name

                def edit(self, sha, force=False):
                    self.outer.edited_refs.append((self.name, sha, force))

            return _Ref(self, ref)

        def create_pull(self, title, body, head, base):
            self.pull_args = (title, body, head, base)
            return types.SimpleNamespace(html_url="https://example.com/pr/1", number=7)

    fake_repo = FakeRepo()

    class FakeGithub:
        def __init__(self, token):
            pass

        def get_repo(self, full):
            assert full == "owner/repo"
            return fake_repo

    monkeypatch.setattr(gh, "Github", FakeGithub)
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    await handler.create_revert_pr_from_commit(update, context, commit_obj.sha)

    assert fake_repo.pull_args[3] == "feature/x"
    assert "feature/x" in update.callback_query.edited_texts[-1][0]


@pytest.mark.asyncio
async def test_open_pr_from_branch_creates_snapshot_commit_when_needed(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = DummyUpdate()
    context = DummyContext()

    session = handler.get_user_session(update.callback_query.from_user.id)
    session["selected_repo"] = "owner/repo"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    class FakeRepo:
        default_branch = "main"
        owner = types.SimpleNamespace(login="owner")

        def __init__(self):
            self.compare_calls = 0
            self.snapshot_commit = None
            self.pull_args = None
            self.edited_refs = []

        def get_pulls(self, **kwargs):
            return []

        def compare(self, base, head):
            self.compare_calls += 1
            if self.compare_calls == 1:
                return types.SimpleNamespace(ahead_by=0, behind_by=4)
            return types.SimpleNamespace(ahead_by=1, behind_by=0)

        def get_branch(self, name):
            assert name == "main"
            return types.SimpleNamespace(commit=types.SimpleNamespace(sha="base123"))

        def get_git_ref(self, ref):
            assert ref == "heads/restore-abc1234"

            class _Ref:
                def __init__(self, outer):
                    self.outer = outer
                    self.object = types.SimpleNamespace(sha="branch123")

                def edit(self, sha, force=False):
                    self.outer.edited_refs.append((sha, force))
                    self.object.sha = sha

            return _Ref(self)

        def get_commit(self, sha):
            if sha == "branch123":
                return make_commit(sha, "branch", tree_sha="tree-branch")
            if sha == "base123":
                return make_commit(sha, "base", tree_sha="tree-base")
            raise AssertionError(f"unexpected sha {sha}")

        def get_git_commit(self, sha):
            return types.SimpleNamespace(sha=sha)

        def get_git_tree(self, sha):
            return types.SimpleNamespace(sha=sha)

        def create_git_commit(self, message, tree, parents):
            self.snapshot_commit = {
                "message": message,
                "tree": tree.sha,
                "parents": [p.sha for p in parents],
            }
            return types.SimpleNamespace(sha="new-snapshot")

        def create_pull(self, title, body, head, base):
            self.pull_args = (title, body, head, base)
            return types.SimpleNamespace(html_url="https://example.com/pr/9", number=9)

    fake_repo = FakeRepo()

    class FakeGithub:
        def __init__(self, token):
            pass

        def get_repo(self, full):
            assert full == "owner/repo"
            return fake_repo

    monkeypatch.setattr(gh, "Github", FakeGithub)
    monkeypatch.setattr(gh, "InlineKeyboardButton", lambda *a, **k: (a, k))
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", lambda rows: rows)

    await handler.open_pr_from_branch(update, context, "restore-abc1234")

    assert fake_repo.snapshot_commit is not None
    assert fake_repo.snapshot_commit["tree"] == "tree-branch"
    assert fake_repo.snapshot_commit["parents"] == ["base123"]
    assert fake_repo.pull_args == (
        "Restore from checkpoint: restore-abc1234",
        "Automated PR to restore state from branch `restore-abc1234`.\n\nCreated via Telegram bot.\n\n"
        "הבוט יצר commit חדש על גבי `main` כדי לשחזר את תוכן הענף.",
        "restore-abc1234",
        "main",
    )
    assert "נוסף commit שחזור אוטומטי" in update.callback_query.edited_texts[-1][0]


@pytest.mark.asyncio
async def test_open_pr_from_branch_reports_identical_tree_hint(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    update = DummyUpdate()
    context = DummyContext()

    session = handler.get_user_session(update.callback_query.from_user.id)
    session["selected_repo"] = "owner/repo"
    monkeypatch.setattr(handler, "get_user_token", lambda _uid: "token")

    class FakeRepo:
        default_branch = "main"
        owner = types.SimpleNamespace(login="owner")

        def get_pulls(self, **kwargs):
            return []

        def compare(self, base, head):
            assert base == "main"
            assert head == "restore-identical"
            return types.SimpleNamespace(ahead_by=0, behind_by=0)

    class FakeGithub:
        def __init__(self, token):
            pass

        def get_repo(self, full):
            assert full == "owner/repo"
            return FakeRepo()

    def fake_button(*args, **kwargs):
        return (args, kwargs)

    def fake_markup(rows):
        return rows

    monkeypatch.setattr(gh, "Github", FakeGithub)
    monkeypatch.setattr(gh, "InlineKeyboardButton", fake_button)
    monkeypatch.setattr(gh, "InlineKeyboardMarkup", fake_markup)
    handler._ensure_branch_snapshot_commit = lambda *_, **__: (False, "identical_tree")

    await handler.open_pr_from_branch(update, context, "restore-identical")

    text = update.callback_query.edited_texts[-1][0]
    assert "אין שינויים" in text
    assert "זהה כרגע" in text


def test_ensure_snapshot_commit_missing_branch_sha():
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    class FakeRepo:
        def get_git_ref(self, ref):
            class _Ref:
                def __init__(self):
                    self.object = types.SimpleNamespace(sha=None)

            return _Ref()

    created, reason = handler._ensure_branch_snapshot_commit(FakeRepo(), "main", "feature/x")
    assert created is False
    assert reason == "missing_branch_sha"


def test_ensure_snapshot_commit_missing_branch_tree():
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    class FakeRepo:
        def get_git_ref(self, ref):
            class _Ref:
                def __init__(self):
                    self.object = types.SimpleNamespace(sha="branchsha")

            return _Ref()

        def get_commit(self, sha):
            assert sha == "branchsha"
            return make_commit(sha, "branch commit")  # tree attr חסר בכוונה

    created, reason = handler._ensure_branch_snapshot_commit(FakeRepo(), "main", "feature/x")
    assert created is False
    assert reason == "missing_branch_tree"


def test_ensure_snapshot_commit_missing_base_sha():
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    class FakeRepo:
        def get_git_ref(self, ref):
            class _Ref:
                def __init__(self):
                    self.object = types.SimpleNamespace(sha="branchsha")

            return _Ref()

        def get_commit(self, sha):
            assert sha == "branchsha"
            return make_commit(sha, "branch", tree_sha="tree-123")

        def get_branch(self, name):
            assert name == "main"
            return types.SimpleNamespace(commit=types.SimpleNamespace(sha=None))

    created, reason = handler._ensure_branch_snapshot_commit(FakeRepo(), "main", "feature/x")
    assert created is False
    assert reason == "missing_base_sha"


def test_ensure_snapshot_commit_identical_tree():
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    class FakeRepo:
        def get_git_ref(self, ref):
            class _Ref:
                def __init__(self):
                    self.object = types.SimpleNamespace(sha="branchsha")

            return _Ref()

        def get_commit(self, sha):
            if sha == "branchsha":
                return make_commit(sha, "branch", tree_sha="shared-tree")
            if sha == "basesha":
                return make_commit(sha, "base", tree_sha="shared-tree")
            raise AssertionError(f"unexpected sha {sha}")

        def get_branch(self, name):
            assert name == "main"
            return types.SimpleNamespace(commit=types.SimpleNamespace(sha="basesha"))

    created, reason = handler._ensure_branch_snapshot_commit(FakeRepo(), "main", "feature/x")
    assert created is False
    assert reason == "identical_tree"


def test_ensure_snapshot_commit_handles_github_exception(monkeypatch):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    class FakeRepo:
        def get_git_ref(self, ref):
            raise gh.GithubException(500, {"message": "boom"})

    created, reason = handler._ensure_branch_snapshot_commit(FakeRepo(), "main", "feature/x")
    assert created is False
    assert reason == "github_error"


def test_ensure_snapshot_commit_handles_unexpected_exception():
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()

    class FakeRepo:
        def get_git_ref(self, ref):
            raise RuntimeError("unexpected failure")

    created, reason = handler._ensure_branch_snapshot_commit(FakeRepo(), "main", "feature/x")
    assert created is False
    assert reason == "unexpected_error"

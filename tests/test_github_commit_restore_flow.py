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

import io
import sys
import types
import zipfile

import pytest

from handlers import documents as documents_mod


@pytest.fixture
def dummy_db(monkeypatch):
    class _DB:
        def __init__(self):
            self.saved_snippets = []
            self.saved_large_files = []
            self.saved_selected_repo = None

        def save_code_snippet(self, snippet):
            self.saved_snippets.append(snippet)
            return True

        def get_latest_version(self, user_id, file_name):
            return {"_id": "snippet-id"}

        def save_large_file(self, large_file):
            self.saved_large_files.append(large_file)
            return True

        def get_large_file(self, user_id, file_name):
            return {"_id": "large-id"}

        def save_selected_repo(self, user_id, repo_full):
            self.saved_selected_repo = (user_id, repo_full)

    db = _DB()
    monkeypatch.setattr(documents_mod, "db", db, raising=False)
    return db


@pytest.fixture
def dummy_backup(monkeypatch, tmp_path):
    class _Backup:
        def __init__(self, base):
            self.backup_dir = base
            self.saved_bytes = []
            self.restore_calls = []

        def save_backup_bytes(self, data, metadata):
            if getattr(self, "raise_on_save", False):
                raise IOError("cannot save backup")
            self.saved_bytes.append((data, metadata))

        def restore_from_backup(self, **kwargs):
            self.restore_calls.append(kwargs)
            return {"restored_files": 3, "errors": []}

    backup = _Backup(tmp_path)
    monkeypatch.setattr(documents_mod, "backup_manager", backup, raising=False)
    return backup


@pytest.fixture
def handler_env(dummy_db, dummy_backup):
    notifications = []
    events = []
    error_increments = []

    async def notify_admins(context, text):
        notifications.append(text)

    async def log_user_activity(update, context):
        events.append(("log_user_activity", update, context))

    def emit_event(name, **kwargs):
        events.append((name, kwargs))

    class _Errors:
        def labels(self, **kwargs):
            class _Counter:
                def inc(self_inner):
                    error_increments.append(kwargs)

            return _Counter()

    handler = documents_mod.DocumentHandler(
        notify_admins=notify_admins,
        get_reporter=lambda: None,
        log_user_activity=log_user_activity,
        encodings_to_try=("utf-8",),
        emit_event=emit_event,
        errors_total=_Errors(),
    )

    return {
        "handler": handler,
        "notifications": notifications,
        "events": events,
        "errors": error_increments,
        "db": dummy_db,
        "backup": dummy_backup,
    }


class _DummyFile:
    def __init__(self, payload: bytes):
        self._payload = payload

    async def download_to_memory(self, buffer: io.BytesIO):
        buffer.write(self._payload)


class _DummyBot:
    def __init__(self, payload: bytes):
        self._payload = payload
        self.requested = []

    async def get_file(self, file_id: str):
        self.requested.append(file_id)
        return _DummyFile(self._payload)


class _ReplyRecorder:
    def __init__(self):
        self.messages = []

    async def reply_text(self, text, **kwargs):
        self.messages.append((text, kwargs))


def _make_update(doc_kwargs):
    recorder = _ReplyRecorder()

    class _Doc:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    document = _Doc(**doc_kwargs)

    class _Message:
        document = document
        reply_text = recorder.reply_text

    update = types.SimpleNamespace(
        message=_Message(),
        effective_user=types.SimpleNamespace(id=doc_kwargs.get("user_id", 1)),
    )
    return update, recorder


@pytest.mark.asyncio
async def test_handle_document_saves_small_snippet(handler_env):
    payload = b"print('hello world')"
    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "example.py",
        "file_size": len(payload),
        "file_id": "fid-1",
        "mime_type": "text/plain",
    })
    context = types.SimpleNamespace(
        bot=bot,
        user_data={},
        bot_data={},
    )

    await handler_env["handler"].handle_document(update, context)

    assert handler_env["db"].saved_snippets, "קובץ טקסט קטן צריך להישמר כ-CodeSnippet"
    assert any(evt[0] == "file_saved" for evt in handler_env["events"])
    assert replies.messages, "צפויה הודעת הצלחה למשתמש"


@pytest.mark.asyncio
async def test_handle_document_saves_large_file(handler_env):
    payload = ("#" * 5000).encode()
    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "large.py",
        "file_size": len(payload),
        "file_id": "fid-2",
        "mime_type": "text/plain",
    })
    context = types.SimpleNamespace(bot=bot, user_data={}, bot_data={})

    await handler_env["handler"].handle_document(update, context)

    assert handler_env["db"].saved_large_files, "קובץ ארוך צריך להישמר כ-LargeFile"
    assert replies.messages and replies.messages[-1][0], "צפויה הודעת הצלחה לקובץ גדול"


@pytest.mark.asyncio
async def test_handle_document_records_activity_with_reporter(handler_env):
    payload = ("#" * 5000).encode()
    bot = _DummyBot(payload)
    update, _ = _make_update({
        "file_name": "activity.py",
        "file_size": len(payload),
        "file_id": "fid-activity",
        "mime_type": "text/plain",
    })
    context = types.SimpleNamespace(bot=bot, user_data={}, bot_data={})

    reports = []

    class Reporter:
        def report_activity(self, user_id):
            reports.append(user_id)

    handler_env["handler"]._get_reporter = lambda: Reporter()

    await handler_env["handler"].handle_document(update, context)

    assert reports == [1]
    assert handler_env["db"].saved_large_files, "עדיין צריך לשמור כקובץ גדול"


@pytest.mark.asyncio
async def test_handle_document_collects_zip_items(handler_env):
    payload = b"sample"
    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "bundle.txt",
        "file_size": len(payload),
        "file_id": "fid-zip-create",
        "mime_type": "text/plain",
    })
    context = types.SimpleNamespace(
        bot=bot,
        user_data={"upload_mode": "zip_create"},
        bot_data={},
    )

    await handler_env["handler"].handle_document(update, context)

    items = context.user_data.get("zip_create_items")
    assert items and items[0]["filename"] == "bundle.txt"
    assert replies.messages, "צפויה הודעה על הוספת הפריט ל-ZIP"


@pytest.mark.asyncio
async def test_handle_document_waiting_for_github_upload(handler_env):
    class _GH:
        def __init__(self):
            self.called = False

        async def handle_file_upload(self, update, context):
            self.called = True

        def get_user_session(self, user_id):
            return {"selected_repo": "owner/repo"}

        def get_user_token(self, user_id):
            return "token"

    gh = _GH()

    update, _ = _make_update({
        "file_name": "ignore.txt",
        "file_size": 1,
        "file_id": "fid-gh",
        "mime_type": "text/plain",
    })
    context = types.SimpleNamespace(
        bot=_DummyBot(b""),
        user_data={"waiting_for_github_upload": True},
        bot_data={"github_handler": gh},
    )

    await handler_env["handler"].handle_document(update, context)

    assert gh.called, "מצב waiting_for_github_upload אמור להעביר לטיפול GitHub"


@pytest.mark.asyncio
async def test_handle_document_stores_zip_copy(handler_env):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("inner.txt", "content")
    payload = zip_bytes.getvalue()

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "archive.zip",
        "file_size": len(payload),
        "file_id": "fid-zip",
        "mime_type": "application/zip",
    })
    context = types.SimpleNamespace(bot=bot, user_data={}, bot_data={})

    await handler_env["handler"].handle_document(update, context)

    assert handler_env["backup"].saved_bytes, "ZIP צריך להישמר כמטען גיבוי"
    assert any("ZIP" in msg for msg, _ in replies.messages)
    assert not handler_env["errors"], "שמירת ZIP לא אמורה להשפיע על error counters"
    assert not any(evt[0] == "file_read_unreadable" for evt in handler_env["events"] if evt), (
        "לא אמורה לצאת התראה על קובץ לא קריא לאחר שמירת ZIP"
    )


@pytest.mark.asyncio
async def test_handle_document_zip_import_restores_backup(handler_env, monkeypatch):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("metadata.json", "{}")
        zf.writestr("file.txt", "hello")
    payload = zip_bytes.getvalue()

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "import.zip",
        "file_size": len(payload),
        "file_id": "fid-import",
        "mime_type": "application/zip",
    })
    context = types.SimpleNamespace(
        bot=bot,
        user_data={"upload_mode": "zip_import"},
        bot_data={},
    )

    await handler_env["handler"].handle_document(update, context)

    assert handler_env["backup"].restore_calls, "zip_import חייב להפעיל restore_from_backup"
    assert any("✅" in msg for msg, _ in replies.messages)


@pytest.mark.asyncio
async def test_handle_document_github_restore_zip(monkeypatch, handler_env):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("root/file.txt", "hello")
    payload = zip_bytes.getvalue()

    class _Repo:
        def __init__(self):
            self.default_branch = "main"
            self.edited = None
            self.created_blobs = []

        def get_git_ref(self, name):
            class _Ref:
                def __init__(self, outer):
                    self.outer = outer
                    self.object = types.SimpleNamespace(sha="base-sha")

                def edit(self, sha):
                    self.outer.edited = sha

            return _Ref(self)

        def get_git_commit(self, sha):
            return types.SimpleNamespace(tree="base-tree", sha=sha)

        def create_git_blob(self, data, encoding):
            blob = types.SimpleNamespace(sha=f"sha-{len(self.created_blobs)}")
            self.created_blobs.append((data, encoding))
            return blob

        def create_git_tree(self, elements, base_tree=None):
            return types.SimpleNamespace(elements=elements, base_tree=base_tree)

        def create_git_commit(self, message, tree, parents):
            return types.SimpleNamespace(sha="new-sha")

    repo_instance = _Repo()

    class _Github:
        def __init__(self, token):
            self.token = token

        def get_repo(self, repo_full):
            return repo_instance

    class _InputGitTreeElement:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    github_module = types.ModuleType("github")
    github_module.Github = _Github
    github_igte_module = types.ModuleType("github.InputGitTreeElement")
    github_igte_module.InputGitTreeElement = _InputGitTreeElement
    original_github = sys.modules.get("github")
    original_igte = sys.modules.get("github.InputGitTreeElement")
    sys.modules["github"] = github_module
    sys.modules["github.InputGitTreeElement"] = github_igte_module

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "repo.zip",
        "file_size": len(payload),
        "file_id": "fid-gh-restore",
        "mime_type": "application/zip",
    })

    class _GHHandler:
        def get_user_session(self, user_id):
            return {"selected_repo": "owner/repo"}

        def get_user_token(self, user_id):
            return "token"

    context = types.SimpleNamespace(
        bot=bot,
        user_data={"upload_mode": "github_restore_zip_to_repo"},
        bot_data={"github_handler": _GHHandler()},
    )

    try:
        await handler_env["handler"].handle_document(update, context)
    finally:
        if original_github is None:
            sys.modules.pop("github", None)
        else:
            sys.modules["github"] = original_github
        if original_igte is None:
            sys.modules.pop("github.InputGitTreeElement", None)
        else:
            sys.modules["github.InputGitTreeElement"] = original_igte

    assert repo_instance.edited == "new-sha", "Git commit חדש אמור להיכתב ל-branch"
    assert any("שחזור" in msg for msg, _ in replies.messages)


@pytest.mark.asyncio
async def test_handle_document_github_create_repo_empty_repo(monkeypatch, handler_env):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("root/file.txt", "print('hi')")
    payload = zip_bytes.getvalue()

    created_files = []

    class FakeGithubException(Exception):
        pass

    class FakeRepo:
        def __init__(self):
            self.default_branch = "main"
            self.full_name = "owner/generated"

        def create_file(self, path, message, content, branch):
            created_files.append((path, message, content, branch))

        def get_git_ref(self, name):
            raise FakeGithubException("no ref")

        def get_git_commit(self, sha):
            raise FakeGithubException("no commit")

    repo_instance = FakeRepo()

    class FakeUser:
        def create_repo(self, name, private, auto_init):
            return repo_instance

    class FakeGithub:
        def __init__(self, token):
            self.token = token

        def get_user(self):
            return FakeUser()

    class FakeInputGitTreeElement:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    originals = {
        "github": sys.modules.get("github"),
        "github.GithubException": sys.modules.get("github.GithubException"),
        "github.InputGitTreeElement": sys.modules.get("github.InputGitTreeElement"),
    }
    github_module = types.ModuleType("github")
    github_module.Github = FakeGithub
    github_exception_module = types.ModuleType("github.GithubException")
    github_exception_module.GithubException = FakeGithubException
    github_igte_module = types.ModuleType("github.InputGitTreeElement")
    github_igte_module.InputGitTreeElement = FakeInputGitTreeElement

    sys.modules["github"] = github_module
    sys.modules["github.GithubException"] = github_exception_module
    sys.modules["github.InputGitTreeElement"] = github_igte_module

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "root.zip",
        "file_size": len(payload),
        "file_id": "fid-gh-create-empty",
        "mime_type": "application/zip",
    })

    class _GHHandler:
        def get_user_session(self, user_id):
            return {"selected_repo": "owner/previous"}

        def get_user_token(self, user_id):
            return "token"

    context = types.SimpleNamespace(
        bot=bot,
        user_data={"upload_mode": "github_create_repo_from_zip"},
        bot_data={"github_handler": _GHHandler()},
    )

    try:
        await handler_env["handler"].handle_document(update, context)
    finally:
        for name, module in originals.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    assert created_files, "צפויה יצירת קובץ באמצעות Contents API לריפו ריק"
    assert created_files[0][0] == "file.txt"
    assert handler_env["db"].saved_selected_repo == (1, repo_instance.full_name)
    assert any("✅" in msg for msg, _ in replies.messages), "צפויה הודעת הצלחה על יצירת הריפו"
    assert context.user_data.get("upload_mode") is None


@pytest.mark.asyncio
async def test_handle_document_github_create_repo_with_base_commit(monkeypatch, handler_env):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("root/app.py", "print('app')")
        zf.writestr("root/lib.txt", "data")
    payload = zip_bytes.getvalue()

    class FakeGithubException(Exception):
        pass

    class FakeRepo:
        def __init__(self):
            self.default_branch = "main"
            self.full_name = "owner/existing"
            self.blobs = []
            self.last_tree = None
            self.last_commit = None
            self.edited_sha = None

        def create_file(self, *args, **kwargs):
            raise AssertionError("should not call create_file when base commit exists")

        def get_git_ref(self, name):
            repo = self

            class _Ref:
                def __init__(self):
                    self.object = types.SimpleNamespace(sha="base-sha")

                def edit(self_inner, sha):
                    repo.edited_sha = sha

            return _Ref()

        def get_git_commit(self, sha):
            return types.SimpleNamespace(tree="base-tree", sha=sha)

        def create_git_blob(self, data, encoding):
            blob = types.SimpleNamespace(sha=f"blob-{len(self.blobs)}")
            self.blobs.append((data, encoding))
            return blob

        def create_git_tree(self, elements, base_tree):
            self.last_tree = (elements, base_tree)
            return types.SimpleNamespace(sha="tree-sha")

        def create_git_commit(self, message, tree, parents):
            self.last_commit = (message, tree, parents)
            return types.SimpleNamespace(sha="new-sha")

    repo_instance = FakeRepo()

    class FakeUser:
        def create_repo(self, name, private, auto_init):
            return repo_instance

    class FakeGithub:
        def __init__(self, token):
            self.token = token

        def get_user(self):
            return FakeUser()

        def get_repo(self, full_name):
            return repo_instance

    class FakeInputGitTreeElement:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    originals = {
        "github": sys.modules.get("github"),
        "github.GithubException": sys.modules.get("github.GithubException"),
        "github.InputGitTreeElement": sys.modules.get("github.InputGitTreeElement"),
    }
    github_module = types.ModuleType("github")
    github_module.Github = FakeGithub
    github_exception_module = types.ModuleType("github.GithubException")
    github_exception_module.GithubException = FakeGithubException
    github_igte_module = types.ModuleType("github.InputGitTreeElement")
    github_igte_module.InputGitTreeElement = FakeInputGitTreeElement

    sys.modules["github"] = github_module
    sys.modules["github.GithubException"] = github_exception_module
    sys.modules["github.InputGitTreeElement"] = github_igte_module

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "root.zip",
        "file_size": len(payload),
        "file_id": "fid-gh-create-tree",
        "mime_type": "application/zip",
    })

    class _GHHandler:
        def get_user_session(self, user_id):
            return {"selected_repo": "owner/existing"}

        def get_user_token(self, user_id):
            return "token"

    context = types.SimpleNamespace(
        bot=bot,
        user_data={"upload_mode": "github_create_repo_from_zip"},
        bot_data={"github_handler": _GHHandler()},
    )

    try:
        await handler_env["handler"].handle_document(update, context)
    finally:
        for name, module in originals.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    assert repo_instance.edited_sha == "new-sha"
    assert repo_instance.last_tree is not None and repo_instance.last_tree[1] == "base-tree"
    assert len(repo_instance.last_tree[0]) == 2
    assert handler_env["db"].saved_selected_repo == (1, repo_instance.full_name)
    assert any("✅" in msg for msg, _ in replies.messages)
    assert context.user_data.get("upload_mode") is None


@pytest.mark.asyncio
async def test_handle_document_zip_import_invalid_archive(handler_env):
    payload = b"not-a-zip"
    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "bad.zip",
        "file_size": len(payload),
        "file_id": "fid-zip-invalid",
        "mime_type": "application/zip",
    })
    context = types.SimpleNamespace(
        bot=bot,
        user_data={"upload_mode": "zip_import"},
        bot_data={},
    )

    await handler_env["handler"].handle_document(update, context)

    assert handler_env["backup"].restore_calls == []
    assert any("❌" in msg for msg, _ in replies.messages)
    assert context.user_data.get("upload_mode") is None


@pytest.mark.asyncio
async def test_handle_document_zip_import_detects_repo_tag(handler_env):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("owner-repo-main/file.txt", "hello")
    payload = zip_bytes.getvalue()

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "owner-repo-main.zip",
        "file_size": len(payload),
        "file_id": "fid-import-tag",
        "mime_type": "application/zip",
    })
    context = types.SimpleNamespace(
        bot=bot,
        user_data={"upload_mode": "zip_import"},
        bot_data={},
    )

    await handler_env["handler"].handle_document(update, context)

    assert handler_env["backup"].restore_calls
    extra_tags = handler_env["backup"].restore_calls[-1].get("extra_tags")
    assert extra_tags == ["repo:owner/repo"]
    assert any("✅" in msg for msg, _ in replies.messages)


@pytest.mark.asyncio
async def test_handle_document_zip_copy_failure_continues_processing(handler_env):
    handler_env["backup"].raise_on_save = True

    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("inner.txt", "content")
    payload = zip_bytes.getvalue()

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "arch.zip",
        "file_size": len(payload),
        "file_id": "fid-zip-fail",
        "mime_type": "application/zip",
    })
    context = types.SimpleNamespace(bot=bot, user_data={}, bot_data={})

    await handler_env["handler"].handle_document(update, context)

    assert handler_env["backup"].saved_bytes == []
    assert handler_env["errors"], "צפוי אינקרמנט לאחר כישלון קריאת טקסט"
    assert any(
        evt[0] == "file_read_unreadable" for evt in handler_env["events"] if isinstance(evt, tuple) and evt
    )
    assert any("❌" in msg for msg, _ in replies.messages)


@pytest.mark.asyncio
async def test_handle_document_github_restore_zip_fallback_to_current(handler_env):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("root/file.txt", "hello")
    payload = zip_bytes.getvalue()

    class FakeRepo:
        def __init__(self):
            self.default_branch = "main"
            self.edited = None

        def get_git_ref(self, name):
            class _Ref:
                def __init__(self, outer):
                    self.outer = outer
                    self.object = types.SimpleNamespace(sha="base-sha")

                def edit(self_inner, sha):
                    self_inner.outer.edited = sha

            return _Ref(self)

        def get_git_commit(self, sha):
            return types.SimpleNamespace(tree="base-tree", sha=sha)

        def create_git_blob(self, data, encoding):
            return types.SimpleNamespace(sha="blob-sha")

        def create_git_tree(self, elements, base_tree=None):
            return types.SimpleNamespace(sha="tree-sha")

        def create_git_commit(self, message, tree, parents):
            return types.SimpleNamespace(sha="new-sha")

    repo_current = FakeRepo()

    class FakeGithub:
        def __init__(self, token):
            self.token = token

        def get_repo(self, repo_full):
            if repo_full == "owner/expected":
                raise Exception("expected missing")
            if repo_full == "owner/current":
                return repo_current
            raise Exception("unexpected repo")

    class FakeInputGitTreeElement:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    originals = {
        "github": sys.modules.get("github"),
        "github.InputGitTreeElement": sys.modules.get("github.InputGitTreeElement"),
    }
    github_module = types.ModuleType("github")
    github_module.Github = FakeGithub
    github_igte_module = types.ModuleType("github.InputGitTreeElement")
    github_igte_module.InputGitTreeElement = FakeInputGitTreeElement
    sys.modules["github"] = github_module
    sys.modules["github.InputGitTreeElement"] = github_igte_module

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "repo.zip",
        "file_size": len(payload),
        "file_id": "fid-gh-restore-fallback",
        "mime_type": "application/zip",
    })

    class _GHHandler:
        def get_user_session(self, user_id):
            return {"selected_repo": "owner/current"}

        def get_user_token(self, user_id):
            return "token"

    context = types.SimpleNamespace(
        bot=bot,
        user_data={
            "upload_mode": "github_restore_zip_to_repo",
            "zip_restore_expected_repo_full": "owner/expected",
        },
        bot_data={"github_handler": _GHHandler()},
    )

    try:
        await handler_env["handler"].handle_document(update, context)
    finally:
        for name, module in originals.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    assert repo_current.edited == "new-sha"
    assert any("⚠️" in msg for msg, _ in replies.messages)
    assert context.user_data.get("upload_mode") is None


@pytest.mark.asyncio
async def test_handle_document_github_restore_zip_with_purge(handler_env):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("root/file.txt", "hello")
    payload = zip_bytes.getvalue()

    class FakeRepo:
        def __init__(self):
            self.default_branch = "main"
            self.purged = False
            self.edited = None

        def get_git_ref(self, name):
            class _Ref:
                def __init__(self, outer):
                    self.outer = outer
                    self.object = types.SimpleNamespace(sha="base-sha")

                def edit(self_inner, sha):
                    self_inner.outer.edited = sha

            return _Ref(self)

        def get_git_commit(self, sha):
            return types.SimpleNamespace(tree="base-tree", sha=sha)

        def create_git_blob(self, data, encoding):
            return types.SimpleNamespace(sha="blob-sha")

        def create_git_tree(self, elements, base_tree=None):
            if base_tree is None:
                self.purged = True
            return types.SimpleNamespace(sha="tree-sha")

        def create_git_commit(self, message, tree, parents):
            return types.SimpleNamespace(sha="new-sha")

    repo_instance = FakeRepo()

    class FakeGithub:
        def __init__(self, token):
            self.token = token

        def get_repo(self, repo_full):
            if repo_full == "owner/expected":
                return repo_instance
            raise Exception("fallback")

    class FakeInputGitTreeElement:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    originals = {
        "github": sys.modules.get("github"),
        "github.InputGitTreeElement": sys.modules.get("github.InputGitTreeElement"),
    }
    github_module = types.ModuleType("github")
    github_module.Github = FakeGithub
    github_igte_module = types.ModuleType("github.InputGitTreeElement")
    github_igte_module.InputGitTreeElement = FakeInputGitTreeElement
    sys.modules["github"] = github_module
    sys.modules["github.InputGitTreeElement"] = github_igte_module

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "repo.zip",
        "file_size": len(payload),
        "file_id": "fid-gh-restore-purge",
        "mime_type": "application/zip",
    })

    class _GHHandler:
        def __init__(self):
            self.session = {"selected_repo": "owner/current"}

        def get_user_session(self, user_id):
            return self.session

        def get_user_token(self, user_id):
            return "token"

    context = types.SimpleNamespace(
        bot=bot,
        user_data={
            "upload_mode": "github_restore_zip_to_repo",
            "github_restore_zip_purge": True,
            "zip_restore_expected_repo_full": "owner/expected",
        },
        bot_data={"github_handler": _GHHandler()},
    )

    try:
        await handler_env["handler"].handle_document(update, context)
    finally:
        for name, module in originals.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    assert repo_instance.purged is True
    assert repo_instance.edited == "new-sha"
    assert any("⚠️" in msg for msg, _ in replies.messages)


@pytest.mark.asyncio
async def test_handle_document_github_restore_zip_repo_not_accessible(handler_env):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("root/file.txt", "hello")
    payload = zip_bytes.getvalue()

    class FakeGithub:
        def __init__(self, token):
            self.token = token

        def get_repo(self, repo_full):
            raise Exception("not accessible")

    class FakeInputGitTreeElement:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    originals = {
        "github": sys.modules.get("github"),
        "github.InputGitTreeElement": sys.modules.get("github.InputGitTreeElement"),
    }
    github_module = types.ModuleType("github")
    github_module.Github = FakeGithub
    github_igte_module = types.ModuleType("github.InputGitTreeElement")
    github_igte_module.InputGitTreeElement = FakeInputGitTreeElement
    sys.modules["github"] = github_module
    sys.modules["github.InputGitTreeElement"] = github_igte_module

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "repo.zip",
        "file_size": len(payload),
        "file_id": "fid-gh-restore-error",
        "mime_type": "application/zip",
    })

    class _GHHandler:
        def get_user_session(self, user_id):
            return {"selected_repo": "owner/repo"}

        def get_user_token(self, user_id):
            return "token"

    context = types.SimpleNamespace(
        bot=bot,
        user_data={"upload_mode": "github_restore_zip_to_repo"},
        bot_data={"github_handler": _GHHandler()},
    )

    try:
        await handler_env["handler"].handle_document(update, context)
    finally:
        for name, module in originals.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    assert any("❌" in msg for msg, _ in replies.messages)
    assert context.user_data.get("upload_mode") is None


@pytest.mark.asyncio
async def test_maybe_alert_oom_notifies_admin(handler_env):
    context = types.SimpleNamespace(bot=None)
    await handler_env["handler"]._maybe_alert_oom(context, MemoryError("out of memory"), "בבדיקה")
    assert handler_env["notifications"], "צפויה התראה למנהלים במקרה של OOM"


@pytest.mark.asyncio
async def test_handle_document_github_create_repo_custom_name(handler_env):
    zip_bytes = io.BytesIO()
    with zipfile.ZipFile(zip_bytes, "w") as zf:
        zf.writestr("file.py", "print('hi')")
    payload = zip_bytes.getvalue()

    class FakeGHException(Exception):
        pass

    class FakeRepo:
        def __init__(self):
            self.default_branch = "main"
            self.full_name = "owner/custom"
            self.created_paths = []

        def create_file(self, path, message, content, branch):
            self.created_paths.append(path)

        def get_git_ref(self, name):
            raise FakeGHException("no ref")

        def get_git_commit(self, sha):
            raise FakeGHException("no commit")

    repo_instance = FakeRepo()

    class FakeUser:
        def create_repo(self, name, private, auto_init):
            assert name == "my-custom"
            assert private is False
            return repo_instance

    class FakeGithub:
        def __init__(self, token):
            self.token = token

        def get_user(self):
            return FakeUser()

    originals = {
        "github": sys.modules.get("github"),
        "github.GithubException": sys.modules.get("github.GithubException"),
    }
    github_module = types.ModuleType("github")
    github_module.Github = FakeGithub
    github_exception_module = types.ModuleType("github.GithubException")
    github_exception_module.GithubException = FakeGHException
    sys.modules["github"] = github_module
    sys.modules["github.GithubException"] = github_exception_module

    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "repo.zip",
        "file_size": len(payload),
        "file_id": "fid-gh-create-custom",
        "mime_type": "application/zip",
    })

    class _GHHandler:
        def get_user_session(self, user_id):
            return {"selected_repo": "owner/old"}

        def get_user_token(self, user_id):
            return "token"

    context = types.SimpleNamespace(
        bot=bot,
        user_data={
            "upload_mode": "github_create_repo_from_zip",
            "new_repo_name": "My Custom",
            "new_repo_private": False,
        },
        bot_data={"github_handler": _GHHandler()},
    )

    try:
        await handler_env["handler"].handle_document(update, context)
    finally:
        for name, module in originals.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    assert repo_instance.created_paths, "צפויה יצירת קבצים בריפו החדש"
    assert context.user_data.get("upload_mode") is None
    assert "✅" in replies.messages[-1][0]


@pytest.mark.asyncio
async def test_handle_document_github_create_repo_missing_token(handler_env):
    payload = b"zip"
    bot = _DummyBot(payload)
    update, replies = _make_update({
        "file_name": "repo.zip",
        "file_size": len(payload),
        "file_id": "fid-no-token",
        "mime_type": "application/zip",
    })

    class _GHHandler:
        def get_user_session(self, user_id):
            return {"selected_repo": "owner/repo"}

        def get_user_token(self, user_id):
            return None

    context = types.SimpleNamespace(
        bot=bot,
        user_data={"upload_mode": "github_create_repo_from_zip"},
        bot_data={"github_handler": _GHHandler()},
    )

    await handler_env["handler"].handle_document(update, context)

    assert any("אין טוקן" in msg for msg, _ in replies.messages)
    assert context.user_data.get("upload_mode") is None

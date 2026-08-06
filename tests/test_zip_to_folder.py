"""
בדיקות לפריסת ZIP לתוך תיקייה בריפו.

הפיצ'ר מוסיף למשתמש אפשרות לשלוח ZIP ולפרוס אותו לתיקייה נבחרת,
במקום לשורש הריפו. הבדיקות מתמקדות בשלושה דברים:

1. נרמול נתיב היעד וחסימת ניסיונות לצאת מהריפו.
2. הגנת Zip-Slip על הנתיבים שבתוך הארכיון עצמו.
3. הפריסה בפועל – שהקבצים מקבלים את ה-prefix ושהריפו הקיים לא נמחק.
"""

import io
import sys
import types
import zipfile

import pytest

from handlers import documents as documents_mod
from handlers.documents import (
    detect_zip_common_root,
    normalize_repo_folder,
    sanitize_zip_member_path,
)


# ---------------------------------------------------------------------------
# זיהוי תיקיית שורש משותפת
# ---------------------------------------------------------------------------


def test_common_root_detected_when_all_files_share_it():
    assert detect_zip_common_root(["proj/a.py", "proj/sub/b.py"]) == "proj"


def test_no_common_root_when_a_file_sits_at_the_top():
    """
    רגרסיה: קודם ZIP כזה זוהה בטעות עם שורש 'src', ולכן 'src/main.py'
    נחתך ל-'main.py' והמבנה של הארכיון נהרס.
    """
    assert detect_zip_common_root(["README.md", "src/main.py"]) is None


def test_no_common_root_for_multiple_top_levels():
    assert detect_zip_common_root(["a/x.py", "b/y.py"]) is None


def test_macosx_entries_do_not_affect_detection():
    assert detect_zip_common_root(["__MACOSX/._x", "proj/a.py"]) == "proj"


def test_appledouble_file_at_root_does_not_break_detection():
    """
    ZIP שנוצר ב-macOS מכיל לעיתים ._proj בשורש. הקובץ מסונן ממילא לפני
    הפריסה, ולכן הוא לא אמור לבטל את זיהוי תיקיית השורש.
    """
    assert detect_zip_common_root(["._proj", "proj/a.py", "proj/b.py"]) == "proj"


def test_appledouble_inside_folder_is_ignored_too():
    assert detect_zip_common_root(["proj/._a.py", "proj/a.py"]) == "proj"


@pytest.mark.parametrize("root", ["..", "."])
def test_dot_paths_are_never_treated_as_common_root(root):
    """
    ".." אינו תיקיית שורש. אילו היה מוחזר ככזה, הסרתו הייתה "מנקה" נתיב
    בריחה במקום שהוא ייפסל — כלומר ארכיון חשוד היה נפרס בשקט.
    """
    assert detect_zip_common_root([f"{root}/a.py", f"{root}/b.py"]) is None


def test_zip_with_root_file_keeps_nested_structure():
    """בדיקה מקצה לקצה של אותו באג, דרך הפרסור האמיתי."""
    handler = documents_mod.DocumentHandler.__new__(documents_mod.DocumentHandler)
    raw = _make_zip({"README.md": b"top", "src/main.py": b"code"})
    files, common_root, _count = handler._parse_zip_for_import(io.BytesIO(raw))

    assert common_root is None
    assert {p for p, _ in files} == {"README.md", "src/main.py"}


# ---------------------------------------------------------------------------
# נרמול נתיב היעד
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("docs", "docs"),
        ("/docs/", "docs"),          # לוכסנים בקצוות – טעות הקלדה נפוצה
        ("src//utils", "src/utils"),  # לוכסן כפול
        ("  docs  ", "docs"),
        ("./docs", "docs"),
        ("docs\\sub", "docs/sub"),    # מפריד של Windows
        ("", ""),
        ("/", ""),
    ],
)
def test_normalize_repo_folder_accepts_and_cleans(raw, expected):
    assert normalize_repo_folder(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["..", "../etc", "docs/..", "docs/../../x", "C:/Users/me/docs"],
)
def test_normalize_repo_folder_blocks_escapes(raw):
    """נתיב שמנסה לצאת מהריפו חייב להיכשל בבירור ולא להינרמל בשקט."""
    with pytest.raises(ValueError):
        normalize_repo_folder(raw)


# ---------------------------------------------------------------------------
# Zip-Slip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a/b.txt", "a/b.txt"),
        ("./a.txt", "a.txt"),
        ("a//b.txt", "a/b.txt"),
        ("a\\b.txt", "a/b.txt"),
        ("/abs/x.txt", "abs/x.txt"),  # נתיב מוחלט בארכיון – מנורמל, לא מסוכן ב-git
        ("a/./b", "a/b"),
    ],
)
def test_sanitize_zip_member_path_normalizes(raw, expected):
    assert sanitize_zip_member_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "../evil.txt",
        "../../etc/passwd",
        "a/../../b",
        "C:/windows/x",
        "",
        "dir/",          # ערך תיקייה, לא קובץ
        "..",
    ],
)
def test_sanitize_zip_member_path_rejects_traversal(raw):
    """
    זו ההגנה המרכזית: בלעדיה קובץ בשם '../x' היה נכתב מחוץ לתיקייה
    שהמשתמש בחר, במקום אחר לגמרי בריפו.
    """
    assert sanitize_zip_member_path(raw) is None


# ---------------------------------------------------------------------------
# הפריסה בפועל
# ---------------------------------------------------------------------------


def _make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class _FakeBlob:
    def __init__(self, sha):
        self.sha = sha


class _FakeRef:
    def __init__(self, sha):
        self.object = types.SimpleNamespace(sha=sha)
        self.edited_to = None

    def edit(self, sha):
        self.edited_to = sha


class _FakeRepo:
    """ריפו מדומה שמתעד את הקריאות, כדי לבדוק מה נשלח ל-GitHub."""

    def __init__(self, default_branch="main"):
        self.default_branch = default_branch
        self.full_name = "owner/repo"
        self.ref = _FakeRef("base-sha")
        self.base_tree = object()
        self.created_trees = []
        self.created_commits = []
        self._blob_counter = 0

    def get_git_ref(self, ref):
        assert ref == f"heads/{self.default_branch}"
        return self.ref

    def get_git_commit(self, sha):
        return types.SimpleNamespace(sha=sha, tree=self.base_tree)

    def create_git_blob(self, content, encoding):
        self._blob_counter += 1
        return _FakeBlob(f"blob-{self._blob_counter}")

    def create_git_tree(self, elements, base_tree=None):
        self.created_trees.append((elements, base_tree))
        return object()

    def create_git_commit(self, message, tree, parents):
        self.created_commits.append((message, tree, parents))
        return types.SimpleNamespace(sha="new-sha")


class _FakeGithubException(Exception):
    """מדמה GithubException, כולל שדה status שהקוד בודק."""

    def __init__(self, status=404):
        super().__init__(f"fake github error {status}")
        self.status = status


class _EmptyRepo(_FakeRepo):
    """ריפו ללא קומיט ראשון — get_git_ref מחזיר 404, כמו GitHub אמיתי."""

    def __init__(self, status=404):
        super().__init__()
        self._status = status
        self.created_files = []

    def get_git_ref(self, ref):
        raise _FakeGithubException(self._status)

    def create_file(self, path, message, content, branch):
        self.created_files.append((path, message, branch))


@pytest.fixture
def fake_github_module():
    """מזריק את מודולי github שהקוד מייבא, ומשחזר אחרי הבדיקה."""

    class _InputGitTreeElement:
        def __init__(self, **kwargs):
            self.path = kwargs.get("path")
            self.mode = kwargs.get("mode")
            self.type = kwargs.get("type")
            self.sha = kwargs.get("sha")

    igte_module = types.ModuleType("github.InputGitTreeElement")
    igte_module.InputGitTreeElement = _InputGitTreeElement
    exc_module = types.ModuleType("github.GithubException")
    exc_module.GithubException = _FakeGithubException

    originals = {
        name: sys.modules.get(name)
        for name in ("github.InputGitTreeElement", "github.GithubException")
    }
    sys.modules["github.InputGitTreeElement"] = igte_module
    sys.modules["github.GithubException"] = exc_module
    try:
        yield _InputGitTreeElement
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def _upload(repo, files, prefix):
    handler = documents_mod.DocumentHandler.__new__(documents_mod.DocumentHandler)
    return documents_mod.DocumentHandler._gh_upload_files(
        handler, repo, files, prefix, f"Deploy ZIP contents to {prefix or 'root'} via bot"
    )


def test_upload_prefixes_every_path(fake_github_module):
    repo = _FakeRepo()
    count = _upload(repo, [("a.py", b"x"), ("sub/b.md", b"y")], "docs")

    assert count == 2
    elements, base_tree = repo.created_trees[0]
    paths = sorted(e.path for e in elements)
    assert paths == ["docs/a.py", "docs/sub/b.md"]
    assert base_tree is repo.base_tree, "חייב לבנות על העץ הקיים"


def test_upload_keeps_existing_repo_intact(fake_github_module):
    """
    הפריסה חייבת להעביר base_tree, אחרת GitHub בונה עץ חדש לגמרי
    וכל שאר הריפו נמחק — בדיוק מה שאסור לקרות כאן.
    """
    repo = _FakeRepo()
    _upload(repo, [("a.py", b"x")], "docs")

    _elements, base_tree = repo.created_trees[0]
    assert base_tree is not None, "בלי base_tree הריפו כולו היה נמחק"

    message, _tree, parents = repo.created_commits[0]
    assert "docs" in message
    assert parents, "הקומיט חייב הורה, אחרת ההיסטוריה נקטעת"
    assert repo.ref.edited_to == "new-sha"


def test_upload_without_prefix_keeps_original_paths(fake_github_module):
    repo = _FakeRepo()
    _upload(repo, [("a.py", b"x")], "")

    elements, _ = repo.created_trees[0]
    assert [e.path for e in elements] == ["a.py"]


def test_upload_respects_non_default_branch(fake_github_module):
    repo = _FakeRepo(default_branch="develop")
    _upload(repo, [("a.py", b"x")], "docs")
    assert repo.ref.edited_to == "new-sha"


@pytest.mark.parametrize("status", [404, 409])
def test_upload_to_empty_repo_uses_contents_api(fake_github_module, status):
    """
    בריפו בלי קומיט ראשון אין ref, ולכן בניית tree הייתה נכשלת.
    במקרה כזה יוצרים את הקבצים דרך Contents API — כולל ה-prefix.
    """
    repo = _EmptyRepo(status=status)
    count = _upload(repo, [("a.py", b"x"), ("sub/b.md", b"y")], "docs")

    assert count == 2
    assert sorted(p for p, _m, _b in repo.created_files) == ["docs/a.py", "docs/sub/b.md"]
    assert not repo.created_trees, "בריפו ריק אין לבנות tree"


def test_upload_propagates_unexpected_api_errors(fake_github_module):
    """
    רק 404/409 נחשבים ל'ריפו ריק'. שגיאת הרשאות או rate limit חייבת
    להתפשט, אחרת נדווח על העלאה מוצלחת שלא באמת קרתה.
    """
    repo = _EmptyRepo(status=403)
    with pytest.raises(_FakeGithubException):
        _upload(repo, [("a.py", b"x")], "docs")


def test_blob_api_errors_are_not_swallowed(fake_github_module):
    """
    בעבר עטף try/except רחב את יצירת ה-blob, ולכן שגיאת API נבלעה
    וניסיון ה-base64 הסתיר את הסיבה האמיתית.
    """
    repo = _FakeRepo()

    def _boom(content, encoding):
        raise RuntimeError("rate limit exceeded")

    repo.create_git_blob = _boom
    with pytest.raises(RuntimeError, match="rate limit"):
        _upload(repo, [("readme.md", b"hello")], "docs")


def test_text_extension_with_binary_content_falls_back(fake_github_module):
    """קובץ עם סיומת טקסט אבל תוכן שאינו UTF-8 נשמר כ-base64 ולא נופל."""
    repo = _FakeRepo()
    encodings = []
    original = repo.create_git_blob

    def _tracking(content, encoding):
        encodings.append(encoding)
        return original(content, encoding)

    repo.create_git_blob = _tracking
    _upload(repo, [("broken.md", b"\xff\xfe\x00binary")], "docs")

    assert encodings == ["base64"]


def test_binary_files_are_uploaded_as_base64(fake_github_module):
    """קובץ בינארי לא אמור להישבר על decode ל-UTF-8."""
    repo = _FakeRepo()
    encodings = []

    original_create_blob = repo.create_git_blob

    def _tracking_blob(content, encoding):
        encodings.append(encoding)
        return original_create_blob(content, encoding)

    repo.create_git_blob = _tracking_blob
    _upload(repo, [("logo.png", b"\x89PNG\r\n\x1a\n\xff\xfe")], "assets")

    assert encodings == ["base64"]


def test_text_file_uploaded_as_utf8(fake_github_module):
    repo = _FakeRepo()
    encodings = []
    original = repo.create_git_blob

    def _tracking_blob(content, encoding):
        encodings.append(encoding)
        return original(content, encoding)

    repo.create_git_blob = _tracking_blob
    _upload(repo, [("readme.md", "שלום".encode("utf-8"))], "docs")

    assert encodings == ["utf-8"]


# ---------------------------------------------------------------------------
# פרסור ה-ZIP יחד עם הסניטציה
# ---------------------------------------------------------------------------


def test_zip_parsing_then_sanitizing_drops_traversal_entries():
    """
    בדיקה משולבת: ארכיון שמכיל גם קובץ תקין וגם ניסיון בריחה —
    התקין נשמר, המסוכן מסונן.
    """
    handler = documents_mod.DocumentHandler.__new__(documents_mod.DocumentHandler)
    raw = _make_zip({
        "good.txt": b"ok",
        "nested/deep.txt": b"ok",
        "../escape.txt": b"bad",
    })
    files, _root, _count = handler._parse_zip_for_import(io.BytesIO(raw))

    safe = []
    skipped = []
    for path, data in files:
        clean = sanitize_zip_member_path(path)
        (skipped if clean is None else safe).append(clean or path)

    assert "good.txt" in safe
    assert "nested/deep.txt" in safe
    assert any("escape" in s for s in skipped), "נתיב הבריחה היה צריך להיפסל"


# ---------------------------------------------------------------------------
# אינטגרציה – המסלול המלא דרך handle_document
# ---------------------------------------------------------------------------


class _DummyFile:
    def __init__(self, payload):
        self._payload = payload

    async def download_to_memory(self, buf):
        buf.write(self._payload)


class _DummyBot:
    def __init__(self, payload):
        self._payload = payload

    async def get_file(self, file_id):
        return _DummyFile(self._payload)


class _Replies:
    def __init__(self):
        self.messages = []

    async def reply_text(self, text, **kwargs):
        self.messages.append(text)


def _make_update(payload_name="upload.zip"):
    replies = _Replies()
    document = types.SimpleNamespace(
        file_name=payload_name, file_size=100, file_id="fid", mime_type="application/zip"
    )
    update = types.SimpleNamespace(
        message=types.SimpleNamespace(document=document, reply_text=replies.reply_text),
        effective_user=types.SimpleNamespace(id=7),
    )
    return update, replies


@pytest.fixture
def github_stub(fake_github_module):
    """מזריק גם את github.Github, ומחזיר את הריפו המדומה שנוצר."""
    repo = _FakeRepo()

    class _Github:
        def __init__(self, token):
            self.token = token

        def get_repo(self, full_name):
            repo.full_name = full_name
            return repo

    module = types.ModuleType("github")
    module.Github = _Github
    original = sys.modules.get("github")
    sys.modules["github"] = module
    try:
        yield repo
    finally:
        if original is None:
            sys.modules.pop("github", None)
        else:
            sys.modules["github"] = original


@pytest.fixture
def zip_handler():
    """DocumentHandler מינימלי – הפלואו הנבדק לא נוגע ב-DB או בגיבויים."""

    async def _noop_async(*args, **kwargs):
        return None

    class _Errors:
        def labels(self, **kwargs):
            return types.SimpleNamespace(inc=lambda: None)

    return documents_mod.DocumentHandler(
        notify_admins=_noop_async,
        get_reporter=lambda: None,
        log_user_activity=_noop_async,
        encodings_to_try=("utf-8",),
        emit_event=lambda *args, **kwargs: None,
        errors_total=_Errors(),
    )


class _GHHandler:
    def get_user_session(self, user_id):
        return {"selected_repo": "owner/repo"}

    def get_user_token(self, user_id):
        return "token"


def _context(bot, **user_data):
    base = {
        "upload_mode": "github_zip_to_folder",
        "zip_to_folder_target": "docs",
        "zip_to_folder_repo": "owner/repo",
    }
    base.update(user_data)
    return types.SimpleNamespace(
        bot=bot, user_data=base, bot_data={"github_handler": _GHHandler()}
    )


@pytest.mark.asyncio
async def test_full_flow_deploys_into_folder(zip_handler, github_stub):
    payload = _make_zip({"index.md": b"hello", "sub/page.md": b"world"})
    update, replies = _make_update()
    context = _context(_DummyBot(payload))

    await zip_handler.handle_document(update, context)

    elements, base_tree = github_stub.created_trees[0]
    assert sorted(e.path for e in elements) == ["docs/index.md", "docs/sub/page.md"]
    assert base_tree is not None, "שאר הריפו חייב להישמר"
    assert any("נפרסו" in m for m in replies.messages), replies.messages
    # מצב ההעלאה מתאפס כדי שקובץ הבא לא ייפרס בטעות לאותה תיקייה
    assert context.user_data["upload_mode"] is None
    assert "zip_to_folder_target" not in context.user_data


@pytest.mark.asyncio
async def test_full_flow_skips_traversal_and_warns(zip_handler, github_stub):
    """קובץ שמנסה לברוח מהתיקייה מדולג, והמשתמש מקבל על כך התראה."""
    payload = _make_zip({"ok.md": b"fine", "../../escape.md": b"bad"})
    update, replies = _make_update()
    context = _context(_DummyBot(payload))

    await zip_handler.handle_document(update, context)

    elements, _ = github_stub.created_trees[0]
    paths = [e.path for e in elements]
    assert paths == ["docs/ok.md"]
    assert not any("escape" in p for p in paths), "נתיב הבריחה נפרס בפועל!"
    assert any("דולגו" in m for m in replies.messages), replies.messages


@pytest.mark.asyncio
async def test_full_flow_rejects_missing_target(zip_handler, github_stub):
    payload = _make_zip({"a.md": b"x"})
    update, replies = _make_update()
    context = _context(_DummyBot(payload), zip_to_folder_target="")

    await zip_handler.handle_document(update, context)

    assert not github_stub.created_trees, "בלי תיקיית יעד אסור לכתוב לריפו"
    assert any("לא נבחרה תיקיית יעד" in m for m in replies.messages), replies.messages


@pytest.mark.asyncio
async def test_full_flow_rejects_bad_target_path(zip_handler, github_stub):
    """נתיב יעד עם '..' נעצר לפני כל פנייה ל-GitHub."""
    payload = _make_zip({"a.md": b"x"})
    update, replies = _make_update()
    context = _context(_DummyBot(payload), zip_to_folder_target="../outside")

    await zip_handler.handle_document(update, context)

    assert not github_stub.created_trees
    assert any("אינו תקין" in m for m in replies.messages), replies.messages


@pytest.mark.asyncio
async def test_full_flow_uses_locked_repo_not_session(zip_handler, github_stub):
    """
    אם המשתמש החליף ריפו בין בחירת התיקייה לשליחת הקובץ,
    הפריסה חייבת ללכת לריפו שננעל ולא לזה שבסשן.
    """
    payload = _make_zip({"a.md": b"x"})
    update, _ = _make_update()
    context = _context(_DummyBot(payload), zip_to_folder_repo="owner/locked")

    await zip_handler.handle_document(update, context)

    assert github_stub.full_name == "owner/locked"


# ---------------------------------------------------------------------------
# זרימת התפריט – בחירת תיקייה, אישור וביטול
# ---------------------------------------------------------------------------


@pytest.fixture
def menu_handler():
    """GitHubMenuHandler בלי לעבור דרך __init__ (שנוגע ב-DB)."""
    from github_menu_handler import GitHubMenuHandler

    handler = GitHubMenuHandler.__new__(GitHubMenuHandler)
    handler.user_sessions = {7: {"selected_repo": "owner/repo", "selected_folder": "docs"}}
    return handler


class _FakeQuery:
    def __init__(self, data="", user_id=7):
        self.data = data
        self.from_user = types.SimpleNamespace(id=user_id)
        self.edited = []
        self.answers = []
        self.markups = []
        self.message = types.SimpleNamespace(reply_text=self._reply)

    async def edit_message_text(self, text, **kwargs):
        self.edited.append(text)
        if kwargs.get("reply_markup") is not None:
            self.markups.append(kwargs["reply_markup"])

    async def answer(self, text="", **kwargs):
        self.answers.append(text)

    async def _reply(self, text, **kwargs):
        self.edited.append(text)
        if kwargs.get("reply_markup") is not None:
            self.markups.append(kwargs["reply_markup"])

    def callbacks(self):
        """כל ה-callback_data שהוצגו למשתמש, לפי הסדר."""
        out = []
        for markup in self.markups:
            for row in markup.inline_keyboard:
                for button in row:
                    out.append(button.callback_data)
        return out


def _menu_update(query):
    return types.SimpleNamespace(
        callback_query=query, effective_user=types.SimpleNamespace(id=7), message=query.message
    )


def _menu_context(**user_data):
    return types.SimpleNamespace(user_data=dict(user_data), bot_data={})


@pytest.mark.asyncio
async def test_confirm_accepts_valid_folder(menu_handler):
    query = _FakeQuery()
    context = _menu_context(zip_to_folder_repo="owner/repo")

    accepted = await menu_handler.confirm_zip_to_folder_target(
        _menu_update(query), context, "docs/api"
    )

    assert accepted is True
    assert context.user_data["zip_to_folder_target"] == "docs/api"
    assert any("docs/api" in t for t in query.edited)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../outside", "", "   "])
async def test_confirm_rejects_bad_folder(menu_handler, bad):
    """
    נתיב פסול מחזיר False, כדי שהקורא ישאיר את המשתמש במצב הזנה
    ויאפשר לו לתקן במקום להתחיל מהתפריט מחדש.
    """
    query = _FakeQuery()
    context = _menu_context(zip_to_folder_repo="owner/repo")

    accepted = await menu_handler.confirm_zip_to_folder_target(
        _menu_update(query), context, bad
    )

    assert accepted is False
    assert "zip_to_folder_target" not in context.user_data


def _text_update(text, user_id=7):
    """update של הודעת טקסט, כפי ש-handle_text_input מצפה לקבל."""
    replies = []

    async def reply_text(message_text, **kwargs):
        replies.append(message_text)

    message = types.SimpleNamespace(
        text=text,
        from_user=types.SimpleNamespace(id=user_id),
        reply_text=reply_text,
    )
    update = types.SimpleNamespace(
        message=message,
        callback_query=None,
        effective_user=types.SimpleNamespace(id=user_id),
    )
    return update, replies


@pytest.mark.asyncio
async def test_bad_path_keeps_user_in_input_mode(menu_handler):
    """
    רגרסיה: קודם הדגל נוקה לפני הוולידציה, ולכן אחרי נתיב שגוי
    ההודעה הבאה כבר לא נחשבה לנתיב והמשתמש נתקע.
    """
    context = _menu_context(
        waiting_for_zipdir_folder=True, zip_to_folder_repo="owner/repo"
    )

    bad_update, bad_replies = _text_update("../escape")
    await menu_handler.handle_text_input(bad_update, context)

    assert context.user_data.get("waiting_for_zipdir_folder") is True, (
        "אחרי נתיב שגוי המשתמש צריך להישאר במצב הזנה"
    )
    assert any("לא תקין" in r for r in bad_replies), bad_replies

    good_update, _ = _text_update("docs")
    await menu_handler.handle_text_input(good_update, context)

    assert context.user_data.get("waiting_for_zipdir_folder") is False
    assert context.user_data["zip_to_folder_target"] == "docs"


@pytest.fixture
def callback_handler(menu_handler, monkeypatch):
    """menu_handler עם get_user_token ועם safe_answer מנוטרל, לבדיקת callbacks."""
    import github_menu_handler as gmh

    menu_handler.get_user_token = lambda user_id: "token"

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(gmh.TelegramUtils, "safe_answer", _noop, raising=False)
    monkeypatch.setattr(gmh, "emit_event", lambda *a, **k: None, raising=False)
    return menu_handler


async def _click(handler, context, data):
    query = _FakeQuery(data=data)
    await handler.handle_menu_callback(_menu_update(query), context)
    return query


@pytest.mark.asyncio
async def test_callback_opens_folder_picker(callback_handler):
    context = _menu_context()
    query = await _click(callback_handler, context, "github_zip_to_folder")

    # הריפו ננעל כבר בשלב הזה, לפני שנשלח קובץ
    assert context.user_data["zip_to_folder_repo"] == "owner/repo"
    assert context.user_data["upload_mode"] is None, "אסור לפתוח מצב קליטה לפני בחירת יעד"
    assert any("פריסת ZIP לתיקייה" in t for t in query.edited), query.edited


@pytest.mark.asyncio
async def test_callback_uses_current_folder(callback_handler):
    context = _menu_context(zip_to_folder_repo="owner/repo")
    query = await _click(callback_handler, context, "zipdir_use_current")

    assert context.user_data["zip_to_folder_target"] == "docs"
    assert any("אישור" in t for t in query.edited), query.edited


@pytest.mark.asyncio
async def test_callback_custom_path_sets_waiting_flag(callback_handler):
    context = _menu_context(zip_to_folder_repo="owner/repo")
    await _click(callback_handler, context, "zipdir_custom")

    assert context.user_data["waiting_for_zipdir_folder"] is True


@pytest.mark.asyncio
async def test_callback_confirm_opens_upload_mode(callback_handler):
    """רק אחרי אישור מפורש נפתח מצב קליטת ה-ZIP."""
    context = _menu_context(
        zip_to_folder_repo="owner/repo", zip_to_folder_target="docs"
    )
    query = await _click(callback_handler, context, "zipdir_confirm")

    assert context.user_data["upload_mode"] == "github_zip_to_folder"
    assert context.user_data["waiting_for_github_upload"] is False
    assert any("שלח עכשיו" in t for t in query.edited), query.edited


@pytest.mark.asyncio
@pytest.mark.parametrize("folder", ["docs<x", "a&b", "we>ird"])
async def test_html_special_chars_in_path_are_escaped(menu_handler, folder):
    """
    הנתיב מגיע מטקסט חופשי ומוצב בהודעת parse_mode=HTML. בלי הברחה,
    טלגרם היה דוחה את ההודעה ב-BadRequest והזרימה הייתה נתקעת.
    """
    query = _FakeQuery()
    context = _menu_context(zip_to_folder_repo="owner/repo")

    accepted = await menu_handler.confirm_zip_to_folder_target(
        _menu_update(query), context, folder
    )

    assert accepted is True
    body = "\n".join(query.edited)
    assert folder not in body, "הנתיב הגולמי הוצב בלי הברחה"
    for ch, entity in (("<", "&lt;"), (">", "&gt;"), ("&", "&amp;")):
        if ch in folder:
            assert entity in body, f"{ch} לא הוברח"


@pytest.mark.asyncio
async def test_confirm_message_escapes_special_chars_on_send_screen(callback_handler):
    """גם מסך 'שלח עכשיו ZIP' מציג את הנתיב, ולכן חייב להבריח אותו."""
    context = _menu_context(
        zip_to_folder_repo="owner/repo", zip_to_folder_target="docs<x"
    )
    query = await _click(callback_handler, context, "zipdir_confirm")

    body = "\n".join(query.edited)
    assert "docs<x" not in body
    assert "&lt;" in body


@pytest.mark.asyncio
async def test_callback_confirm_without_target_does_not_open_upload_mode(callback_handler):
    context = _menu_context(zip_to_folder_repo="owner/repo")
    query = await _click(callback_handler, context, "zipdir_confirm")

    assert context.user_data.get("upload_mode") != "github_zip_to_folder"
    assert any("לא נבחרה" in a for a in query.answers), query.answers


@pytest.mark.asyncio
async def test_callback_requires_selected_repo(callback_handler):
    callback_handler.user_sessions[7] = {"selected_repo": None, "selected_folder": None}
    context = _menu_context()
    query = await _click(callback_handler, context, "github_zip_to_folder")

    assert "zip_to_folder_repo" not in context.user_data
    assert any("ריפו" in a for a in query.answers), query.answers


@pytest.mark.asyncio
async def test_callback_use_current_without_folder(callback_handler):
    callback_handler.user_sessions[7] = {
        "selected_repo": "owner/repo", "selected_folder": None
    }
    context = _menu_context(zip_to_folder_repo="owner/repo")
    query = await _click(callback_handler, context, "zipdir_use_current")

    assert "zip_to_folder_target" not in context.user_data
    assert any("אין תיקייה" in a for a in query.answers), query.answers


_ZIPDIR_STATE_KEYS = (
    "waiting_for_zipdir_folder",
    "zip_to_folder_target",
    "zip_to_folder_repo",
)


@pytest.mark.asyncio
async def test_returning_to_main_menu_clears_zipdir_state(callback_handler):
    """
    רגרסיה: 'ביטול'/'חזור' בזרימה מחזירים לתפריט GitHub הראשי. אם המצב
    לא מנוקה שם, הבוט נשאר ממתין לנתיב וההודעה הבאה של המשתמש מתפרשת
    בטעות כתיקיית יעד.
    """
    context = _menu_context()
    await _click(callback_handler, context, "github_zip_to_folder")
    await _click(callback_handler, context, "zipdir_custom")
    assert context.user_data["waiting_for_zipdir_folder"] is True

    await _click(callback_handler, context, "github_menu")

    for key in _ZIPDIR_STATE_KEYS:
        assert not context.user_data.get(key), f"{key} נשאר תקוע אחרי חזרה לתפריט"
    assert context.user_data.get("upload_mode") != "github_zip_to_folder"


@pytest.mark.asyncio
async def test_returning_to_main_menu_clears_pending_upload_mode(callback_handler):
    """גם אחרי אישור היעד, יציאה לתפריט מבטלת את ההמתנה לקובץ."""
    context = _menu_context()
    await _click(callback_handler, context, "github_zip_to_folder")
    await _click(callback_handler, context, "zipdir_use_current")
    await _click(callback_handler, context, "zipdir_confirm")
    assert context.user_data["upload_mode"] == "github_zip_to_folder"

    await _click(callback_handler, context, "github_menu")
    assert context.user_data.get("upload_mode") != "github_zip_to_folder"


def test_clear_helper_only_touches_this_flow(menu_handler):
    """
    הניקוי מרוכז בפונקציה אחת ששני מסלולי היציאה קוראים לה. היא אמורה
    לנקות רק את מצב הזרימה הזו — ולא מצבי העלאה אחרים שרצים במקביל.
    """
    context = _menu_context(
        waiting_for_zipdir_folder=True,
        zip_to_folder_target="docs",
        zip_to_folder_repo="owner/repo",
        upload_mode="github_restore_zip_to_repo",  # זרימה אחרת
        waiting_for_github_upload=True,
    )

    menu_handler.clear_zip_to_folder_state(context)

    for key in _ZIPDIR_STATE_KEYS:
        assert key not in context.user_data
    assert context.user_data["upload_mode"] == "github_restore_zip_to_repo", (
        "הניקוי דרס מצב העלאה של זרימה אחרת"
    )
    assert context.user_data["waiting_for_github_upload"] is True


def test_clear_helper_resets_own_upload_mode(menu_handler):
    context = _menu_context(upload_mode="github_zip_to_folder")
    menu_handler.clear_zip_to_folder_state(context)
    assert "upload_mode" not in context.user_data


def test_clear_helper_is_safe_on_empty_state(menu_handler):
    """קריאה כשאין מצב פעיל לא אמורה לזרוק."""
    context = _menu_context()
    menu_handler.clear_zip_to_folder_state(context)
    assert context.user_data == {}


@pytest.mark.asyncio
async def test_backup_menu_still_clears_zipdir_state(callback_handler):
    """
    הכפתור עבר לתפריט הראשי, אבל הניקוי בתפריט הגיבוי נשאר כרשת ביטחון
    למקרה שהמשתמש מגיע לשם באמצע הזרימה.
    """
    context = _menu_context()
    await _click(callback_handler, context, "github_zip_to_folder")
    await _click(callback_handler, context, "zipdir_custom")

    await _click(callback_handler, context, "github_backup_menu")

    for key in _ZIPDIR_STATE_KEYS:
        assert not context.user_data.get(key), f"{key} נשאר תקוע אחרי מעבר לתפריט הגיבוי"


def test_main_menu_exit_clears_zipdir_state():
    """
    יציאה דרך התפריט הראשי היא מסלול נוסף שבו הדגל היה נשאר תקוע,
    בדיוק כמו בכפתור הביטול.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    start = src.index("main_menu_texts = {")
    block = src[start : start + 3000]
    for key in ("waiting_for_zipdir_folder", "zip_to_folder_target", "zip_to_folder_repo"):
        assert f"'{key}'" in block, f"{key} לא מנוקה ביציאה דרך התפריט הראשי"


def test_all_callbacks_are_registered_in_router():
    """
    כפתור שלא רשום ב-pattern של main.py פשוט לא יגיב בבוט,
    בלי שום שגיאה — לכן שווה לשמור על זה בבדיקה.
    """
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    main_src = (repo_root / "main.py").read_text(encoding="utf-8")
    menu_src = (repo_root / "github_menu_handler.py").read_text(encoding="utf-8")

    for callback in (
        "github_zip_to_folder",
        "zipdir_use_current",
        "zipdir_custom",
        "zipdir_confirm",
    ):
        assert callback in main_src, f"{callback} לא רשום ב-pattern של main.py"
        assert f'query.data == "{callback}"' in menu_src, f"אין handler ל-{callback}"

    # הנתיב שמוקלד ידנית מנותב דרך main.py אל handle_text_input
    assert "waiting_for_zipdir_folder" in main_src
    assert "waiting_for_zipdir_folder" in menu_src


@pytest.mark.asyncio
async def test_button_appears_in_the_main_github_menu(callback_handler):
    """
    הכפתור שייך לתפריט GitHub הראשי, ליד שאר פעולות ההעלאה — ולא
    לתפריט הגיבוי והשחזור: פריסת ZIP לתיקייה אינה גיבוי ואינה שחזור.
    """
    query = _FakeQuery()
    await callback_handler.github_menu_command(_menu_update(query), _menu_context())

    buttons = query.callbacks()
    assert "github_zip_to_folder" in buttons, f"הכפתור אינו בתפריט הראשי: {buttons}"
    # יושב ליד פעולות ההעלאה, לא בקצה התפריט
    assert abs(buttons.index("github_zip_to_folder") - buttons.index("upload_file")) == 1


@pytest.mark.asyncio
async def test_button_is_not_in_the_backup_menu(callback_handler):
    query = _FakeQuery()
    await callback_handler.show_github_backup_menu(_menu_update(query), _menu_context())

    buttons = query.callbacks()
    assert buttons, "תפריט הגיבוי לא הוצג"
    assert "github_zip_to_folder" not in buttons, "הכפתור עדיין בתפריט הגיבוי"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "callback", ["github_zip_to_folder", "zipdir_custom", "zipdir_use_current"]
)
async def test_flow_screens_return_to_the_main_menu(callback_handler, callback):
    """
    כפתורי החזרה/ביטול בכל מסכי הזרימה חייבים להחזיר לתפריט שממנו
    המשתמש נכנס — התפריט הראשי, ולא תפריט הגיבוי.
    """
    context = _menu_context()
    await _click(callback_handler, context, "github_zip_to_folder")

    query = _FakeQuery(data=callback)
    await callback_handler.handle_menu_callback(_menu_update(query), context)

    buttons = query.callbacks()
    assert buttons, f"המסך {callback} לא הציג מקלדת"
    assert "github_backup_menu" not in buttons, f"{callback} עדיין מחזיר לתפריט הגיבוי"
    assert "github_menu" in buttons, f"{callback} אינו מציע חזרה לתפריט הראשי"


@pytest.mark.asyncio
async def test_full_flow_rejects_when_all_paths_unsafe(zip_handler, github_stub):
    """ZIP שכולו נתיבי בריחה נעצר עם הודעה, בלי לגעת בריפו."""
    payload = _make_zip({"../a.md": b"x", "../../b.md": b"y"})
    update, replies = _make_update()
    context = _context(_DummyBot(payload))

    await zip_handler.handle_document(update, context)

    assert not github_stub.created_trees
    assert any("נדחו מטעמי בטיחות" in m for m in replies.messages), replies.messages


@pytest.mark.asyncio
async def test_full_flow_requires_token(zip_handler, github_stub):
    class _NoToken:
        def get_user_session(self, user_id):
            return {"selected_repo": "owner/repo"}

        def get_user_token(self, user_id):
            return None

    payload = _make_zip({"a.md": b"x"})
    update, replies = _make_update()
    context = _context(_DummyBot(payload))
    context.bot_data = {"github_handler": _NoToken()}

    await zip_handler.handle_document(update, context)

    assert not github_stub.created_trees
    assert any("טוקן" in m for m in replies.messages), replies.messages


@pytest.mark.asyncio
async def test_full_flow_reports_upload_errors(zip_handler, github_stub):
    """כשל מול GitHub מדווח למשתמש ולא נבלע בשקט."""
    payload = _make_zip({"a.md": b"x"})
    update, replies = _make_update()
    context = _context(_DummyBot(payload))

    def _boom(*args, **kwargs):
        raise RuntimeError("github is down")

    github_stub.create_git_blob = _boom

    await zip_handler.handle_document(update, context)

    assert any("שגיאה בפריסת ZIP" in m for m in replies.messages), replies.messages


@pytest.mark.asyncio
async def test_full_flow_rejects_non_zip(zip_handler, github_stub):
    update, replies = _make_update()
    context = _context(_DummyBot(b"this is not a zip"))

    await zip_handler.handle_document(update, context)

    assert not github_stub.created_trees
    assert any("אינו ZIP תקין" in m for m in replies.messages), replies.messages

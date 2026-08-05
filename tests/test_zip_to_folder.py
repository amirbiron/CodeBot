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


@pytest.fixture
def fake_github_module():
    """מזריק github.InputGitTreeElement מדומה, ומשחזר אחרי הבדיקה."""

    class _InputGitTreeElement:
        def __init__(self, **kwargs):
            self.path = kwargs.get("path")
            self.mode = kwargs.get("mode")
            self.type = kwargs.get("type")
            self.sha = kwargs.get("sha")

    module = types.ModuleType("github.InputGitTreeElement")
    module.InputGitTreeElement = _InputGitTreeElement
    original = sys.modules.get("github.InputGitTreeElement")
    sys.modules["github.InputGitTreeElement"] = module
    try:
        yield _InputGitTreeElement
    finally:
        if original is None:
            sys.modules.pop("github.InputGitTreeElement", None)
        else:
            sys.modules["github.InputGitTreeElement"] = original


def _upload(repo, files, prefix):
    handler = documents_mod.DocumentHandler.__new__(documents_mod.DocumentHandler)
    return documents_mod.DocumentHandler._gh_upload_files_to_folder(
        handler, repo, files, prefix
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


def test_menu_button_exists():
    from pathlib import Path

    menu_src = (Path(__file__).resolve().parents[1] / "github_menu_handler.py").read_text(
        encoding="utf-8"
    )
    assert 'callback_data="github_zip_to_folder"' in menu_src


@pytest.mark.asyncio
async def test_full_flow_rejects_non_zip(zip_handler, github_stub):
    update, replies = _make_update()
    context = _context(_DummyBot(b"this is not a zip"))

    await zip_handler.handle_document(update, context)

    assert not github_stub.created_trees
    assert any("אינו ZIP תקין" in m for m in replies.messages), replies.messages

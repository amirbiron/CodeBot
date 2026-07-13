"""בדיקות רגרסיה לממצאי הריוויו על פלואו download_zip (הורדת ריפו כ-ZIP).

מכסה:
- ממצא 5: backup_id עמיד להתנגשות (רכיב אקראי) ועדיין ניתן לפרסור user_id.
- ממצא 4: save_backup_file שמחזיר None נחשב כשל (אין דיווח הצלחה כוזב).
- ממצא 2: תקרת הורדה קשיחה MAX_BACKUP_BYTES מבטלת הורדה חורגת.
- ממצא 1: לאחר הודעת ENOSPC ידידותית לא נשלחת גם הודעת השגיאה הכללית.
- ממצא 3: _safe_remove_temp_file מוחק רק תחת tempdir ודוחה נתיבים מסוכנים.
"""
import asyncio
import errno
import io
import json
import os
import re
import tempfile
import types
import zipfile

import pytest


def _small_zip_bytes():
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('repo/a.txt', b'a')
    return mem.getvalue()


class _Msg:
    def __init__(self):
        self.docs = []
        self.texts = []

    async def reply_document(self, document=None, filename=None, caption=None):
        self.docs.append({"filename": filename, "caption": caption})

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)


class _Query:
    def __init__(self, user_id):
        self.data = "download_zip:"
        self.message = _Msg()
        self.from_user = types.SimpleNamespace(id=user_id)
        self.edits = []

    async def edit_message_text(self, text=None, *a, **k):
        self.edits.append(text)

    async def answer(self, *a, **k):
        return None


class _Upd:
    def __init__(self, user_id):
        self.callback_query = _Query(user_id)
        self.effective_user = types.SimpleNamespace(id=user_id)


class _Ctx:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


def _make_repo():
    class _Repo:
        full_name = "o/r"
        name = "r"

        def get_archive_link(self, _):
            return "https://example.com/archive.zip"
    return _Repo()


def _install(monkeypatch, *, save_return="bid", payload=None, content_length=None, giant=False):
    import github_menu_handler as gh

    payload = payload if payload is not None else _small_zip_bytes()
    cl = str(content_length if content_length is not None else len(payload))

    class _Resp:
        def __init__(self):
            self.headers = {"Content-Length": cl}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=131072):
            if giant:
                # מספר קטן וקבוע של בלוקים קטנים; הטסט מקטין את MAX_BACKUP_BYTES
                # כך שהביטול יקרה אחרי כמה KB בלבד (בלי לכתוב מאות MB לדיסק).
                blk = b"x" * 2048
                for _ in range(64):
                    yield blk
            else:
                for i in range(0, len(payload), chunk_size):
                    yield payload[i:i + chunk_size]

    def _req_get(_url, headers=None, stream=False, timeout=60):
        return _Resp()

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return _make_repo()

    saved = {"ids": [], "paths": []}

    class _BM:
        def save_backup_file(self, path):
            saved["paths"].append(path)
            try:
                with zipfile.ZipFile(path, 'r') as zf:
                    saved["ids"].append(json.loads(zf.read('metadata.json')).get("backup_id"))
            except Exception:
                pass
            if isinstance(save_return, Exception):
                raise save_return
            return save_return

        def list_backups(self, user_id):
            return []

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh.requests, "get", _req_get)
    monkeypatch.setattr(gh, "backup_manager", _BM())
    return gh, saved


async def _run(gh, user_id=6865105071):
    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": "o/r"}
    handler.get_user_token = lambda uid: "t"
    upd = _Upd(user_id)
    await asyncio.wait_for(handler.handle_menu_callback(upd, _Ctx()), timeout=5.0)
    return upd.callback_query


@pytest.mark.asyncio
async def test_backup_id_has_random_suffix_and_parseable(monkeypatch):
    gh, saved = _install(monkeypatch, save_return="bid")
    await _run(gh, user_id=6865105071)
    assert saved["ids"], "save_backup_file should have been called"
    bid = saved["ids"][0]
    assert bid.startswith("backup_6865105071_"), bid
    # user_id must still be parseable by the same regex list_backups uses
    m = re.match(r"^backup_(\d+)_", bid)
    assert m and int(m.group(1)) == 6865105071
    # collision-resistant random suffix after the timestamp
    parts = bid.split("_")
    assert len(parts) == 4 and re.fullmatch(r"[0-9a-f]+", parts[3]), parts


@pytest.mark.asyncio
async def test_two_backups_same_user_get_distinct_ids(monkeypatch):
    gh, saved = _install(monkeypatch, save_return="bid")
    await _run(gh, user_id=42)
    await _run(gh, user_id=42)
    assert len(saved["ids"]) == 2
    assert saved["ids"][0] != saved["ids"][1], "concurrent backups must not collide"


@pytest.mark.asyncio
async def test_save_returns_none_is_treated_as_failure(monkeypatch):
    gh, _ = _install(monkeypatch, save_return=None)
    q = await _run(gh)
    assert not q.message.docs, "must not send a document when the save failed"
    assert not any("נשמר ברשימת הגיבויים" in t for t in q.message.texts), q.message.texts
    assert any(t and "שגיאה בהורדת ZIP" in t for t in q.edits), q.edits


@pytest.mark.asyncio
async def test_hard_ceiling_aborts_oversized_download(monkeypatch):
    gh, _ = _install(monkeypatch, save_return="bid", content_length=0, giant=True)
    # תקרה קטנה כדי שהביטול יקרה מהר (מונע כתיבת מאות MB לדיסק בזמן הטסט)
    monkeypatch.setattr(gh, "MAX_BACKUP_BYTES", 8192, raising=True)
    q = await _run(gh)
    assert not q.message.docs
    assert any("גדול מדי לגיבוי" in t for t in q.message.texts), q.message.texts


@pytest.mark.asyncio
async def test_enospc_sends_single_message_not_generic(monkeypatch):
    gh, _ = _install(monkeypatch, save_return=OSError(errno.ENOSPC, "no space left"))
    q = await _run(gh)
    assert any("אין מקום" in t for t in q.message.texts), q.message.texts
    # finding 1: after the friendly message we return — no generic error is edited in
    assert not any(t and "שגיאה בהורדת ZIP" in t for t in q.edits), q.edits


def test_safe_remove_temp_file_tempdir_only(tmp_path, monkeypatch):
    import github_menu_handler as gh

    # tempdir מדומה בתוך ה-tmp_path המנוהל של pytest; כל הכתיבות/מחיקות בטסט
    # נשארות בתוכו — בלי לגעת ב-cwd/בספריית הפרויקט.
    fake_tmp = tmp_path / "faketmp"
    fake_tmp.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_tmp))

    # a) מוחק קובץ שנמצא תחת ה-tempdir (המדומה), בלי בדיקת קיום נפרדת
    inside = fake_tmp / "inside.zip"
    inside.write_text("x")
    assert gh._safe_remove_temp_file(str(inside)) is True
    assert not inside.exists()

    # b) נתיב שכבר נמחק -> מטופל פנימית (FileNotFoundError) ומחזיר True
    assert gh._safe_remove_temp_file(str(inside)) is True
    # c) None -> ללא שגיאה
    assert gh._safe_remove_temp_file(None) is True

    # d) מסרב למחוק נתיב מחוץ ל-tempdir — נשאר בתוך tmp_path (לא cwd)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    assert gh._safe_remove_temp_file(str(outside)) is True  # refused-safe
    assert outside.exists(), "must not delete a path outside tempdir"

    # e) מסרב לנתיבים מסוכנים (שורש/cwd/תיקיית ה-temp עצמה)
    for danger in ("/", ".", os.getcwd(), str(fake_tmp)):
        gh._safe_remove_temp_file(danger)
    assert os.path.isdir(os.getcwd())
    assert fake_tmp.is_dir()


def test_env_positive_int_parsing(monkeypatch):
    """finding 2: ערך ENV שגוי לא מפיל את טעינת המודול אלא נופל ל-default."""
    import github_menu_handler as gh

    default = 500
    name = "X_MAX_BACKUP_TEST"
    monkeypatch.delenv(name, raising=False)
    assert gh._env_positive_int(name, default) == default  # unset
    for bad in ("", "   ", "abc", "12.5", "0", "-5", "0x10"):
        monkeypatch.setenv(name, bad)
        assert gh._env_positive_int(name, default) == default, bad
    monkeypatch.setenv(name, "123")
    assert gh._env_positive_int(name, default) == 123
    monkeypatch.setenv(name, "  777  ")
    assert gh._env_positive_int(name, default) == 777


@pytest.mark.asyncio
async def test_http_response_closed_on_hard_ceiling_abort(monkeypatch):
    """finding 3: חיבור ה-HTTP (stream) נסגר גם כשההורדה בוטלה מעל התקרה הקשיחה."""
    import github_menu_handler as gh

    closed = {"n": 0}

    class _Resp:
        def __init__(self):
            self.headers = {"Content-Length": "0"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=131072):
            blk = b"x" * 2048
            for _ in range(64):
                yield blk

        def close(self):
            closed["n"] += 1

    def _req_get(_url, headers=None, stream=False, timeout=60):
        return _Resp()

    class _Repo:
        full_name = "o/r"
        name = "r"

        def get_archive_link(self, _):
            return "https://example.com/archive.zip"

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return _Repo()

    class _BM:
        def save_backup_file(self, path):
            return "bid"

        def list_backups(self, user_id):
            return []

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(gh.requests, "get", _req_get)
    monkeypatch.setattr(gh, "backup_manager", _BM())
    monkeypatch.setattr(gh, "MAX_BACKUP_BYTES", 8192, raising=True)

    q = await _run(gh)
    # ההורדה בוטלה עם הודעה ידידותית...
    assert any("גדול מדי לגיבוי" in t for t in q.message.texts), q.message.texts
    # ...וה-Response נסגר (ולא הודלף)
    assert closed["n"] >= 1

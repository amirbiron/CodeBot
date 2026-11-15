"""הורדת ZIP מגיטהאב כמשימת רקע — הרגרסיות של התקלה מ-15.11.2026.

מה קרה: לחיצה על "📦 הורד תיקייה כ־ZIP" תקעה את הבוט כמעט שבע דקות. האריזה
משכה כל קובץ בבקשת API נפרדת עם השהיה של שתי שניות לפני כל אחת, וה-handler
חיכה לה עד הסוף — והבוט מעבד עדכון אחד בכל פעם, אז אף לחיצה של אף משתמש לא
טופלה בינתיים. המשתמש לחץ שוב; הלחיצה חיכתה בתור, וכשהגיע תורה נכשלה על
"Query is too old" (``query.answer`` ישיר) ודרסה את מסך היעד של האריזה הראשונה,
שבעצם הצליחה.

הטסטים כאן בודקים את התיקון בשורש: ה-handler חוזר מיד והעבודה רצה ברקע,
לחיצה כפולה לא מתחילה אריזה שנייה, לחיצה ישנה לא נכשלת, הארכיון יורד בבקשה
אחת בענף שנבחר, ולעבודה יש תקרת זמן משלה. ההמתנה בטסטים חסומה תמיד
(``wait_for`` / ``Event.wait(timeout=...)``), כך שבאג נכשל ולא נתלה.
"""

import asyncio
import threading
import types
import zipfile
from io import BytesIO

import pytest

from _github_zip_harness import (
    FakeArchiveRepo,
    FakeArchiveResponse,
    install_archive_http,
    make_context,
    zipball_bytes,
)

USER = 5


@pytest.fixture(autouse=True)
def isolated_pending_dir(tmp_path, monkeypatch):
    """תיקיית ה-ZIP הממתין של כל טסט בנפרד — כדי שלא יישארו קבצים בתיקייה המשותפת."""
    import utils

    d = tmp_path / "pending_zip"
    d.mkdir()
    monkeypatch.setattr(utils, "_pending_zip_dir", lambda: d)
    return d


class _Msg:
    def __init__(self):
        self.docs = []
        self.texts = []

    async def reply_document(self, document=None, filename=None, caption=None):
        self.docs.append({"filename": filename, "caption": caption})

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        return types.SimpleNamespace(chat=types.SimpleNamespace(id=1), message_id=len(self.texts))


class _Query:
    def __init__(self, data, user_id=USER):
        self.data = data
        self.message = _Msg()
        self.from_user = types.SimpleNamespace(id=user_id)
        self.edits = []
        self.answers = 0

    async def answer(self, *a, **k):
        self.answers += 1
        return None

    async def edit_message_text(self, text=None, **kwargs):
        self.edits.append(text)
        return self.message


def _update(query):
    return types.SimpleNamespace(
        callback_query=query,
        effective_user=types.SimpleNamespace(id=query.from_user.id),
        effective_message=query.message,
    )


def _handler(monkeypatch, repo, *, path="skills/logo"):
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": repo.full_name}
    handler.get_user_token = lambda uid: "t"
    # הארגומנטים של כל לקוח PyGithub שנבנה — כדי לבדוק איך המשימה בונה אותו
    handler.github_client_kwargs = []

    class _Gh:
        def __init__(self, *a, **k):
            handler.github_client_kwargs.append(k)

        def get_repo(self, _):
            return repo

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(handler, "_get_path_from_cb", lambda c, d, p: path)
    return handler


def _default_repo():
    return FakeArchiveRepo(
        {
            "main": zipball_bytes(
                {
                    "skills/logo/SKILL.md": b"main",
                    "skills/logo/scripts/run.sh": b"#!/bin/sh\n",
                    "skills/logo-old/SKILL.md": b"old",
                    "README.md": b"readme",
                },
                symlinks={"skills/logo/link-to-readme": "../../README.md"},
                executables={"skills/logo/scripts/run.sh"},
            ),
            "dev": zipball_bytes({"skills/logo/SKILL.md": b"dev"}),
        }
    )


class _Gate:
    """הורדה שנעצרת באמצע עד ש-``release()`` — כדי לבדוק מה קורה בזמן שהיא רצה."""

    def __init__(self):
        self.started = threading.Event()
        self.released = threading.Event()

    def release(self):
        self.released.set()

    def install(self, monkeypatch, gh, repo):
        gate = self

        class _SlowResponse(FakeArchiveResponse):
            def iter_content(self, chunk_size=131072):
                gate.started.set()
                # חסום בזמן: באג שלא משחרר את השער נכשל אחרי חמש שניות, לא נתלה
                assert gate.released.wait(timeout=5.0), "השער לא שוחרר"
                yield from super().iter_content(chunk_size)

        def _http_request(method, url, **kwargs):
            return _SlowResponse(repo.archive_for_url(url))

        monkeypatch.setattr(gh, "http_request", _http_request)

    async def wait_started(self):
        assert await asyncio.to_thread(self.started.wait, 5.0), "ההורדה לא התחילה"


async def _click(handler, query, ctx):
    await asyncio.wait_for(handler.handle_menu_callback(_update(query), ctx), timeout=5.0)


# ------------------------------------------------- הבוט לא נתקע


class _BackupsView:
    """``backup_handler`` מזויף ב-``bot_data``: רושם שהמעבר לרשימת הגיבויים קרה."""

    def __init__(self):
        self.calls = 0

    async def _show_backups_list(self, update, context, page=1):
        self.calls += 1


class _BackupManager:
    """מנהל גיבויים מזויף למסלול הריפו המלא — שומר בהצלחה, בלי אחסון אמיתי."""

    def __init__(self):
        self.saved = []

    def save_backup_file(self, path):
        self.saved.append(path)
        return "bid"

    def list_backups(self, user_id):
        return []


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["skills/logo", ""], ids=["folder", "full-repo"])
async def test_handler_returns_while_the_download_is_still_running(monkeypatch, path):
    """השורש: ה-handler חוזר מיד, וההורדה ממשיכה ברקע — בשני המסלולים.

    לפני התיקון ה-handler חיכה לכל ההורדה, ותור העדכונים של הבוט — שמעבד
    עדכון אחד בכל פעם — חיכה איתו. כאן ההורדה חסומה עד שהטסט משחרר אותה,
    וה-handler חייב לחזור לפני כן.
    """
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo, path=path)
    backups = _BackupManager()
    monkeypatch.setattr(gh, "backup_manager", backups)
    gate = _Gate()
    gate.install(monkeypatch, gh, repo)
    ctx = make_context()
    query = _Query(f"download_zip:{path}")

    await asyncio.wait_for(handler.handle_menu_callback(_update(query), ctx), timeout=1.0)
    await gate.wait_started()
    assert len(ctx.application.tasks) == 1 and not ctx.application.tasks[0].done()
    assert not ctx.user_data.get("ghzip_pending") and not backups.saved, "העבודה הסתיימה לפני שההורדה שוחררה?"

    gate.release()
    await ctx.application.drain()
    if path:
        assert ctx.user_data.get("ghzip_pending"), "האריזה ברקע לא הגיעה לשאלת היעד"
    else:
        assert backups.saved and query.message.docs, "הגיבוי ברקע לא נשמר או לא נשלח"


@pytest.mark.asyncio
async def test_progress_is_shown_and_replaced_by_the_final_screen(monkeypatch):
    """בזמן ההורדה יש שורת התקדמות, ובסוף היא מוחלפת — לא נשארת "מוריד…" על המסך.

    בלי שום סימן התקדמות המסך נראה קפוא, וזה מה שגרם למשתמש ללחוץ שוב.
    """
    import github_menu_handler as gh

    monkeypatch.setattr(gh, "ZIP_PROGRESS_INTERVAL_SECONDS", 0.01)
    repo = _default_repo()
    handler = _handler(monkeypatch, repo)
    gate = _Gate()
    gate.install(monkeypatch, gh, repo)
    ctx = make_context()
    query = _Query("download_zip:x")

    # עריכת התקדמות איטית, שנרשמת רק כשהיא מסתיימת — כמו בטלגרם, שם העריכה
    # שמגיעה אחרונה היא שנשארת. ההורדה משתחררת בזמן שעריכה כזו עוד באוויר,
    # ולכן עדכון שלא חיכו לו בסוף היה נרשם אחרי שאלת היעד ודורס אותה.
    fast_edit = query.edit_message_text

    async def _slow_progress_edit(text=None, **kwargs):
        if text and text.startswith(("⏳ מתחבר", "⏳ מוריד", "📦 אורז")):
            await asyncio.sleep(0.2)
        return await fast_edit(text, **kwargs)

    query.edit_message_text = _slow_progress_edit

    await _click(handler, query, ctx)
    await gate.wait_started()
    gate.release()
    await ctx.application.drain()

    assert any("⏳" in (t or "") and "GitHub" in (t or "") for t in query.edits), query.edits
    assert "איפה לשמור" in (query.edits[-1] or ""), f"המסך האחרון אינו שאלת היעד: {query.edits[-1]!r}"


# ------------------------------------------------- לחיצה כפולה וישנה


@pytest.mark.asyncio
async def test_concurrent_clicks_start_a_single_job(monkeypatch):
    """שתי לחיצות במקביל ⇒ הורדה אחת. השנייה מקבלת הודעה, לא אריזה נוספת.

    רצות ב-``gather`` ולא ברצף: הבטחה של "אחת בלבד" נבדקת במקביל, אחרת הטסט
    יעבור גם על בדיקה שאינה אטומית.
    """
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo)
    gate = _Gate()
    gate.install(monkeypatch, gh, repo)
    ctx = make_context()
    q1, q2 = _Query("download_zip:x"), _Query("download_zip:x")

    await asyncio.wait_for(
        asyncio.gather(handler.handle_menu_callback(_update(q1), ctx), handler.handle_menu_callback(_update(q2), ctx)),
        timeout=5.0,
    )
    gate.release()
    await ctx.application.drain()

    assert len(ctx.application.tasks) == 1, "נפתחה יותר מאריזה אחת"
    assert repo.archive_refs == ["main"], f"הורדות: {repo.archive_refs}"
    replies = q1.message.texts + q2.message.texts
    assert any(r == gh.ZIP_JOB_ALREADY_RUNNING_TEXT for r in replies), replies
    assert len(ctx.user_data.get("ghzip_pending") or {}) == 1


@pytest.mark.asyncio
async def test_a_new_download_is_allowed_after_the_job_ends(monkeypatch):
    """הסימון "אריזה בתהליך" משתחרר בסוף — גם אחרי כשל, ולא רק אחרי הצלחה."""
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo)
    calls = {"n": 0}

    def _failing_then_ok(method, url, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeArchiveResponse(b"", status_error=RuntimeError("codeload 502"))
        return FakeArchiveResponse(repo.archive_for_url(url))

    monkeypatch.setattr(gh, "http_request", _failing_then_ok)
    ctx = make_context()

    first = _Query("download_zip:x")
    await _click(handler, first, ctx)
    await ctx.application.drain()
    assert "❌" in (first.edits[-1] or "")
    assert USER not in handler._zip_jobs_in_flight

    second = _Query("download_zip:x")
    await _click(handler, second, ctx)
    await ctx.application.drain()
    assert not second.message.texts, "הלחיצה השנייה נחסמה אחרי שהראשונה נכשלה"
    assert ctx.user_data.get("ghzip_pending")


@pytest.mark.asyncio
async def test_a_stale_click_still_packs(monkeypatch):
    """לחיצה שטלגרם כבר לא מאפשר לאשר (``Query is too old``) לא מפילה את האריזה.

    זו בדיוק הלחיצה שנכשלה בתקלה: האישור הראשון עבר דרך ``safe_answer``
    שמתעלם מהשגיאה, ואישור שני וישיר זרק אותה.
    """
    from telegram.error import BadRequest

    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo)
    install_archive_http(monkeypatch, gh, repo)
    ctx = make_context()
    query = _Query("download_zip:x")

    async def _too_old(*a, **k):
        query.answers += 1
        raise BadRequest("Query is too old and response timeout expired or query id is invalid")

    query.answer = _too_old
    await _click(handler, query, ctx)
    await ctx.application.drain()

    assert ctx.user_data.get("ghzip_pending"), f"האריזה נכשלה: {query.edits}"
    assert not any("שגיאה" in (t or "") for t in query.edits), query.edits


# ------------------------------------------------- תור ותקרת זמן


@pytest.mark.asyncio
async def test_second_user_waits_in_line_and_then_runs(monkeypatch):
    """אריזה של משתמש אחר רצה ⇒ השני רואה שהוא בתור, ומקבל את שלו אחר כך."""
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo)
    gate = _Gate()
    gate.install(monkeypatch, gh, repo)
    ctx_a, ctx_b = make_context(), make_context()
    qa, qb = _Query("download_zip:x", user_id=1), _Query("download_zip:x", user_id=2)

    await _click(handler, qa, ctx_a)
    await gate.wait_started()
    await _click(handler, qb, ctx_b)
    for _ in range(100):
        if gh.ZIP_JOB_QUEUE_WAIT_TEXT in qb.edits:
            break
        await asyncio.sleep(0.01)
    assert gh.ZIP_JOB_QUEUE_WAIT_TEXT in qb.edits, qb.edits

    gate.release()
    await ctx_a.application.drain()
    await ctx_b.application.drain()
    assert ctx_a.user_data.get("ghzip_pending") and ctx_b.user_data.get("ghzip_pending")


@pytest.mark.asyncio
async def test_waiting_in_line_has_its_own_deadline(monkeypatch):
    """ההמתנה בתור מוגבלת: מי שחיכה יותר מדי מקבל הודעה, ולא נשאר תלוי."""
    import github_menu_handler as gh

    monkeypatch.setattr(gh, "ZIP_JOB_QUEUE_WAIT_SECONDS", 0.05)
    repo = _default_repo()
    handler = _handler(monkeypatch, repo)
    gate = _Gate()
    gate.install(monkeypatch, gh, repo)
    ctx_a, ctx_b = make_context(), make_context()
    qa, qb = _Query("download_zip:x", user_id=1), _Query("download_zip:x", user_id=2)

    await _click(handler, qa, ctx_a)
    await gate.wait_started()
    await _click(handler, qb, ctx_b)
    await ctx_b.application.drain()
    assert qb.edits[-1] == gh.ZIP_JOB_QUEUE_TIMEOUT_TEXT, qb.edits
    assert 2 not in handler._zip_jobs_in_flight

    gate.release()
    await ctx_a.application.drain()
    assert ctx_a.user_data.get("ghzip_pending"), "האריזה הראשונה נפגעה מהוויתור של השנייה"


@pytest.mark.asyncio
async def test_a_slow_download_stops_at_the_deadline(monkeypatch, tmp_path):
    """לעבודה יש תקרת זמן משלה: הורדה איטית נעצרת עם הודעה, והקובץ הזמני נמחק."""
    import tempfile
    import time

    import github_menu_handler as gh

    monkeypatch.setattr(gh, "ZIP_JOB_DEADLINE_SECONDS", 0.05)
    # הקובץ הזמני של ההורדה נוצר כאן, כדי שאפשר יהיה לראות שנמחק
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    repo = _default_repo()
    handler = _handler(monkeypatch, repo)

    class _Trickle(FakeArchiveResponse):
        def iter_content(self, chunk_size=131072):
            for _ in range(50):
                time.sleep(0.02)
                yield b"x" * 10

    monkeypatch.setattr(gh, "http_request", lambda method, url, **kw: _Trickle(b""))
    ctx = make_context()
    query = _Query("download_zip:x")

    await _click(handler, query, ctx)
    await ctx.application.drain()

    assert query.edits[-1] == gh.ZIP_JOB_TIMEOUT_TEXT, query.edits
    assert not list(tmp_path.glob("*.zip")), "הקובץ הזמני של ההורדה נשאר"
    assert USER not in handler._zip_jobs_in_flight


# ------------------------------------------------- מה נארז


@pytest.mark.asyncio
async def test_folder_is_packed_from_one_archive_of_the_selected_branch(monkeypatch):
    """בקשת ארכיון אחת, בענף שנבחר — לא בקשה לכל קובץ."""
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo)
    responses = install_archive_http(monkeypatch, gh, repo)
    ctx = make_context(user_data={"browse_ref": "dev"})
    query = _Query("download_zip:x")

    await _click(handler, query, ctx)
    await ctx.application.drain()

    assert repo.archive_refs == ["dev"]
    assert len(responses) == 1 and responses[0].closed, "החיבור לא נסגר"
    entry = next(iter(ctx.user_data["ghzip_pending"].values()))
    with zipfile.ZipFile(entry["path"]) as zf:
        assert zf.read("logo/SKILL.md") == b"dev"


@pytest.mark.asyncio
async def test_packed_folder_content(monkeypatch):
    """רק התיקייה: לא השכנה ששמה מתחיל באותן אותיות, בלי קישורים סימבוליים,
    ועם הרשאת ההרצה של הסקריפט כמו ב-git."""
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo)
    install_archive_http(monkeypatch, gh, repo)
    ctx = make_context()
    query = _Query("download_zip:x")

    await _click(handler, query, ctx)
    await ctx.application.drain()

    entry = next(iter(ctx.user_data["ghzip_pending"].values()))
    with zipfile.ZipFile(entry["path"]) as zf:
        names = sorted(zf.namelist())
        assert names == ["logo/SKILL.md", "logo/scripts/run.sh"], names
        assert (zf.getinfo("logo/scripts/run.sh").external_attr >> 16) & 0o111, "הרשאת ההרצה אבדה"
    assert entry["total_files"] == 2


@pytest.mark.asyncio
async def test_folder_of_only_symlinks_says_so(monkeypatch):
    """תיקייה שיש בה רק קישורים סימבוליים קיימת — לא לשלוח את המשתמש לבדוק את הנתיב.

    נמצא באימות מול zipball אמיתי: ``node_modules/.bin`` בריפו הזה הוא 16
    קישורים ושום קובץ, והאריזה דיווחה "בדוק שהנתיב קיים".
    """
    import github_menu_handler as gh

    repo = FakeArchiveRepo({"main": zipball_bytes({"README.md": b"r"}, symlinks={"bin/tool": "../lib/tool.js"})})
    handler = _handler(monkeypatch, repo, path="bin")
    install_archive_http(monkeypatch, gh, repo)
    ctx = make_context()
    query = _Query("download_zip:x")

    await _click(handler, query, ctx)
    await ctx.application.drain()

    assert "קישורים סימבוליים" in (query.edits[-1] or ""), query.edits
    assert "בדוק שהנתיב" not in (query.edits[-1] or "")
    assert not ctx.user_data.get("ghzip_pending")


@pytest.mark.asyncio
async def test_archive_with_unexpected_layout_is_refused(monkeypatch):
    """ארכיון בלי תיקיית שורש אחת אינו zipball שאנחנו מכירים — עוצרים ולא מנחשים."""
    import github_menu_handler as gh

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a/skills/logo/SKILL.md", b"x")
        z.writestr("b/skills/logo/SKILL.md", b"y")
    repo = FakeArchiveRepo({"main": buf.getvalue()})
    handler = _handler(monkeypatch, repo)
    install_archive_http(monkeypatch, gh, repo)
    ctx = make_context()
    query = _Query("download_zip:x")

    await _click(handler, query, ctx)
    await ctx.application.drain()

    assert "אינו במבנה הצפוי" in (query.edits[-1] or ""), query.edits
    assert not ctx.user_data.get("ghzip_pending")


# ------------------------------------------------- ריפו מלא


@pytest.mark.asyncio
async def test_full_repo_download_uses_the_selected_branch(monkeypatch):
    """גם הורדת הריפו כולו מכבדת את הענף שבדפדפן, ולא תמיד את ברירת המחדל."""
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo, path="")
    install_archive_http(monkeypatch, gh, repo)
    monkeypatch.setattr(gh, "backup_manager", _BackupManager())
    backups_view = _BackupsView()
    ctx = make_context(user_data={"browse_ref": "dev"}, bot_data={"backup_handler": backups_view})
    query = _Query("download_zip:")

    await _click(handler, query, ctx)
    await ctx.application.drain()

    assert repo.archive_refs == ["dev"]
    assert query.message.docs and "dev" in query.message.docs[-1]["caption"]
    # ההודעה של שורת ההתקדמות מתחלפת ברשימת הגיבויים — המסלול הרגיל, לא החלופה שלו
    assert backups_view.calls == 1, "המעבר לרשימת הגיבויים לא קרה"


@pytest.mark.asyncio
async def test_error_text_does_not_carry_the_archive_link_token(monkeypatch):
    """כשל בהורדה לא מעביר את הקישור הזמני של GitHub להודעה, ללוג או לאירוע.

    ``requests`` מצמיד את הכתובת לחריגה (``... for url: ...``), ולריפו פרטי
    הקישור זמני ועלול לשאת טוקן. הטוקן כאן בדוי.
    """
    import logging

    import requests

    import github_menu_handler as gh

    secret = "SECRETtok3n"
    repo = _default_repo()
    handler = _handler(monkeypatch, repo, path="")
    url = f"https://codeload.github.com/o/r/legacy.zip/refs/heads/main?token={secret}"
    error = requests.HTTPError(f"404 Client Error: Not Found for url: {url}")
    monkeypatch.setattr(gh, "http_request", lambda method, u, **kw: FakeArchiveResponse(b"", status_error=error))
    events = []
    monkeypatch.setattr(gh, "emit_event", lambda name, severity="info", **f: events.append((name, f)))
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    capture = _Capture()
    gh.logger.addHandler(capture)
    try:
        ctx = make_context()
        query = _Query("download_zip:")
        await _click(handler, query, ctx)
        await ctx.application.drain()
    finally:
        gh.logger.removeHandler(capture)

    assert "❌" in (query.edits[-1] or "")
    everything = " ".join([*(t or "" for t in query.edits), *query.message.texts, *records, repr(events)])
    assert secret not in everything, "הטוקן מהקישור דלף"
    assert any(name == "github_zipball_fetch_error" for name, _ in events)


def test_pending_zip_path_rejects_unsafe_tokens(isolated_pending_dir):
    """הנתיב של ZIP ממתין נשאר תמיד בתוך התיקייה הייעודית."""
    import utils

    assert utils.pending_zip_path("abc123") == str(isolated_pending_dir / "abc123.bin")
    for bad in ("", "../x", "a/b", "a\\b", ".."):
        with pytest.raises(ValueError):
            utils.pending_zip_path(bad)

# ------------------------------------------------- ריוויו: GitHub API, קישור, harness


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["skills/logo", ""], ids=["folder", "full-repo"])
async def test_github_client_has_no_retry_that_waits_for_the_rate_limit(monkeypatch, path):
    """הלקוח של המשימה נבנה בלי retry.

    ה-retry של ברירת המחדל ב-PyGithub ממתין עד איפוס המכסה — עד שעה — ובזמן הזה
    המשימה מחזיקה את המקום בתור ואת הסימון של המשתמש, הרבה אחרי תקרת הזמן.
    """
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo, path=path)
    install_archive_http(monkeypatch, gh, repo)
    monkeypatch.setattr(gh, "backup_manager", _BackupManager())
    ctx = make_context(bot_data={"backup_handler": _BackupsView()})

    await _click(handler, _Query(f"download_zip:{path}"), ctx)
    await ctx.application.drain()

    assert handler.github_client_kwargs, "לא נבנה לקוח PyGithub"
    assert all("retry" in k and k["retry"] is None for k in handler.github_client_kwargs), handler.github_client_kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["skills/logo", ""], ids=["folder", "full-repo"])
async def test_rate_limit_gets_its_own_message(monkeypatch, path):
    """מכסה שנגמרה ⇒ הודעה שאומרת לנסות שוב, ולא שגיאה גולמית של 403.

    הזיהוי לפי ``RateLimitExceededException`` של PyGithub ולא לפי קוד הסטטוס: 403
    הוא גם הרשאה חסרה, ושם ההודעה הזו הייתה שולחת לחכות לשווא.
    """
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo, path=path)

    def _rate_limited(archive_format, ref=None):
        raise gh.RateLimitExceededException(403, {"message": "API rate limit exceeded for user"}, None)

    repo.get_archive_link = _rate_limited
    ctx = make_context()
    query = _Query(f"download_zip:{path}")

    await _click(handler, query, ctx)
    await ctx.application.drain()

    assert query.edits[-1] == gh.ZIP_JOB_RATE_LIMIT_TEXT, query.edits
    assert USER not in handler._zip_jobs_in_flight


@pytest.mark.asyncio
async def test_permission_403_is_not_reported_as_a_rate_limit(monkeypatch):
    """403 שאינו מכסה (הרשאה חסרה) מקבל את הודעת השגיאה הרגילה, לא "נסה שוב בעוד כמה דקות"."""
    import github_menu_handler as gh

    repo = _default_repo()
    handler = _handler(monkeypatch, repo)

    def _forbidden(archive_format, ref=None):
        raise gh.GithubException(403, {"message": "Resource not accessible by integration"}, None)

    repo.get_archive_link = _forbidden
    ctx = make_context()
    query = _Query("download_zip:x")

    await _click(handler, query, ctx)
    await ctx.application.drain()

    assert query.edits[-1] != gh.ZIP_JOB_RATE_LIMIT_TEXT
    assert "❌" in (query.edits[-1] or "")


class _TokenArchiveRepo(FakeArchiveRepo):
    """ריפו שמחזיר קישור ארכיון עם טוקן בשאילתה, כמו קישור זמני של ריפו פרטי."""

    SECRET = "SECRETtok3n"

    def get_archive_link(self, archive_format, ref=None):
        self.archive_refs.append(ref)
        return f"https://codeload.github.com/{self.full_name}/legacy.zip/refs/heads/x?token={self.SECRET}"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["too_big_for_telegram", "send_failed"])
async def test_backup_not_sent_links_to_the_branch_page_not_the_archive(monkeypatch, case):
    """גיבוי שלא נשלח בטלגרם מקבל קישור לעמוד הענף ב-GitHub, בלי טוקן ובלי תפוגה.

    קישור הארכיון של ריפו פרטי זמני (חמש דקות) ועלול לשאת טוקן. ענף עם ``#``
    מקודד, אחרת הקישור היה נקטע בו.
    """
    import github_menu_handler as gh

    ref = "fix#1"
    repo = _TokenArchiveRepo({ref: zipball_bytes({"a.txt": b"a"})})
    handler = _handler(monkeypatch, repo, path="")
    monkeypatch.setattr(gh, "http_request", lambda method, url, **kw: FakeArchiveResponse(repo.archives[ref]))
    monkeypatch.setattr(gh, "backup_manager", _BackupManager())
    ctx = make_context(user_data={"browse_ref": ref}, bot_data={"backup_handler": _BackupsView()})
    query = _Query("download_zip:")
    if case == "too_big_for_telegram":
        monkeypatch.setattr(gh, "MAX_ZIP_TOTAL_BYTES", 1)
    else:
        async def _send_fails(*a, **k):
            raise RuntimeError("telegram upload failed")

        query.message.reply_document = _send_fails

    await _click(handler, query, ctx)
    await ctx.application.drain()

    texts = " ".join(query.message.texts)
    assert repo.SECRET not in texts and "codeload" not in texts, texts
    assert 'href="https://github.com/o/r/tree/fix%231"' in texts, texts
    assert "Download ZIP" in texts


@pytest.mark.asyncio
async def test_harness_drain_waits_for_every_task_before_raising():
    """``drain`` לא מחזיר שליטה בזמן שמשימה אחרת עוד רצה, וזורק את הכשל אחרי שכולן נגמרו."""
    app = make_context().application
    slow_done = asyncio.Event()

    async def _fails_fast():
        raise RuntimeError("boom")

    async def _slow():
        await asyncio.sleep(0.05)
        slow_done.set()

    app.create_task(_fails_fast())
    app.create_task(_slow())
    with pytest.raises(RuntimeError, match="boom"):
        await app.drain()
    assert slow_done.is_set(), "drain החזיר שליטה בזמן שמשימה אחרת עוד רצה"
    with pytest.raises(RuntimeError, match="boom"):
        await app.drain()

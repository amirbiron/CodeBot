"""תמונת קוד באיכות מלאה: ה-PNG נשמר ב-Drive כ-PNG, יורד כקובץ, וההודעה אחרי השמירה נושאת קישור ולא מזהה.

הבדיקות עוברות דרך אותם ממשקים שהייצור עובר בהם: ``upload_bytes`` מול דמה של שירות ה-Drive (``files().create``, ‏``MediaIoBaseUpload``),
והכפתורים דרך ``handle_callback_query`` ודרך התבנית שנרשמה ל-handler של התמונות — לא מחרוזת שהועתקה לכאן.
"""

import io
import logging
import re
import sys
import types
from types import SimpleNamespace

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"full-quality"
LINK = "https://drive.google.com/file/d/fid-png/view?usp=drivesdk"


# --- שירות ה-Drive -------------------------------------------------------------------------------


def _drive_service(monkeypatch, response):
    """``services.google_drive_service`` עם שירות Drive מדומה; מחזיר את המודול ואת מה שההעלאה קיבלה."""
    import services.google_drive_service as gds

    seen = {}

    class _Req:
        def next_chunk(self):
            return None, response

    class _Files:
        def create(self, body=None, media_body=None, fields=None):
            seen["fields"] = fields
            seen["body"] = body
            return _Req()

    class _Svc:
        def files(self):
            return _Files()

    class _Media:
        def __init__(self, fh, mimetype=None, resumable=False, chunksize=None):
            seen["mimetype"] = mimetype

    monkeypatch.setattr(gds, "get_drive_service", lambda uid, *, owner: _Svc(), raising=True)
    monkeypatch.setattr(gds, "ensure_subpath", lambda uid, sub, *, owner: "folder-1", raising=True)
    monkeypatch.setattr(gds, "MediaIoBaseUpload", _Media, raising=True)
    return gds, seen


def test_a_code_image_is_uploaded_as_png_and_comes_back_with_its_link(monkeypatch):
    gds, seen = _drive_service(monkeypatch, {"id": "fid-png", "webViewLink": LINK})

    uploaded = gds.upload_bytes_with_link(7, "a.py.png", PNG, sub_path="code_images", owner="bot", mimetype="image/png")

    assert uploaded == gds.DriveUpload(file_id="fid-png", web_view_link=LINK)
    assert seen["mimetype"] == "image/png"
    # הקישור מתבקש מה-API — הוא לא חוזר בלי ``fields``
    assert "webViewLink" in [part.strip() for part in seen["fields"].split(",")]
    assert "mimeType" not in seen["body"]


def test_a_backup_upload_without_a_mimetype_stays_zip(monkeypatch):
    gds, seen = _drive_service(monkeypatch, {"id": "fid-zip", "webViewLink": LINK})

    fid = gds.upload_bytes(7, "BKP_all_v1.zip", b"PK\x03\x04", sub_path="all", owner="bot")

    assert fid == "fid-zip"
    assert seen["mimetype"] == "application/zip"


def test_a_backup_named_without_zip_still_uploads_as_zip(monkeypatch):
    # ברירת מחדל ולא גזירה מהסיומת: שם הקובץ לא משנה את הסוג של גיבוי
    gds, seen = _drive_service(monkeypatch, {"id": "fid-zip"})

    assert gds.upload_bytes(7, "backup-without-suffix", b"PK\x03\x04", sub_path="all", owner="webapp") == "fid-zip"
    assert seen["mimetype"] == "application/zip"


@pytest.mark.parametrize(
    "link",
    [None, 123, "", "javascript:alert(1)", "http://drive.google.com/file/d/x/view", "https://", "/file/d/x/view"],
    ids=["missing", "not-a-string", "empty", "javascript", "http", "no-host", "relative"],
)
def test_a_link_that_is_not_an_https_url_is_dropped_and_the_upload_still_counts(monkeypatch, link):
    response = {"id": "fid-png"}
    if link is not None:
        response["webViewLink"] = link
    gds, _seen = _drive_service(monkeypatch, response)

    uploaded = gds.upload_bytes_with_link(7, "a.py.png", PNG, sub_path="code_images", owner="bot", mimetype="image/png")

    assert uploaded == gds.DriveUpload(file_id="fid-png", web_view_link=None)


@pytest.mark.parametrize("response", [{"webViewLink": LINK}, {"id": 12345}, {"id": ""}, ["fid"]], ids=["no-id", "int-id", "empty-id", "not-a-dict"])
def test_a_response_without_a_string_id_is_a_failed_upload(monkeypatch, caplog, response):
    gds, _seen = _drive_service(monkeypatch, response)

    with caplog.at_level(logging.WARNING, logger=gds.__name__):
        assert gds.upload_bytes_with_link(7, "a.py.png", PNG, sub_path="code_images", owner="bot", mimetype="image/png") is None
        assert gds.upload_bytes(7, "a.zip", b"PK", sub_path="zip", owner="bot") is None

    assert sum("op=upload_bytes.response" in r.getMessage() for r in caplog.records) == 2


# --- הבוט -----------------------------------------------------------------------------------------


class _App:
    def __init__(self):
        self.handlers = []

    def add_handler(self, handler, *a, **k):
        self.handlers.append(handler)


class _Msg:
    def __init__(self, calls):
        self.calls = calls

    async def reply_photo(self, *a, **k):
        self.calls.append(("reply_photo", a, k))

    async def reply_document(self, *a, **k):
        self.calls.append(("reply_document", a, k))

    async def reply_text(self, *a, **k):
        self.calls.append(("reply_text", a, k))


class _Query:
    def __init__(self, data, calls):
        self.data = data
        self.calls = calls
        self.message = _Msg(calls)
        self.from_user = SimpleNamespace(id=42)

    async def answer(self, *a, **k):
        self.calls.append(("answer", a, k))

    async def edit_message_text(self, *a, **k):
        self.calls.append(("edit_message_text", a, k))

    async def edit_message_caption(self, *a, **k):
        self.calls.append(("edit_message_caption", a, k))

    async def edit_message_reply_markup(self, *a, **k):
        self.calls.append(("edit_message_reply_markup", a, k))


class _Bot:
    """מה שהבדיקות צריכות מהבוט: הקובץ, המחולל וה-Drive, כולם מדומים ומתועדים."""

    def __init__(self, monkeypatch, *, upload=None):
        import bot_handlers as mod
        from rate_limiter import RateLimiter

        self.mod = mod
        self.requested = []  # שמות הקבצים שהכפתורים ביקשו מהמסד
        self.renders = []  # (הגדרות המחולל, הארגומנטים של generate_image)
        self.uploads = []
        bot = self

        class _Facade:
            def get_latest_version(self, uid, fn):
                bot.requested.append(fn)
                return {"file_name": fn, "code": "print('x')", "programming_language": "python"}

        class _Gen:
            def __init__(self, *a, **k):
                self.init = k

            def generate_image(self, *a, **k):
                bot.renders.append((self.init, k))
                return PNG

        monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())
        monkeypatch.setattr(mod, "CodeImageGenerator", _Gen, raising=True)
        # מגביל אמיתי עם מצב משלו לכל בדיקה — המגביל של המודול זוכר לחיצות בין בדיקות
        monkeypatch.setattr(mod, "image_rate_limiter", RateLimiter(max_per_minute=100_000), raising=True)

        from services.google_drive_service import DriveUpload  # הצורה האמיתית של מה שההעלאה מחזירה

        def _upload(uid, filename, data, folder_id=None, sub_path=None, *, owner, mimetype):
            bot.uploads.append({"filename": filename, "data": data, "sub_path": sub_path, "owner": owner, "mimetype": mimetype})
            if upload is not None:
                return upload()
            return DriveUpload(file_id="fid-png", web_view_link=LINK)

        fake = types.ModuleType("services.google_drive_service")
        fake.upload_bytes_with_link = _upload
        monkeypatch.setitem(sys.modules, "services.google_drive_service", fake)

        self.app = _App()
        self.h = mod.AdvancedBotHandlers(self.app)
        self.ctx = SimpleNamespace(user_data={}, args=[])

    async def press(self, data):
        calls = []
        await self.h.handle_callback_query(SimpleNamespace(effective_user=SimpleNamespace(id=42), callback_query=_Query(data, calls)), self.ctx)
        return calls

    async def image_command(self, file_name):
        calls = []
        self.ctx.args = [file_name]
        upd = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=_Msg(calls))
        await self.h.image_command(upd, self.ctx)
        return calls

    async def image_keyboard(self, file_name):
        """המקלדת שמתחת לתמונה ש-``/image`` שלח — מה שהמשתמש מקבל, ולא פונקציה פנימית."""
        rows = _layout(_only(await self.image_command(file_name), "reply_photo")[2]["reply_markup"])
        self.requested.clear()
        self.renders.clear()
        return rows

    async def settings_keyboard(self, file_name):
        """תפריט ההגדרות שנפתח בלחיצה על "📝 ערוך הגדרות" במקלדת של התמונה."""
        rows = await self.image_keyboard(file_name)
        edit_cb = rows[0][1][1]
        return _layout(_only(await self.press(edit_cb), "edit_message_text")[2]["reply_markup"])

    async def button(self, file_name, label):
        """ה-``callback_data`` של הכפתור ``label`` במקלדת של התמונה."""
        found = [cb for row in await self.image_keyboard(file_name) for text, cb in row if text == label]
        assert len(found) == 1, (label, found)
        return found[0]

    def image_pattern(self):
        """התבנית שנרשמה ל-handler של כפתורי התמונה — אותה תבנית ש-PTB מפעיל ב-``re.match``."""
        patterns = []
        for handler in self.app.handlers:
            pattern = getattr(handler, "pattern", None)
            pattern = getattr(pattern, "pattern", pattern)
            if isinstance(pattern, str) and "regenerate_image_" in pattern:
                patterns.append(pattern)
        assert len(patterns) == 1, patterns
        return patterns[0]


def _layout(markup):
    return [[(btn.text, btn.callback_data) for btn in row] for row in markup.inline_keyboard]


def _only(calls, name):
    found = [c for c in calls if c[0] == name]
    assert len(found) == 1, calls
    return found[0]


def _no_boundary_error(calls):
    # הגבול של handle_callback_query עונה כך על כל חריגה שלא טופלה
    assert not any("אירעה שגיאה" in str(c) for c in calls), calls


@pytest.mark.asyncio
async def test_the_image_keyboard_has_a_header_and_both_full_quality_buttons(monkeypatch):
    bot = _Bot(monkeypatch)

    rows = await bot.image_keyboard("a.py")

    assert [[text for text, _cb in row] for row in rows] == [
        ["🔄 צור מחדש", "📝 ערוך הגדרות"],
        ["לתמונה באיכות גבוהה"],
        ["💾 שמור ב-Drive", "⬇️ הורד כקובץ"],
    ]
    # שורת הכותרת היא אותו מנגנון כמו כותרות הסעיפים בתפריט ההגדרות
    header_prefix = rows[1][0][1].split(":", 1)[0] + ":"
    settings_headers = [row[0][1] for row in await bot.settings_keyboard("a.py") if len(row) == 1 and row[0][1].startswith(header_prefix)]
    assert header_prefix == "img_section:" and settings_headers, settings_headers


@pytest.mark.asyncio
async def test_every_place_that_shows_a_code_image_shows_the_same_keyboard(monkeypatch):
    bot = _Bot(monkeypatch)
    file_name = "קובץ-עם-שם-ארוך-מאוד-בעברית-שלא-נכנס-בשישים-וארבעה-בייטים.py"

    from_command = await bot.image_keyboard(file_name)
    from_regenerate = _layout(_only(await bot.press(from_command[0][0][1]), "reply_photo")[2]["reply_markup"])
    done_cb = (await bot.settings_keyboard(file_name))[-1][0][1]
    from_settings_done = _layout(_only(await bot.press(done_cb), "edit_message_reply_markup")[2]["reply_markup"])

    assert from_command == from_regenerate == from_settings_done


_NAMES = ["a.py"] + ["ש" * n + ".py" for n in range(1, 41)] + ["x" * 90 + ".py"]


@pytest.mark.asyncio
@pytest.mark.parametrize("file_name", _NAMES, ids=lambda n: f"{len(n.encode('utf-8'))}B")
async def test_every_image_button_fits_telegram_and_reaches_the_image_handler_with_its_file(monkeypatch, file_name):
    bot = _Bot(monkeypatch)
    pattern = bot.image_pattern()
    # פתקית קיימת, כדי שגם הכפתור "נקה" יופיע במקלדת ההגדרות
    bot.h._set_image_setting(bot.ctx, file_name, "note", "n")
    result_rows = await bot.image_keyboard(file_name)
    settings_rows = await bot.settings_keyboard(file_name)
    buttons = [cb for rows in (result_rows, settings_rows) for row in rows for _text, cb in row]

    for cb in buttons:
        # InlineKeyboardButton.MAX_CALLBACK_DATA — טלגרם סופר בייטים של UTF-8, לא תווים
        assert 1 <= len(cb.encode("utf-8")) <= 64, cb
        # כמו CallbackQueryHandler.check_update ב-PTB: re.match מול התבנית שנרשמה
        assert re.match(pattern, cb), cb

    for cb in buttons:
        if cb.startswith("img_section:"):
            continue
        bot.requested.clear()
        bot.h._set_image_setting(bot.ctx, file_name, "note", "n")
        calls = await bot.press(cb)
        _no_boundary_error(calls)
        if cb.startswith(("regenerate_image_", "save_to_drive_", "img_download:")):
            assert bot.requested == [file_name], cb
        elif cb.startswith("edit_image_settings_"):
            assert _layout(_only(calls, "edit_message_text")[2]["reply_markup"]) == settings_rows
        elif cb.startswith(("img_set_theme:", "img_set_style:", "img_set_width:", "img_set_font:")):
            key = {"img_set_theme:": "theme", "img_set_style:": "style", "img_set_width:": "width", "img_set_font:": "font"}[cb.split(":", 1)[0] + ":"]
            assert key in bot.ctx.user_data["img_settings"][file_name], cb
        elif cb.startswith("img_note_prompt:"):
            assert bot.ctx.user_data.pop("waiting_for_image_note")["file_name"] == file_name
        elif cb.startswith("img_note_clear:"):
            assert "note" not in bot.ctx.user_data.get("img_settings", {}).get(file_name, {})
        elif cb.startswith("img_settings_done:"):
            assert _layout(_only(calls, "edit_message_reply_markup")[2]["reply_markup"]) == result_rows
        else:  # pragma: no cover - כפתור חדש שהבדיקה לא מכירה
            pytest.fail(f"כפתור בלי בדיקת יעד: {cb}")


@pytest.mark.asyncio
async def test_the_header_button_is_answered_and_does_nothing(monkeypatch):
    bot = _Bot(monkeypatch)
    header = await bot.button("a.py", "לתמונה באיכות גבוהה")

    calls = await bot.press(header)

    assert calls and {c[0] for c in calls} == {"answer"}
    assert bot.requested == [] and bot.renders == [] and bot.uploads == []


@pytest.mark.asyncio
async def test_download_sends_the_png_itself_as_a_document(monkeypatch):
    bot = _Bot(monkeypatch)
    download = await bot.button("a.py", "⬇️ הורד כקובץ")

    calls = await bot.press(download)

    _no_boundary_error(calls)
    assert not [c for c in calls if c[0] == "reply_photo"]
    _name, args, kwargs = _only(calls, "reply_document")
    document = kwargs.get("document", args[0] if args else None)
    assert document.filename == "a.py.png"
    sent = document.obj.getvalue() if isinstance(document.obj, io.BytesIO) else document.obj
    assert sent == PNG
    assert kwargs.get("parse_mode") == "HTML"


@pytest.mark.asyncio
async def test_drive_and_download_make_the_same_image_with_the_same_name(monkeypatch):
    bot = _Bot(monkeypatch)
    for key, value in (("theme", "github"), ("style", "dracula"), ("width", 1400), ("font", "jetbrains"), ("note", "הערה")):
        bot.h._set_image_setting(bot.ctx, "a.py", key, value)
    save = await bot.button("a.py", "💾 שמור ב-Drive")
    download = await bot.button("a.py", "⬇️ הורד כקובץ")
    await bot.image_command("a.py")
    shown = bot.renders[-1]
    bot.renders.clear()

    drive_calls = await bot.press(save)
    download_calls = await bot.press(download)

    _no_boundary_error(drive_calls + download_calls)
    # שתיהן — והתמונה שהמשתמש ראה — מאותן הגדרות
    assert bot.renders == [shown, shown]
    init, kwargs = shown
    assert init == {"style": "dracula", "theme": "github", "font_family": "jetbrains"}
    assert kwargs["max_width"] == 1400 and kwargs["note"] == "הערה"
    [upload] = bot.uploads
    document = _only(download_calls, "reply_document")[2]["document"]
    assert upload["filename"] == document.filename == "a.py.png"
    assert upload == {"filename": "a.py.png", "data": PNG, "sub_path": "code_images", "owner": "bot", "mimetype": "image/png"}


@pytest.mark.asyncio
async def test_the_drive_message_links_to_the_file_and_escapes_the_link(monkeypatch):
    from services.google_drive_service import DriveUpload

    link = 'https://drive.google.com/file/d/fid/view?usp=drivesdk&x="y"'
    bot = _Bot(monkeypatch, upload=lambda: DriveUpload(file_id="fid-raw-id", web_view_link=link))
    save = await bot.button("<a>.py", "💾 שמור ב-Drive")

    calls = await bot.press(save)

    _no_boundary_error(calls)
    _name, args, kwargs = _only(calls, "reply_text")
    text = args[0]
    assert '<a href="https://drive.google.com/file/d/fid/view?usp=drivesdk&amp;x=&quot;y&quot;">פתיחה ב-Drive</a>' in text
    assert "&lt;a&gt;.py" in text and "fid-raw-id" not in text
    assert kwargs.get("parse_mode") == "HTML"
    # הודעה חדשה — התמונה, הכיתוב שלה והכפתורים שלה לא נערכו
    assert not [c for c in calls if c[0].startswith("edit_message")]


@pytest.mark.asyncio
async def test_a_save_without_a_link_says_saved_without_the_id(monkeypatch, caplog):
    from services.google_drive_service import DriveUpload

    bot = _Bot(monkeypatch, upload=lambda: DriveUpload(file_id="fid-raw-id", web_view_link=None))
    save = await bot.button("a.py", "💾 שמור ב-Drive")

    with caplog.at_level(logging.WARNING, logger="bot_handlers"):
        calls = await bot.press(save)

    text = _only(calls, "reply_text")[1][0]
    assert text.startswith("✅ נשמר ל-Drive") and "fid-raw-id" not in text and "<a " not in text
    assert any(r.getMessage() == "drive_code_image_no_link" for r in caplog.records)


@pytest.mark.asyncio
async def test_a_failed_upload_says_the_save_failed(monkeypatch):
    bot = _Bot(monkeypatch, upload=lambda: None)
    save = await bot.button("a.py", "💾 שמור ב-Drive")

    calls = await bot.press(save)

    assert _only(calls, "reply_text")[1][0] == "⚠️ שמירה ל-Drive לא הצליחה (בדוק הרשאות/חיבור)"


@pytest.mark.asyncio
async def test_a_bug_in_the_upload_is_not_reported_as_a_drive_connection_problem(monkeypatch, caplog):
    def _bug():
        raise AttributeError("'NoneType' object has no attribute 'files'")

    bot = _Bot(monkeypatch, upload=_bug)
    save = await bot.button("a.py", "💾 שמור ב-Drive")

    with caplog.at_level(logging.WARNING, logger="bot_handlers"):
        calls = await bot.press(save)

    assert not any("בדוק הרשאות/חיבור" in str(c) for c in calls), calls
    # הגיע לגבול של handle_callback_query, עם השורה של ההעלאה וה-traceback שלה
    assert any("אירעה שגיאה" in str(c) for c in calls), calls
    [record] = [r for r in caplog.records if r.getMessage() == "drive_code_image_upload_failed"]
    assert record.exc_info and record.exc_info[0] is AttributeError

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
    [
        None,
        123,
        "",
        "javascript:alert(1)",
        "http://drive.google.com/file/d/x/view",
        "https://",
        "/file/d/x/view",
        # urlsplit זורק ValueError על מארח פגום — סוגר מרובע שלא נסגר, או תו שנורמליזציית NFKC הופכת לתו אסור
        "https://[drive.google.com/file/d/x/view",
        "https://＃drive.google.com/file/d/x/view",
    ],
    ids=["missing", "not-a-string", "empty", "javascript", "http", "no-host", "relative", "unclosed-bracket", "nfkc-invalid-host"],
)
def test_a_link_that_is_not_an_https_url_is_dropped_and_the_upload_still_counts(monkeypatch, link):
    response = {"id": "fid-png"}
    if link is not None:
        response["webViewLink"] = link
    gds, _seen = _drive_service(monkeypatch, response)

    uploaded = gds.upload_bytes_with_link(7, "a.py.png", PNG, sub_path="code_images", owner="bot", mimetype="image/png")

    assert uploaded == gds.DriveUpload(file_id="fid-png", web_view_link=None)
    # גם המסלול של הגיבויים: הקובץ עלה, והמזהה חוזר
    assert gds.upload_bytes(7, "BKP_all_v1.zip", b"PK", sub_path="all", owner="bot") == "fid-png"


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
    """מה שהבדיקות צריכות מהבוט: הקובץ וגרסאותיו, היצירה וה-Drive, כולם מדומים ומתועדים."""

    def __init__(self, monkeypatch, *, upload=None):
        import bot_handlers as mod
        from bson.objectid import ObjectId
        from rate_limiter import RateLimiter

        self.mod = mod
        self._object_id = ObjectId
        self.requested = []  # שמות הקבצים שהכפתורים ביקשו מהמסד לפי שם (הגרסה האחרונה)
        self.pinned = []  # מזהי הגרסאות שהכפתורים ביקשו מהמסד לפי ``_id``
        self.renders = []  # הבקשות ש-``render_png`` קיבל — מה שהתהליך הנפרד היה יוצר
        self.uploads = []
        self.versions = {}  # מזהה גרסה ← מסמך, כמו במסד
        self.latest_id = None
        self.pinned_error = None  # חריגה ש-``get_version_by_id`` זורק — כשל של המסד, כמו ב-``Repository.find_version_by_id``
        self.save("print('x')")
        bot = self

        class _Facade:
            def get_latest_version(self, uid, fn):
                bot.requested.append(fn)
                return dict(bot.versions[bot.latest_id], file_name=fn)

            def get_version_by_id(self, uid, version_id):
                bot.pinned.append(version_id)
                if bot.pinned_error is not None:
                    raise bot.pinned_error
                doc = bot.versions.get(version_id)
                return dict(doc) if doc else None

        def _render_png(request):
            bot.renders.append(dict(request))
            return PNG

        monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())
        # זמינות היצירה נבדקת לפי המחלקה; היצירה עצמה רצה בתהליך נפרד, ו-``render_png`` הוא התפר שלה
        monkeypatch.setattr(mod, "CodeImageGenerator", object, raising=True)
        monkeypatch.setattr(mod.code_image_render, "render_png", _render_png, raising=True)
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

    def save(self, code, file_name="a.py"):
        """שמירה של גרסה חדשה: מסמך חדש עם ``_id`` משלו, והוא הגרסה האחרונה."""
        version_id = str(self._object_id())
        self.versions[version_id] = {"_id": self._object_id(version_id), "file_name": file_name, "code": code, "programming_language": "python"}
        self.latest_id = version_id
        return version_id

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
        self.pinned.clear()
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

    # אותה גרסה הוצגה ב-/image וב"צור מחדש", ולכן אותה מקלדת בדיוק, כולל מזהה הגרסה שבכפתורים
    assert from_command == from_regenerate
    pinned = f"img_download:{bot.latest_id}:"
    assert from_command[2][1][1].startswith(pinned)
    # בחזרה מעריכת ההגדרות אין גרסה לנעוץ (כפתורי ההגדרות לא נושאים אותה), ולכן ``-`` — אחרת זו אותה מקלדת
    assert from_settings_done == _layout(bot.h._build_image_result_keyboard(bot.ctx, file_name))
    assert from_settings_done[2][1][1].startswith("img_download:-:")
    assert [t for row in from_settings_done for t, _ in row] == [t for row in from_command for t, _ in row]


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
        bot.pinned.clear()
        bot.h._set_image_setting(bot.ctx, file_name, "note", "n")
        calls = await bot.press(cb)
        _no_boundary_error(calls)
        if cb.startswith("regenerate_image_"):
            assert bot.requested == [file_name] and bot.pinned == [], cb
        elif cb.startswith(("img_drive:", "img_download:")):
            # הגרסה שהוצגה, לפי ה-``_id`` שבכפתור — בלי לחפש לפי שם
            assert bot.pinned == [bot.latest_id] and bot.requested == [], cb
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
            # המקלדת של התמונה בלי מזהה הגרסה — כפתורי ההגדרות לא נושאים אותו. בלי המזהה הכפתור קצר יותר, ולכן שם שנכנס
            # בלעדיו נשאר שם ולא טוקן, ואי אפשר רק להחליף את המזהה ב-``-``
            unpinned = _layout(bot.h._build_image_result_keyboard(bot.ctx, file_name))
            assert _layout(_only(calls, "edit_message_reply_markup")[2]["reply_markup"]) == unpinned
            assert [t for row in unpinned for t, _ in row] == [t for row in result_rows for t, _ in row]
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
    # כשההגדרות לא השתנו מאז ההצגה, שתיהן זהות לתמונה שהוצגה
    assert bot.renders == [shown, shown]
    assert {k: shown[k] for k in ("style", "theme", "font_family", "width", "note")} == {
        "style": "dracula", "theme": "github", "font_family": "jetbrains", "width": 1400, "note": "הערה",
    }
    [upload] = bot.uploads
    document = _only(download_calls, "reply_document")[2]["document"]
    assert upload["filename"] == document.filename == "a.py.png"
    assert upload == {"filename": "a.py.png", "data": PNG, "sub_path": "code_images", "owner": "bot", "mimetype": "image/png"}


@pytest.mark.asyncio
async def test_after_the_file_changes_drive_and_download_render_the_version_that_was_shown(monkeypatch):
    bot = _Bot(monkeypatch)
    shown_id = bot.latest_id
    save = await bot.button("a.py", "💾 שמור ב-Drive")
    download = await bot.button("a.py", "⬇️ הורד כקובץ")
    regenerate = await bot.button("a.py", "🔄 צור מחדש")

    bot.save("print('changed')")  # למשל מהוובאפ, אחרי שהתמונה נשלחה
    for cb in (save, download, regenerate):
        _no_boundary_error(await bot.press(cb))

    drive, downloaded, regenerated = bot.renders
    assert drive["code"] == downloaded["code"] == "print('x')"
    assert bot.pinned == [shown_id, shown_id]
    # "צור מחדש" יוצר מהגרסה האחרונה, כמו קודם
    assert regenerated["code"] == "print('changed')"


@pytest.mark.asyncio
async def test_the_settings_are_the_ones_at_click_time(monkeypatch):
    # בזרימה הרגילה שינוי הגדרות נגמר ב"צור מחדש", ולכן ההגדרות של רגע הלחיצה הן גם של התמונה שמעל הכפתורים.
    # אחרי "ערוך הגדרות" ← "שמור", לפני "צור מחדש", התמונה שמעל הכפתורים עדיין בהגדרות הקודמות.
    bot = _Bot(monkeypatch)
    download = await bot.button("a.py", "⬇️ הורד כקובץ")

    bot.h._set_image_setting(bot.ctx, "a.py", "theme", "github")
    _no_boundary_error(await bot.press(download))

    [downloaded] = bot.renders
    assert downloaded["theme"] == "github" and downloaded["code"] == "print('x')"


@pytest.mark.asyncio
async def test_without_a_version_in_the_button_the_latest_version_is_used(monkeypatch):
    bot = _Bot(monkeypatch)
    done_cb = (await bot.settings_keyboard("a.py"))[-1][0][1]
    restored = _layout(_only(await bot.press(done_cb), "edit_message_reply_markup")[2]["reply_markup"])
    download = restored[2][1][1]
    assert download.startswith("img_download:-:")

    bot.save("print('changed')")
    _no_boundary_error(await bot.press(download))

    assert bot.pinned == [] and bot.requested == ["a.py"]
    assert bot.renders[-1]["code"] == "print('changed')"


@pytest.mark.asyncio
async def test_a_version_that_is_no_longer_available_falls_back_to_the_latest_and_says_so(monkeypatch, caplog):
    bot = _Bot(monkeypatch)
    shown_id = bot.latest_id
    download = await bot.button("a.py", "⬇️ הורד כקובץ")
    bot.save("print('changed')")
    del bot.versions[shown_id]  # נמחקה — או מזהה שאינו של המשתמש, שעליו המסד עונה אותו דבר

    with caplog.at_level(logging.WARNING, logger="bot_handlers"):
        calls = await bot.press(download)

    _no_boundary_error(calls)
    assert bot.pinned == [shown_id] and bot.requested == ["a.py"]
    assert bot.renders[-1]["code"] == "print('changed')"
    caption = _only(calls, "reply_document")[2]["caption"]
    assert "כבר לא זמינה" in caption
    assert any(r.getMessage() == "code_image_pinned_version_unavailable" for r in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["database-error", "no-files-facade"],
)
async def test_a_failed_read_of_the_pinned_version_is_an_error_and_not_an_image_of_another_version(monkeypatch, caplog, failure):
    from pymongo.errors import PyMongoError

    bot = _Bot(monkeypatch)
    download = await bot.button("a.py", "⬇️ הורד כקובץ")
    save = await bot.button("a.py", "💾 שמור ב-Drive")
    bot.save("print('changed')")
    if failure == "database-error":
        bot.pinned_error = PyMongoError("primary unreachable")
    else:
        # ``_get_files_facade_or_none`` מחזירה ``None`` כשבניית הפסאדה נכשלה — אי אפשר לדעת אם הגרסה קיימת
        monkeypatch.setattr(bot.mod, "_get_files_facade_or_none", lambda: None)

    with caplog.at_level(logging.WARNING, logger="bot_handlers"):
        calls = await bot.press(download) + await bot.press(save)

    # כשל מגיע לגבול של handle_callback_query, ולא הופך ל"לא זמינה" שיוצר מהגרסה האחרונה
    assert sum("אירעה שגיאה" in str(c) for c in calls if c[0] == "edit_message_text") == 2, calls
    assert bot.requested == [] and bot.renders == [] and bot.uploads == []
    assert not [c for c in calls if c[0] in ("reply_document", "reply_photo")]
    assert not any(r.getMessage() == "code_image_pinned_version_unavailable" for r in caplog.records)
    expected = PyMongoError if failure == "database-error" else RuntimeError
    records = [r for r in caplog.records if r.getMessage() == "code_image_pinned_version_read_failed"]
    assert len(records) == 2 and all(r.exc_info and r.exc_info[0] is expected for r in records)


# --- כפתור מלפני הפעלה מחדש של הבוט --------------------------------------------------------------
# לבוט אין persistence: הפעלה מחדש (דיפלוי) מאפסת את ``user_data``, ואיתו את המיפוי מטוקן לשם שכפתורים של שם ארוך נושאים.

_LONG_NAME = "קובץ-עם-שם-ארוך-מאוד-בעברית-שלא-נכנס-בשישים-וארבעה-בייטים.py"


def _restart(bot):
    bot.ctx.user_data.clear()


def _expired(calls):
    """הכפתור ענה שהוא פג תוקף — ולא "לא נמצא" על שם כמו ``tok:...``, ולא שגיאה."""
    _no_boundary_error(calls)
    texts = [c[1][0] for c in calls if c[0] == "reply_text"]
    assert len(texts) == 1 and "פג תוקף" in texts[0], calls
    assert not any("לא נמצא" in str(c) or "tok:" in str(c) for c in calls), calls


@pytest.mark.asyncio
async def test_after_a_restart_drive_and_download_still_make_the_image_with_the_real_name(monkeypatch):
    bot = _Bot(monkeypatch)
    bot.save("print('x')", file_name=_LONG_NAME)
    download = await bot.button(_LONG_NAME, "⬇️ הורד כקובץ")
    save = await bot.button(_LONG_NAME, "💾 שמור ב-Drive")
    assert ":tok:" in download and ":tok:" in save  # השם לא נכנס ב-64 בייטים, ולכן הכפתור נושא טוקן
    _restart(bot)

    download_calls = await bot.press(download)
    drive_calls = await bot.press(save)

    _no_boundary_error(download_calls + drive_calls)
    # השם מגיע ממסמך הגרסה, בלי המיפוי — ולא נשאל שום שם במסד
    assert bot.requested == [] and len(bot.pinned) == 2
    assert [r["filename"] for r in bot.renders] == [_LONG_NAME, _LONG_NAME]
    document = _only(download_calls, "reply_document")[2]
    assert document["document"].filename == f"{_LONG_NAME}.png"
    assert _LONG_NAME in document["caption"]
    assert [u["filename"] for u in bot.uploads] == [f"{_LONG_NAME}.png"]
    assert _LONG_NAME in _only(drive_calls, "reply_text")[1][0]
    assert not any("tok:" in str(c) for c in download_calls + drive_calls)


@pytest.mark.asyncio
async def test_after_a_restart_drive_and_download_whose_version_is_gone_say_the_button_expired(monkeypatch):
    bot = _Bot(monkeypatch)
    shown_id = bot.save("print('x')", file_name=_LONG_NAME)
    download = await bot.button(_LONG_NAME, "⬇️ הורד כקובץ")
    save = await bot.button(_LONG_NAME, "💾 שמור ב-Drive")
    bot.save("print('changed')", file_name=_LONG_NAME)
    del bot.versions[shown_id]
    _restart(bot)

    for cb in (download, save):
        _expired(await bot.press(cb))

    # בלי השם אין גרסה אחרונה לחפש: לא נשאל שום שם במסד, ושום תמונה לא נוצרה
    assert bot.pinned == [shown_id, shown_id] and bot.requested == []
    assert bot.renders == [] and bot.uploads == []


@pytest.mark.asyncio
async def test_after_a_restart_every_image_button_without_a_version_says_it_expired(monkeypatch):
    bot = _Bot(monkeypatch)
    bot.save("print('x')", file_name=_LONG_NAME)
    bot.h._set_image_setting(bot.ctx, _LONG_NAME, "note", "n")  # כדי שגם "נקה" יופיע
    result_rows = await bot.image_keyboard(_LONG_NAME)
    settings_rows = await bot.settings_keyboard(_LONG_NAME)
    buttons = [
        cb
        for rows in (result_rows, settings_rows)
        for row in rows
        for _text, cb in row
        if not cb.startswith("img_section:") and not re.match(r"^img_(?:drive|download):[0-9a-f]{24}:", cb)
    ]
    # כפתור "שמור ב-Drive" מלפני ``img_drive:``, בלי מזהה גרסה: ``save_to_drive_tok:<טוקן>``
    drive_cb = result_rows[2][0][1]  # img_drive:<id>:tok:<טוקן>
    buttons.append(f"save_to_drive_{drive_cb.split(':', 2)[2]}")
    assert all("tok:" in cb for cb in buttons), buttons
    assert len(buttons) >= 10, buttons  # צור מחדש, ערוך הגדרות, וכל תפריט ההגדרות
    _restart(bot)

    for cb in buttons:
        _expired(await bot.press(cb))

    assert bot.requested == [] and bot.renders == [] and bot.uploads == []
    # שום הגדרה לא נשמרה תחת שם כמו ``tok:...``, ושום פתקית לא מחכה לקובץ כזה
    assert not bot.ctx.user_data.get("img_settings") and "waiting_for_image_note" not in bot.ctx.user_data


@pytest.mark.asyncio
async def test_a_file_name_that_starts_like_a_token_is_sent_as_a_token(monkeypatch):
    # שם כזה אפשרי מהוובאפ ומה-MCP, שלא אוסרים ``:`` — בלי טוקן הוא היה נקרא ככפתור שפג תוקף
    name = "tok:a.py"
    bot = _Bot(monkeypatch)
    bot.save("print('x')", file_name=name)
    regenerate = await bot.button(name, "🔄 צור מחדש")
    assert regenerate != f"regenerate_image_{name}"

    calls = await bot.press(regenerate)

    _no_boundary_error(calls)
    assert bot.requested == [name] and [r["filename"] for r in bot.renders] == [name]


@pytest.mark.asyncio
async def test_a_drive_button_sent_before_the_version_was_pinned_still_saves_the_latest(monkeypatch):
    # כפתורים בהודעות שנשלחו לפני ``img_drive:`` — ``save_to_drive_<שם>``, בלי מזהה גרסה
    bot = _Bot(monkeypatch)
    bot.save("print('latest')")

    calls = await bot.press("save_to_drive_a.py")

    _no_boundary_error(calls)
    assert bot.requested == ["a.py"] and bot.pinned == []
    assert bot.renders[-1]["code"] == "print('latest')"
    assert [u["mimetype"] for u in bot.uploads] == ["image/png"]


@pytest.mark.asyncio
async def test_the_drive_message_links_to_the_file_and_escapes_the_link(monkeypatch):
    from services.google_drive_service import DriveUpload

    link = 'https://drive.google.com/file/d/fid/view?usp=drivesdk&x="y"'
    bot = _Bot(monkeypatch, upload=lambda: DriveUpload(file_id="fid-raw-id", web_view_link=link))
    bot.save("print('x')", file_name="<a>.py")  # השם בהודעה הוא של מסמך הגרסה
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


# --- הגרסה לפי ``_id`` בשכבת הקבצים ----------------------------------------------------------------


def test_the_files_facade_loads_a_version_by_id_only_for_its_owner_and_only_while_it_is_active(monkeypatch):
    from bson.objectid import ObjectId
    from pymongo.errors import PyMongoError

    from src.infrastructure.composition.files_facade import FilesFacade

    version_id = ObjectId()
    stored = {"_id": version_id, "user_id": 7, "file_name": "a.py", "code": "x", "is_active": True}
    queries = []

    class _DB:
        error = None

        def find_version_by_id(self, doc_id, user_id):
            # כמו ``Repository.find_version_by_id``: ``user_id`` הוא חלק מהשאילתה
            queries.append((doc_id, user_id))
            if self.error:
                raise self.error
            return dict(stored) if (doc_id, user_id) == (stored["_id"], stored["user_id"]) else None

    db = _DB()
    facade = FilesFacade()
    monkeypatch.setattr(facade, "_get_db", lambda: db)

    assert facade.get_version_by_id(7, str(version_id))["code"] == "x"
    # ה-``_id`` נשלח כ-ObjectId, כמו שהוא שמור — מחרוזת לא הייתה מוצאת כלום
    assert queries[-1] == (version_id, 7) and isinstance(queries[-1][0], ObjectId)
    assert facade.get_version_by_id(8, str(version_id)) is None

    # מזהה שאינו ObjectId — מ-callback_data מזויף — לא מגיע למסד בכלל
    before = len(queries)
    for forged in ("", "abc", "x" * 24, None, 123, str(version_id) + "0"):
        assert facade.get_version_by_id(7, forged) is None
    assert len(queries) == before

    stored["is_active"] = False  # בסל המיחזור
    assert facade.get_version_by_id(7, str(version_id)) is None

    db.error = PyMongoError("no primary")
    with pytest.raises(PyMongoError):
        facade.get_version_by_id(7, str(version_id))


def test_the_version_id_is_read_both_from_a_fresh_document_and_from_a_cached_one():
    # ``get_latest_version`` עטוף ב-``@cached``, והקאש שומר JSON עם ``default=str`` (``cache_manager.py``): בפגיעה בקאש ה-``_id``
    # מגיע כמחרוזת של 24 תווים, ובהחטאה — כ-``ObjectId``. בשני המקרים הכפתורים צריכים לשאת אותו.
    from bson.objectid import ObjectId

    import bot_handlers as mod

    oid = ObjectId()
    version_id = mod.AdvancedBotHandlers._image_version_id
    assert version_id({"_id": oid}) == str(oid)
    assert version_id({"_id": str(oid)}) == str(oid)
    for no_pin in ({}, {"_id": None}, {"_id": ""}, {"_id": {"$oid": str(oid)}}, {"_id": "not-an-object-id"}):
        assert version_id(no_pin) is None, no_pin

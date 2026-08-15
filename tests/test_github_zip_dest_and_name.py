"""הורדת תיקייה מגיטהאב כ־ZIP: ענף, יעד אחסון ושם הקובץ.

שלוש תקלות שנפגשו באותה נקודה — הזיפ שיצא מהבוט לא התאים לשימוש שבשבילו
הורידו אותו:

1. האריזה התעלמה מהענף שנבחר בדפדפן והחזירה תמיד את ברירת המחדל, בשקט.
2. הזיפ נשמר אוטומטית כגיבוי, ולגיבוי מוזרק ``metadata.json`` לשורש הארכיון —
   קובץ זר שהופך אותו ללא-תקין כסקיל להתקנה בקלוד.
3. השם נבנה בפורמט של גיבוי (``BKP zip skills v1 - ...``) במקום שם התיקייה.

הטסטים כתובים בדפוס של ``test_github_zip_spool_to_disk.py``: סטאבים ידניים
במקום MagicMock, ``monkeypatch.setattr(gh, "Github", ...)``, ו-``wait_for``
כדי שלולאה תקועה תיכשל במקום להיתלות.
"""

import asyncio
import types
import zipfile
from io import BytesIO

import pytest

USER = 5
REPO = "o/r"


@pytest.fixture(autouse=True)
def isolated_pending_dir(tmp_path, monkeypatch):
    """מבודד את תיקיית ה-ZIP הממתין לכל טסט בנפרד.

    בלי זה טסטים שאורזים בלי לסיים משאירים קבצים בתיקייה גלובלית משותפת עד
    שה-TTL פג — מה שנוגד את כללי הבטיחות של הריפו (עבודה בתיקיות ייעודיות
    לכל טסט) וגם הופך טסטים מקבילים לתלויים זה בזה.
    """
    import utils

    d = tmp_path / "pending_zip"
    d.mkdir()
    monkeypatch.setattr(utils, "_pending_zip_dir", lambda: d)
    yield
    for leftover in d.glob("*.bin"):
        leftover.unlink()


class _Item:
    def __init__(self, t, name, path, size=0, data=b""):
        self.type = t
        self.name = name
        self.path = path
        self.size = size
        self.decoded_content = data


class _Repo:
    """ריפו מזויף עם שני ענפים שתוכנם שונה, כדי שבחירת ref תהיה נצפית."""

    name = "r"
    full_name = REPO
    default_branch = "main"

    def __init__(self):
        self.refs_seen = []

    def get_contents(self, path, ref=None):
        self.refs_seen.append(ref)
        marker = b"dev" if ref == "dev" else b"main"
        if path == "skills/logo-designer":
            return [
                _Item("file", "SKILL.md", "skills/logo-designer/SKILL.md", 6, marker),
                _Item("dir", "references", "skills/logo-designer/references"),
            ]
        if path == "skills/logo-designer/references":
            return [
                _Item("file", "guide.md", "skills/logo-designer/references/guide.md", 2, b"gg")
            ]
        if path.endswith("SKILL.md"):
            return _Item("file", "SKILL.md", path, 6, marker)
        if path.endswith("guide.md"):
            return _Item("file", "guide.md", path, 2, b"gg")
        return []


class _Msg:
    def __init__(self):
        self.docs = []
        self.texts = []
        self.text = ""
        self.from_user = types.SimpleNamespace(id=USER)

    async def reply_document(self, document=None, filename=None, caption=None):
        raw = document.getvalue() if hasattr(document, "getvalue") else document
        self.docs.append({"filename": filename, "caption": caption, "bytes": raw})

    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(id=1), message_id=len(self.texts)
        )


class _Query:
    def __init__(self, data):
        self.data = data
        self.message = _Msg()
        self.from_user = types.SimpleNamespace(id=USER)
        self.edits = []

    async def answer(self, *a, **k):
        return None

    async def edit_message_text(self, text=None, **kwargs):
        self.edits.append(text)
        return self.message


def _make(monkeypatch, *, browse_ref=None, path="skills/logo-designer"):
    """מרכיב handler מחווט לריפו מזויף, ומחזיר (handler, upd, ctx, repo)."""
    import github_menu_handler as gh

    handler = gh.GitHubMenuHandler()
    handler.get_user_session = lambda uid: {"selected_repo": REPO}
    handler.get_user_token = lambda uid: "t"

    repo = _Repo()

    class _Gh:
        def __init__(self, *a, **k):
            pass

        def get_repo(self, _):
            return repo

    monkeypatch.setattr(gh, "Github", _Gh)
    monkeypatch.setattr(handler, "_get_path_from_cb", lambda c, d, p: path)

    query = _Query("download_zip:x")
    upd = types.SimpleNamespace(
        callback_query=query,
        effective_user=types.SimpleNamespace(id=USER),
        effective_message=query.message,
    )
    ctx = types.SimpleNamespace(user_data={}, bot_data={})
    if browse_ref:
        ctx.user_data["browse_ref"] = browse_ref
    return handler, upd, ctx, repo


async def _pack(handler, upd, ctx):
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=5.0)
    return next(iter(ctx.user_data["ghzip_pending"]))


async def _choose(handler, upd, ctx, data):
    upd.callback_query.data = data
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=5.0)


async def _send_text(handler, upd, ctx, text):
    """מדמה הודעת טקסט: handle_text_input קורא את הטקסט מ-update.message.text."""
    msg = upd.callback_query.message
    msg.text = text
    msg_upd = types.SimpleNamespace(
        message=msg,
        effective_message=msg,
        effective_user=types.SimpleNamespace(id=USER),
        callback_query=None,
    )
    return await asyncio.wait_for(handler.handle_text_input(msg_upd, ctx), timeout=5.0)


# ---------------------------------------------------------------- הענף


@pytest.mark.asyncio
async def test_packing_uses_the_selected_branch(monkeypatch):
    """הרגרסיה המרכזית: האריזה חייבת לכבד את הענף שהדפדפן מציג.

    בלי זה מי שבחר ענף דרך '🌿 ref:' קיבל את ברירת המחדל בלי שום סימן —
    התוכן פשוט היה של ענף אחר.
    """
    handler, upd, ctx, repo = _make(monkeypatch, browse_ref="dev")
    await _pack(handler, upd, ctx)

    assert repo.refs_seen, "לא בוצעה שום קריאה ל-get_contents"
    assert set(repo.refs_seen) == {"dev"}, f"נקראו ref-ים לא צפויים: {set(repo.refs_seen)}"


@pytest.mark.asyncio
async def test_default_branch_used_when_nothing_selected(monkeypatch):
    handler, upd, ctx, repo = _make(monkeypatch)
    await _pack(handler, upd, ctx)
    assert set(repo.refs_seen) == {"main"}


@pytest.mark.asyncio
async def test_selected_branch_recorded_in_metadata(monkeypatch):
    handler, upd, ctx, _ = _make(monkeypatch, browse_ref="dev")
    token = await _pack(handler, upd, ctx)
    entry = ctx.user_data["ghzip_pending"][token]
    assert entry["metadata"]["ref"] == "dev"


@pytest.mark.asyncio
async def test_stale_ref_does_not_fall_back_to_another_branch(monkeypatch):
    """ref שגוי לא נופל בשקט לענף אחר.

    ה-fallback ל-``TypeError`` נועד רק לחתימה שלא מקבלת ``ref``; 404 חייב
    להישאר 404. הבדיקה היא על **מה נקרא בפועל** ולא רק על התוצאה, כי
    ``walk_and_zip`` בולע חריגות ומדלג — ולכן ספירת קבצים לבדה תעבור בשני
    המקרים ולא תוכיח כלום.
    """
    import github_menu_handler as gh

    handler, upd, ctx, repo = _make(monkeypatch, browse_ref="no-such-branch")

    calls = []

    def _boom(path, ref=None):
        calls.append(ref)
        raise gh.GithubException(404, {"message": "No commit found for the ref"}, None)

    repo.get_contents = _boom
    # לא _pack: עם 0 קבצים הזרימה נעצרת לפני שאלת היעד ואין ghzip_pending
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=5.0)

    assert calls, "לא בוצעה שום קריאה"
    assert all(r == "no-such-branch" for r in calls), (
        f"נעשתה קריאה בלי ה-ref שנבחר — נפילה שקטה לענף אחר: {calls}"
    )


@pytest.mark.asyncio
async def test_empty_archive_is_reported_instead_of_offered(monkeypatch):
    """ref/נתיב שלא קיימים ⇒ הודעת שגיאה, לא הצעה לשמור ארכיון ריק."""
    import github_menu_handler as gh

    handler, upd, ctx, repo = _make(monkeypatch, browse_ref="no-such-branch")

    def _boom(path, ref=None):
        raise gh.GithubException(404, {"message": "No commit found for the ref"}, None)

    repo.get_contents = _boom
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=5.0)

    assert not ctx.user_data.get("ghzip_pending"), "הוצע לשמור ארכיון ריק"
    assert any("לא נמצאו קבצים" in (t or "") for t in upd.callback_query.edits)


@pytest.mark.asyncio
async def test_all_files_too_large_says_so(monkeypatch):
    """כשכל הקבצים דולגו בגלל גודל — לא לשלוח את המשתמש לבדוק את הנתיב.

    "הנתיב לא קיים" ו"הקבצים גדולים מדי" דורשים פעולות שונות לגמרי, והודעה
    אחת לשניהם שולחת לחפש במקום הלא נכון.
    """
    import github_menu_handler as gh

    handler, upd, ctx, repo = _make(monkeypatch)
    monkeypatch.setattr(gh, "MAX_INLINE_FILE_BYTES", 1)  # כל קובץ חורג
    await asyncio.wait_for(handler.handle_menu_callback(upd, ctx), timeout=5.0)

    assert not ctx.user_data.get("ghzip_pending")
    edits = " ".join(t or "" for t in upd.callback_query.edits)
    assert "מגבלות גודל" in edits, edits
    assert "בדוק שהנתיב" not in edits, "הודעה מטעה: הנתיב תקין"


@pytest.mark.asyncio
async def test_archive_cap_skips_are_counted(monkeypatch):
    """דילוג בגלל תקרת הארכיון נספר ומדווח, ולא נעלם בשקט.

    בלי המונה המשתמש מקבל ZIP חסר בלי שום סימן שמשהו נחתך.
    """
    import github_menu_handler as gh

    monkeypatch.setattr(gh, "MAX_ZIP_FILES", 1)  # רק הקובץ הראשון נכנס
    monkeypatch.setattr(gh.skill_manager, "save_skill_bytes", lambda *a, **k: "sid")

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)

    entry = ctx.user_data["ghzip_pending"][token]
    assert entry["total_files"] == 1
    assert entry["skipped_limits"] >= 1, "דילוג בגלל תקרה לא נספר"
    assert any("תקרה" in (t or "") for t in upd.callback_query.edits)

    await _choose(handler, upd, ctx, f"ghzip_dest_skill:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")
    assert "תקרה" in upd.callback_query.message.docs[-1]["caption"]


@pytest.mark.asyncio
async def test_github_calls_do_not_block_the_event_loop(monkeypatch):
    """קריאות PyGithub הסינכרוניות רצות ב-thread ולא על ה-event loop.

    הלולאה עוברת על כל קובץ בנפרד, אז קריאה חוסמת אחת מספיקה כדי לעכב את
    שאר עדכוני הבוט לאורך כל האריזה.
    """
    import threading

    handler, upd, ctx, repo = _make(monkeypatch)
    main_thread = threading.get_ident()
    seen = []

    original = repo.get_contents

    def _tracked(path, ref=None):
        seen.append(threading.get_ident())
        return original(path, ref=ref)

    repo.get_contents = _tracked
    await _pack(handler, upd, ctx)

    assert seen, "לא בוצעה שום קריאה"
    assert all(t != main_thread for t in seen), "קריאת רשת חוסמת רצה על ה-event loop"


# ---------------------------------------------------- metadata.json והיעד


@pytest.mark.asyncio
@pytest.mark.parametrize("dest", ["skill", "backup"])
async def test_zip_never_contains_metadata_json(monkeypatch, dest):
    """הזיפ שמגיע למשתמש נקי בשני היעדים.

    לגיבוי, ``save_backup_bytes`` מזריק את הקובץ בעצמו בשכבת האחסון — אין
    צורך להזריק אותו כאן, וההזרקה הכפולה היא שהרסה את מסלול הסקיל.
    """
    import github_menu_handler as gh

    monkeypatch.setattr(gh.backup_manager, "save_backup_bytes", lambda *a, **k: "bid")
    monkeypatch.setattr(gh.skill_manager, "save_skill_bytes", lambda *a, **k: "sid")

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    await _choose(handler, upd, ctx, f"ghzip_dest_{dest}:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")

    doc = upd.callback_query.message.docs[-1]
    names = zipfile.ZipFile(BytesIO(doc["bytes"])).namelist()
    assert "metadata.json" not in names, f"קובץ מטא-דאטה זר בזיפ: {names}"
    assert any(n.endswith("SKILL.md") for n in names)
    assert any(n.endswith("references/guide.md") for n in names), "תת-תיקייה לא נארזה"


@pytest.mark.asyncio
async def test_skill_is_saved_byte_for_byte(monkeypatch):
    """מה שנשלח למשתמש הוא בדיוק מה שנשמר כסקיל."""
    import github_menu_handler as gh

    captured = {}
    monkeypatch.setattr(
        gh.skill_manager,
        "save_skill_bytes",
        lambda data, md: captured.update(data=data, md=md) or "sid",
    )

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    await _choose(handler, upd, ctx, f"ghzip_dest_skill:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")

    assert captured["data"] == upd.callback_query.message.docs[-1]["bytes"]
    assert captured["md"]["original_name"] == "logo-designer.zip"


@pytest.mark.asyncio
async def test_backup_receives_metadata_dict(monkeypatch):
    """הגיבוי עדיין מקבל את המטא-דאטה — רק דרך הפרמטר, לא דרך הארכיון."""
    import github_menu_handler as gh

    captured = {}
    monkeypatch.setattr(
        gh.backup_manager,
        "save_backup_bytes",
        lambda data, md: captured.update(md=md) or "bid",
    )
    monkeypatch.setattr(gh.backup_manager, "list_backups", lambda uid: [])

    handler, upd, ctx, _ = _make(monkeypatch, browse_ref="dev")
    token = await _pack(handler, upd, ctx)
    await _choose(handler, upd, ctx, f"ghzip_dest_backup:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")

    assert captured["md"]["backup_id"]
    assert captured["md"]["repo"] == REPO
    assert captured["md"]["ref"] == "dev"


@pytest.mark.asyncio
async def test_backup_returning_none_counts_as_failure(monkeypatch):
    """``save_backup_bytes`` מסמן כשל ב-``None``, לא בחריגה.

    בלי לבדוק את ערך ההחזרה היינו מוחקים את הקובץ הזמני, מדווחים "נשמר"
    ומציגים מסך דירוג ל-backup_id שלא קיים — כשל שקט בלי דרך לנסות שוב.
    """
    import os

    import github_menu_handler as gh

    monkeypatch.setattr(gh.backup_manager, "save_backup_bytes", lambda *a, **k: None)

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    path = ctx.user_data["ghzip_pending"][token]["path"]
    await _choose(handler, upd, ctx, f"ghzip_dest_backup:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")

    caption = upd.callback_query.message.docs[-1]["caption"]
    assert "נכשלה" in caption, f"דווחה הצלחה כוזבת: {caption}"
    assert os.path.exists(path), "הקובץ הזמני נמחק למרות שהשמירה נכשלה"
    assert token in ctx.user_data["ghzip_pending"]
    # ובלי מסך דירוג — הוא מפנה ל-backup_id שלא נשמר
    assert not any("backup zip" in (t or "") for t in upd.callback_query.message.texts)


@pytest.mark.asyncio
async def test_backup_id_is_unique_within_the_same_second(monkeypatch):
    """שתי אריזות באותה שנייה חייבות לקבל backup_id שונה.

    ``save_backup_bytes`` שומר לקובץ בשם ``{backup_id}.zip`` ומוחק רשומה קיימת
    עם אותו שם — מזהה זהה היה מוחק את הגיבוי הראשון בשקט.
    """
    handler, upd, ctx, _ = _make(monkeypatch)
    first = await _pack(handler, upd, ctx)
    id_a = ctx.user_data["ghzip_pending"][first]["metadata"]["backup_id"]

    handler2, upd2, ctx2, _ = _make(monkeypatch)
    second = await _pack(handler2, upd2, ctx2)
    id_b = ctx2.user_data["ghzip_pending"][second]["metadata"]["backup_id"]

    assert id_a != id_b, f"מזהה גיבוי חוזר על עצמו: {id_a}"


@pytest.mark.asyncio
async def test_failed_send_does_not_double_save(monkeypatch):
    """כשל בשליחת המסמך אחרי שמירה מוצלחת לא יוצר רשומה שנייה בניסיון חוזר.

    ארכיון בגבול מגבלת טלגרם נשלח אחרי שהשמירה כבר הצליחה; בלי הגנה, לחיצה
    חוזרת על אותו token הייתה שומרת פעם נוספת.
    """
    import github_menu_handler as gh

    saves = []
    monkeypatch.setattr(
        gh.skill_manager, "save_skill_bytes", lambda *a, **k: saves.append(1) or "sid"
    )

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    await _choose(handler, upd, ctx, f"ghzip_dest_skill:{token}")

    # השליחה נכשלת — הזרימה מתפוצצת אחרי שהשמירה כבר בוצעה
    async def _boom(*a, **k):
        raise RuntimeError("file too large for telegram")

    upd.callback_query.message.reply_document = _boom
    with pytest.raises(RuntimeError):
        await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")

    assert len(saves) == 1
    assert ctx.user_data["ghzip_pending"][token].get("persisted") is True

    # ניסיון חוזר: הקובץ נשלח, אבל בלי שמירה נוספת
    upd.callback_query.message.reply_document = _Msg.reply_document.__get__(
        upd.callback_query.message
    )
    await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")
    assert len(saves) == 1, f"נשמר פעמיים לאותו ארכיון: {len(saves)}"


@pytest.mark.asyncio
async def test_file_cap_checked_before_fetching_content(monkeypatch):
    """אחרי שהגענו לתקרת הקבצים לא מושכים עוד תוכן מהרשת.

    כל קובץ עולה קריאת רשת והשהיית rate-limit; משיכה אחרי התקרה מבזבזת
    דקות ומכסת API על תוכן שנזרק מיד.
    """
    import github_menu_handler as gh

    monkeypatch.setattr(gh, "MAX_ZIP_FILES", 1)
    handler, upd, ctx, repo = _make(monkeypatch)

    fetched = []
    original = repo.get_contents

    def _tracked(path, ref=None):
        fetched.append(path)
        return original(path, ref=ref)

    repo.get_contents = _tracked
    token = await _pack(handler, upd, ctx)

    assert ctx.user_data["ghzip_pending"][token]["skipped_limits"] >= 1
    # הקובץ השני לא נמשך בכלל — רק הליסטינג של התיקיות ושליפת הקובץ הראשון
    assert fetched.count("skills/logo-designer/references/guide.md") == 0


@pytest.mark.asyncio
async def test_nothing_saved_before_the_user_answers(monkeypatch):
    """אחרי האריזה בלבד — שום יעד לא נגע בקובץ."""
    import github_menu_handler as gh

    calls = []
    monkeypatch.setattr(gh.backup_manager, "save_backup_bytes", lambda *a, **k: calls.append("backup"))
    monkeypatch.setattr(gh.skill_manager, "save_skill_bytes", lambda *a, **k: calls.append("skill"))

    handler, upd, ctx, _ = _make(monkeypatch)
    await _pack(handler, upd, ctx)

    assert calls == [], f"נשמר משהו לפני שהמשתמש נשאל: {calls}"
    assert not upd.callback_query.message.docs, "הקובץ נשלח לפני הבחירה"


# ------------------------------------------------------------------ השם


@pytest.mark.asyncio
async def test_default_name_is_the_folder_name(monkeypatch):
    """``skills/logo-designer`` ⇒ ``logo-designer.zip`` — בלי BKP/v/תאריך."""
    import github_menu_handler as gh

    monkeypatch.setattr(gh.skill_manager, "save_skill_bytes", lambda *a, **k: "sid")

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    await _choose(handler, upd, ctx, f"ghzip_dest_skill:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")

    name = upd.callback_query.message.docs[-1]["filename"]
    assert name == "logo-designer.zip", f"שם לא צפוי: {name}"
    assert "BKP" not in name and " v" not in name


@pytest.mark.asyncio
async def test_custom_name_is_applied(monkeypatch):
    """'✏️ שם אחר' ⇒ דגל נדלק, הטקסט נקלט, השם מתחלף."""
    import github_menu_handler as gh

    monkeypatch.setattr(gh.skill_manager, "save_skill_bytes", lambda *a, **k: "sid")

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    await _choose(handler, upd, ctx, f"ghzip_dest_skill:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_custom:{token}")

    assert ctx.user_data.get("waiting_for_zip_custom_name") == token

    handled = await _send_text(handler, upd, ctx, "my-logo-kit")
    assert handled is True
    assert upd.callback_query.message.docs[-1]["filename"] == "my-logo-kit.zip"
    assert "waiting_for_zip_custom_name" not in ctx.user_data


@pytest.mark.asyncio
async def test_bad_custom_name_keeps_the_flow_open(monkeypatch):
    """שם שלא שורד סניטציה לא זורק את המשתמש מהזרימה."""
    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    await _choose(handler, upd, ctx, f"ghzip_dest_skill:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_custom:{token}")

    await _send_text(handler, upd, ctx, "///")

    assert ctx.user_data.get("waiting_for_zip_custom_name") == token, "הדגל כובה בטעות"
    assert not upd.callback_query.message.docs, "נשלח קובץ עם שם לא תקין"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("logo-designer", "logo-designer"),
        ("../../etc/passwd", "etc-passwd"),
        ("a/b", "a-b"),
        ("my:file*name?", "my-file-name"),
        ("archive.zip", "archive"),  # סיומת כפולה לא נוצרת
        ("סקיל שלי", "סקיל שלי"),  # עברית שורדת
        ("  spaced  out  ", "spaced out"),
        ("///", ""),
        ("", ""),
        ("x" * 200, "x" * 100),
    ],
)
def test_safe_zip_filename(raw, expected):
    import github_menu_handler as gh

    assert gh._safe_zip_filename(raw) == expected


# --------------------------------------------------------------- ה-UI


@pytest.mark.parametrize(
    "path, must_contain",
    [
        ("skills/logo-designer", "logo-designer"),
        ("docs", "docs"),
        ("", "כל הריפו"),
    ],
)
def test_button_label_names_the_folder(path, must_contain):
    """התווית אומרת מה ייארז — בלי זה קל ללחוץ מתיקיית-אב ולקבל אותה."""
    import github_menu_handler as gh

    label = gh.GitHubMenuHandler._zip_button_label(path)
    assert must_contain in label
    assert "הורד תיקייה" in label  # המחרוזת שטסטים קיימים נשענים עליה


def test_long_folder_name_is_trimmed():
    import github_menu_handler as gh

    label = gh.GitHubMenuHandler._zip_button_label("a/" + "n" * 60)
    assert "…" in label
    assert len(label) < 60


@pytest.mark.asyncio
async def test_callback_data_within_telegram_limit(monkeypatch):
    """כל ה-callbacks של הזרימה מתחת ל-64 בייט."""
    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    for prefix in (
        "ghzip_dest_skill",
        "ghzip_dest_backup",
        "ghzip_name_default",
        "ghzip_name_custom",
        "ghzip_cancel",
    ):
        data = f"{prefix}:{token}"
        assert len(data.encode("utf-8")) <= 64, f"{data} ארוך מדי"


# --------------------------------------------------------- מחזור חיים


@pytest.mark.asyncio
async def test_cancel_removes_the_temp_file(monkeypatch):
    import os

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    path = ctx.user_data["ghzip_pending"][token]["path"]
    assert os.path.exists(path)

    await _choose(handler, upd, ctx, f"ghzip_cancel:{token}")

    assert not os.path.exists(path), "הקובץ הזמני נשאר אחרי ביטול"
    assert token not in ctx.user_data["ghzip_pending"]


@pytest.mark.asyncio
async def test_temp_file_removed_after_successful_save(monkeypatch):
    import os

    import github_menu_handler as gh

    monkeypatch.setattr(gh.skill_manager, "save_skill_bytes", lambda *a, **k: "sid")

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    path = ctx.user_data["ghzip_pending"][token]["path"]
    await _choose(handler, upd, ctx, f"ghzip_dest_skill:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")

    assert not os.path.exists(path)


@pytest.mark.asyncio
async def test_temp_file_survives_a_failed_save(monkeypatch):
    """בכשל שמירה ה-token נשאר, כדי שאפשר יהיה לנסות שוב.

    הדפוס מ-``conversation_handlers._handle_zip_route``.
    """
    import os

    import github_menu_handler as gh

    def _fail(*a, **k):
        raise RuntimeError("gridfs down")

    monkeypatch.setattr(gh.skill_manager, "save_skill_bytes", _fail)

    handler, upd, ctx, _ = _make(monkeypatch)
    token = await _pack(handler, upd, ctx)
    path = ctx.user_data["ghzip_pending"][token]["path"]
    await _choose(handler, upd, ctx, f"ghzip_dest_skill:{token}")
    await _choose(handler, upd, ctx, f"ghzip_name_default:{token}")

    assert os.path.exists(path), "הקובץ הזמני נמחק למרות שהשמירה נכשלה"
    assert token in ctx.user_data["ghzip_pending"]
    # המשתמש עדיין מקבל את הקובץ, עם אזהרה שהשמירה נכשלה
    assert "נכשלה" in upd.callback_query.message.docs[-1]["caption"]


@pytest.mark.asyncio
async def test_expired_token_is_reported(monkeypatch):
    handler, upd, ctx, _ = _make(monkeypatch)
    await _pack(handler, upd, ctx)
    ctx.user_data["ghzip_pending"] = {}

    await _choose(handler, upd, ctx, "ghzip_dest_skill:deadbeef")

    assert any("פג" in (t or "") for t in upd.callback_query.edits)

"""סל המיחזור מציג שורה אחת לכל **קובץ**, והפעולות עליה חלות על כולו.

**למה זה קיים.** קובץ שהמשתמש רואה הוא ``(user_id, file_name)``; במסד כל
גרסה היא מסמך נפרד. מסך הסל שלף מסמכים וציר שורה לכל אחד, ולכן קובץ בן
שש גרסאות תפס שש שורות עם אותו שם, אותו תאריך מחיקה ואותו תאריך תפוגה.
בבוט לא היה אפילו ``v1``..``v6`` להבחין ביניהן: שש שורות כפתורים זהות.
ולקבצים גדולים, שאין להם ``version`` כלל, השורות היו בלתי ניתנות
להבחנה — וזה לא מקרה קצה, כי ``Repository.save_large_file`` מוריד את
הגרסה הקודמת לסל בכל שמירה מחדש.

הבדיקות רצות על מונגו אמיתי, דרך ה-HTTP client ודרך ``show_recycle_bin``
של הבוט — המסלולים שהמשתמש עובר בהם — וקוראות בחזרה **מהמסד** אחרי כל
שחזור ומחיקה סופית, ולא מערך ההחזרה שלהם.
"""

import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

pytest.importorskip("flask")
pytest.importorskip("pymongo")

USER_ID = 7171
OTHER_USER = 8282
FILE = "amir.md"
DELETED_AT = datetime(2026, 2, 3, 8, 30, tzinfo=timezone.utc)
EXPIRES_AT = DELETED_AT + timedelta(days=30)


# ── הזרעה ────────────────────────────────────────────────────────────────


def _trash_doc(file_name, version, *, user_id, deleted_at, expires_at):
    return {
        "_id": ObjectId(),
        "user_id": user_id,
        "file_name": file_name,
        "code": f"# גרסה {version}",
        "programming_language": "markdown",
        "version": version,
        "is_active": False,
        "created_at": DELETED_AT - timedelta(days=1),
        "deleted_at": deleted_at,
        "deleted_expires_at": expires_at,
    }


def _seed_trashed(wa, file_name=FILE, versions=3, *, user_id=USER_ID,
                  deleted_at=DELETED_AT, expires_at=EXPIRES_AT):
    """קובץ אחד בסל, כמה מסמכי גרסה. מחזיר את המזהים לפי סדר הגרסה."""
    db = wa.get_db()
    ids = []
    for v in range(1, versions + 1):
        doc = _trash_doc(file_name, v, user_id=user_id,
                         deleted_at=deleted_at, expires_at=expires_at)
        ids.append(doc["_id"])
        db.code_snippets.insert_one(doc)
    return ids


def _seed_trashed_large(wa, file_name="big.md", copies=2, *, user_id=USER_ID):
    """קובץ גדול בסל. אין לו ``version``, וכל העברה לסל לוקחת ``now`` משלה."""
    db = wa.get_db()
    ids = []
    for i in range(copies):
        oid = ObjectId()
        ids.append(oid)
        db.large_files.insert_one({
            "_id": oid,
            "user_id": user_id,
            "file_name": file_name,
            "content": f"תוכן {i}",
            "is_active": False,
            "created_at": DELETED_AT - timedelta(days=2),
            "deleted_at": DELETED_AT + timedelta(minutes=i),
            "deleted_expires_at": EXPIRES_AT + timedelta(minutes=i),
        })
    return ids


def _reset(wa):
    db = wa.get_db()
    db.code_snippets.delete_many({})
    db.large_files.delete_many({})


def _client(wa, user_id=USER_ID):
    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_data"] = {"id": user_id, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    return client


def _trash_html(wa, user_id=USER_ID, page=None):
    resp = _client(wa, user_id).get("/trash" if page is None else f"/trash?page={page}")
    assert resp.status_code == 200, resp.status_code
    return resp.data.decode("utf-8")


def _rows(html):
    """מספר השורות בטבלה — נספר לפי כפתור הפעולה שיש אחד לכל שורה."""
    return html.count("restoreTrashed('")


def _in_trash(wa, file_name=FILE, user_id=USER_ID):
    return wa.get_db().code_snippets.count_documents(
        {"user_id": user_id, "file_name": file_name, "is_active": False})


def _active(wa, file_name=FILE, user_id=USER_ID):
    return wa.get_db().code_snippets.count_documents(
        {"user_id": user_id, "file_name": file_name, "is_active": True})


# ── התצוגה ───────────────────────────────────────────────────────────────


def test_a_file_with_three_trashed_versions_is_one_row(wired_mongo):
    """המסלול שדווח: קובץ אחד שנמחק — שורה אחת, ועליה מספר הגרסאות."""
    _reset(wired_mongo)
    _seed_trashed(wired_mongo, versions=3)

    html = _trash_html(wired_mongo)

    assert _rows(html) == 1, f"הסל הציג {_rows(html)} שורות לקובץ אחד"
    assert FILE in html
    assert "3 גרסאות" in html, "השורה אינה מצהירה כמה גרסאות שלה בסל"


def test_the_header_counts_files_and_not_version_documents(wired_mongo):
    """הכותרת מצהירה על מה שהשורות מציגות — קבצים."""
    _reset(wired_mongo)
    _seed_trashed(wired_mongo, versions=6)

    html = _trash_html(wired_mongo)

    assert "<strong>1</strong> קבצים בסל" in html, (
        "הכותרת סופרת מסמכי גרסה ולא קבצים")


def test_two_trashed_copies_of_a_large_file_are_one_row(wired_mongo):
    """המקרה שאין לו שום מבדיל חזותי: ל-``large_files`` אין ``version``."""
    _reset(wired_mongo)
    _seed_trashed_large(wired_mongo, copies=2)

    html = _trash_html(wired_mongo)

    assert _rows(html) == 1, f"שתי שורות זהות לקובץ גדול אחד: {_rows(html)}"
    assert "big.md" in html


def test_the_same_name_in_both_collections_stays_two_files(wired_mongo):
    """שם זהה בשתי הקולקציות הוא שתי ישויות — ולכן שתי שורות."""
    _reset(wired_mongo)
    _seed_trashed(wired_mongo, file_name="same.md", versions=2)
    _seed_trashed_large(wired_mongo, file_name="same.md", copies=1)

    html = _trash_html(wired_mongo)

    assert _rows(html) == 2, (
        f"קיבוץ לפי שם לבד מיזג שתי ישויות נפרדות: {_rows(html)} שורות")


def test_the_row_declares_the_earliest_expiry_of_its_versions(wired_mongo):
    """אינדקס ה-TTL מוחק מסמך-מסמך, ולכן המוקדם הוא מה שמחייב.

    v1 פוקע בתחילת מרץ ו-v2 בסופו. מתחילת מרץ הקובץ כבר אינו שלם, ולכן
    זה התאריך שהשורה מצהירה. ``$max`` היה מבטיח שחזור מלא עד סוף מרץ.
    """
    _reset(wired_mongo)
    early = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)
    late = datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)
    db = wired_mongo.get_db()
    db.code_snippets.insert_one(_trash_doc(
        FILE, 1, user_id=USER_ID, deleted_at=DELETED_AT, expires_at=early))
    db.code_snippets.insert_one(_trash_doc(
        FILE, 2, user_id=USER_ID, deleted_at=DELETED_AT + timedelta(days=5),
        expires_at=late))

    html = _trash_html(wired_mongo)

    assert _rows(html) == 1
    assert wired_mongo.format_datetime_display(early) in html, "התפוגה המוקדמת אינה מוצגת"
    assert wired_mongo.format_datetime_display(late) not in html, (
        "השורה מצהירה על תפוגה שבה חלק מההיסטוריה כבר נמחק")


def test_the_earliest_deletion_date_is_the_one_shown(wired_mongo):
    """אותו היגיון על ``deleted_at`` — הרגע שהקובץ התחיל להתפרק."""
    _reset(wired_mongo)
    first = datetime(2026, 1, 2, 7, 0, tzinfo=timezone.utc)
    second = datetime(2026, 1, 20, 7, 0, tzinfo=timezone.utc)
    db = wired_mongo.get_db()
    db.code_snippets.insert_one(_trash_doc(
        FILE, 1, user_id=USER_ID, deleted_at=first, expires_at=EXPIRES_AT))
    db.code_snippets.insert_one(_trash_doc(
        FILE, 2, user_id=USER_ID, deleted_at=second, expires_at=EXPIRES_AT))

    html = _trash_html(wired_mongo)

    assert wired_mongo.format_datetime_display(first) in html
    assert wired_mongo.format_datetime_display(second) not in html


def test_revisions_of_a_file_that_still_exists_are_not_shown(wired_mongo):
    """‏``save_large_file`` מוריד את הגרסה הקודמת לסל בכל שמירה מחדש.

    לקובץ גדול **חי** יש לכן דרך קבע מסמכים בסל. הסל מציג קבצים שנמחקו,
    לא היסטוריית רוויזיות, ולכן שם שיש לו גרסה פעילה אינו שורה בסל.
    """
    _reset(wired_mongo)
    _seed_trashed_large(wired_mongo, file_name="alive.md", copies=2)
    wired_mongo.get_db().large_files.insert_one({
        "_id": ObjectId(),
        "user_id": USER_ID,
        "file_name": "alive.md",
        "content": "הגרסה החיה",
        "is_active": True,
        "created_at": DELETED_AT,
    })

    html = _trash_html(wired_mongo)

    assert "alive.md" not in html, "רוויזיה של קובץ קיים הוצגה כקובץ מחוק"
    assert _rows(html) == 0


def test_a_live_file_in_the_other_collection_does_not_hide_the_row(wired_mongo):
    """ההסתרה היא לפי הקולקציה של השורה, ולא לפי השם לבדו.

    ‏``big.md`` חי ב-``code_snippets`` ו-``big.md`` מחוק ב-``large_files``
    הם שתי ישויות. בדיקת "יש גרסה פעילה" שמתעלמת מהקולקציה הייתה מסתירה
    קובץ גדול שנמחק רק בגלל שם זהה במקום אחר.
    """
    _reset(wired_mongo)
    _seed_trashed_large(wired_mongo, file_name="big.md", copies=2)
    wired_mongo.get_db().code_snippets.insert_one({
        "_id": ObjectId(),
        "user_id": USER_ID,
        "file_name": "big.md",
        "code": "# קובץ רגיל חי באותו שם",
        "programming_language": "markdown",
        "version": 1,
        "is_active": True,
        "created_at": DELETED_AT,
    })

    html = _trash_html(wired_mongo)

    assert _rows(html) == 1, "השורה נעלמה בגלל שם זהה בקולקציה האחרת"
    assert "big.md" in html


def test_half_deleted_files_from_the_old_bug_show_what_is_in_the_trash(wired_mongo):
    """קובץ שחלק מגרסאותיו בסל וחלק פעילות — מה שהבאג הישן השאיר.

    בקולקציית ``code_snippets`` הגרסאות הפעילות הן הקובץ עצמו, ולכן הוא
    אינו קובץ מחוק: הוא נמצא בעמוד הקבצים, לא בסל.
    """
    _reset(wired_mongo)
    _seed_trashed(wired_mongo, file_name="half.md", versions=2)
    wired_mongo.get_db().code_snippets.insert_one({
        "_id": ObjectId(),
        "user_id": USER_ID,
        "file_name": "half.md",
        "code": "# הגרסה שנשארה",
        "programming_language": "markdown",
        "version": 3,
        "is_active": True,
        "created_at": DELETED_AT,
    })

    html = _trash_html(wired_mongo)

    assert "half.md" not in html
    assert _rows(html) == 0


def test_another_users_trash_is_not_listed(wired_mongo):
    _reset(wired_mongo)
    _seed_trashed(wired_mongo, file_name="theirs.md", versions=2, user_id=OTHER_USER)

    html = _trash_html(wired_mongo)

    assert "theirs.md" not in html
    assert _rows(html) == 0


def test_pagination_counts_files_across_pages(wired_mongo):
    """העימוד מדלג על **קבצים**, לא על מסמכי גרסה.

    ‏25 קבצים בשלוש גרסאות כל אחד הם 75 מסמכים. עימוד לפי מסמכים היה
    מחזיר את העמוד הראשון שלוש פעמים ומסתיר 17 קבצים.
    """
    _reset(wired_mongo)
    for i in range(25):
        _seed_trashed(wired_mongo, file_name=f"f{i:02d}.md", versions=3,
                      deleted_at=DELETED_AT + timedelta(minutes=i))

    first = _trash_html(wired_mongo, page=1)
    second = _trash_html(wired_mongo, page=2)

    assert "<strong>25</strong> קבצים בסל" in first
    assert _rows(first) == 20, _rows(first)
    assert _rows(second) == 5, _rows(second)
    names_first = {f"f{i:02d}.md" for i in range(25) if f"f{i:02d}.md" in first}
    names_second = {f"f{i:02d}.md" for i in range(25) if f"f{i:02d}.md" in second}
    assert not (names_first & names_second), "אותו קובץ הופיע בשני עמודים"
    assert len(names_first | names_second) == 25, "קבצים נשמטו בין העמודים"


def test_a_failed_query_is_an_error_and_not_an_empty_trash(wired_mongo, monkeypatch):
    """תקלה בטעינה אינה "מחקתי הכול".

    זה הצד ההפוך של הבאג שהיה בבוט: שם ``TypeError`` במיון החזיר סל ריק.
    """
    _reset(wired_mongo)
    _seed_trashed(wired_mongo, versions=2)

    def _boom(db, pipeline):
        raise RuntimeError("aggregate_failed")

    monkeypatch.setattr(wired_mongo, "_aggregate_snippets", _boom)

    html = _trash_html(wired_mongo)

    assert "לא הצלחנו לטעון את הסל" in html
    assert "הסל ריק" not in html
    # וגם לא "יש כרגע 0 קבצים בסל" — מספר שלא נמדד אינו מוצג.
    assert "קבצים בסל" not in html


# ── הפעולות ──────────────────────────────────────────────────────────────


def test_restore_brings_back_every_version_of_the_file(wired_mongo):
    """המזהה של השורה הוא של גרסה אחת — והשחזור חל על הקובץ."""
    _reset(wired_mongo)
    _seed_trashed(wired_mongo, versions=3)
    row_id = _trash_row_id(wired_mongo)

    resp = _client(wired_mongo).post(f"/api/trash/{row_id}/restore", json={})

    assert resp.status_code == 200, resp.data
    assert _active(wired_mongo) == 3, "גרסאות נשארו בסל — היסטוריה קטועה"
    assert _in_trash(wired_mongo) == 0
    assert FILE not in _trash_html(wired_mongo)


def test_restore_through_a_middle_versions_id_restores_all(wired_mongo):
    """לא רק דרך המזהה שהשורה נושאת: כל מזהה של הקובץ מחזיר את כולו."""
    _reset(wired_mongo)
    ids = _seed_trashed(wired_mongo, versions=3)

    resp = _client(wired_mongo).post(f"/api/trash/{ids[1]}/restore", json={})

    assert resp.status_code == 200, resp.data
    assert _active(wired_mongo) == 3
    assert _in_trash(wired_mongo) == 0


def test_the_restore_response_counts_files_and_versions_apart(wired_mongo):
    _reset(wired_mongo)
    _seed_trashed(wired_mongo, versions=4)
    row_id = _trash_row_id(wired_mongo)

    body = _client(wired_mongo).post(f"/api/trash/{row_id}/restore", json={}).get_json()

    assert body["ok"] is True, body
    assert body["files"] == 1, body
    assert body["restored"] == 4, body
    assert body["file_name"] == FILE, body


def test_purge_removes_every_version_and_the_file_does_not_return(wired_mongo):
    _reset(wired_mongo)
    _seed_trashed(wired_mongo, versions=3)
    row_id = _trash_row_id(wired_mongo)

    resp = _client(wired_mongo).post(f"/api/trash/{row_id}/purge", json={})

    assert resp.status_code == 200, resp.data
    assert _in_trash(wired_mongo) == 0, "גרסאות נשארו בסל אחרי מחיקה סופית"
    assert _active(wired_mongo) == 0, "מחיקה סופית החזירה גרסה לחיים"
    assert FILE not in _trash_html(wired_mongo)


def test_purge_does_not_touch_the_active_versions_of_the_same_name(wired_mongo):
    """‏``is_active: False`` במסנן הוא השומר, ולא רק פרט מימוש."""
    _reset(wired_mongo)
    ids = _seed_trashed(wired_mongo, file_name="half.md", versions=2)
    wired_mongo.get_db().code_snippets.insert_one({
        "_id": ObjectId(),
        "user_id": USER_ID,
        "file_name": "half.md",
        "code": "# הגרסה החיה",
        "programming_language": "markdown",
        "version": 3,
        "is_active": True,
        "created_at": DELETED_AT,
    })

    resp = _client(wired_mongo).post(f"/api/trash/{ids[0]}/purge", json={})

    assert resp.status_code == 200, resp.data
    assert _in_trash(wired_mongo, "half.md") == 0
    assert _active(wired_mongo, "half.md") == 1, "הגרסה הפעילה נמחקה לצמיתות"


def test_purge_works_on_a_large_file(wired_mongo):
    _reset(wired_mongo)
    ids = _seed_trashed_large(wired_mongo, file_name="big.md", copies=3)

    resp = _client(wired_mongo).post(f"/api/trash/{ids[0]}/purge", json={})

    assert resp.status_code == 200, resp.data
    assert wired_mongo.get_db().large_files.count_documents(
        {"user_id": USER_ID, "file_name": "big.md"}) == 0


def test_an_id_of_another_user_is_rejected(wired_mongo):
    _reset(wired_mongo)
    ids = _seed_trashed(wired_mongo, file_name="theirs.md", versions=2,
                        user_id=OTHER_USER)

    restore = _client(wired_mongo).post(f"/api/trash/{ids[0]}/restore", json={})
    purge = _client(wired_mongo).post(f"/api/trash/{ids[0]}/purge", json={})

    assert restore.status_code == 404, restore.data
    assert purge.status_code == 404, purge.data
    assert _in_trash(wired_mongo, "theirs.md", user_id=OTHER_USER) == 2


def _trash_row_id(wa, user_id=USER_ID):
    """המזהה שהשורה באמת נושאת — נקרא מה-HTML, לא מורכב בבדיקה."""
    html = _trash_html(wa, user_id)
    marker = "restoreTrashed('"
    start = html.index(marker) + len(marker)
    return html[start:html.index("'", start)]


# ── הבוט ─────────────────────────────────────────────────────────────────


def _repo_for(wa):
    """‏``Repository`` על מסד הבדיקה. ``wired_mongo`` מפנה רק את הוובאפ."""
    from database.repository import Repository

    db = wa.get_db()

    class _Manager:
        def __init__(self):
            self.collection = db.code_snippets
            self.large_files_collection = db.large_files
            self.db = db

    return Repository(_Manager())


@pytest.fixture
def bot_on_test_db(wired_mongo, monkeypatch):
    """מפנה את ``conversation_handlers`` ל-``Repository`` של מסד הבדיקה."""
    repo = _repo_for(wired_mongo)
    module = types.ModuleType("database")

    class _DB:
        def _get_repo(self):
            return repo

    module.db = _DB()
    monkeypatch.setitem(sys.modules, "database", module)
    return wired_mongo


def _bot_screen(monkeypatch, data="recycle_page_1", user_id=USER_ID):
    """מריץ את ``show_recycle_bin`` ומחזיר (הכותרת, המקלדת)."""
    import asyncio

    import conversation_handlers as ch

    captured = {}

    async def _fake_edit(query, text, reply_markup=None, parse_mode=None):
        captured["text"] = text
        captured["markup"] = reply_markup

    monkeypatch.setattr(ch.TelegramUtils, "safe_edit_message_text", _fake_edit)

    class _Q:
        def __init__(self):
            self.data = data
            self.message = types.SimpleNamespace()

        async def answer(self, *a, **k):
            return None

    class _U:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = types.SimpleNamespace(id=user_id)

    asyncio.run(ch.show_recycle_bin(_U(), types.SimpleNamespace(user_data={})))
    return captured.get("text", ""), captured.get("markup")


def _restore_buttons(markup):
    return [b for row in (markup.inline_keyboard if markup else [])
            for b in row if (b.text or "").startswith("♻️")]


def test_the_bot_shows_one_button_pair_per_file(bot_on_test_db, monkeypatch):
    """בבוט לא היה אפילו badge להבחין בין השורות — שש גרסאות, שש שורות זהות."""
    _reset(bot_on_test_db)
    _seed_trashed(bot_on_test_db, versions=3)

    text, markup = _bot_screen(monkeypatch)

    buttons = _restore_buttons(markup)
    assert len(buttons) == 1, f"הבוט הציג {len(buttons)} שורות לקובץ אחד"
    assert FILE in buttons[0].text
    assert "3 גרסאות" in buttons[0].text, "הכפתור אינו אומר כמה גרסאות בסל"
    assert "1 קבצים" in text, text


def test_the_bot_header_counts_files(bot_on_test_db, monkeypatch):
    _reset(bot_on_test_db)
    _seed_trashed(bot_on_test_db, versions=6)

    text, _markup = _bot_screen(monkeypatch)

    assert "6 קבצים" not in text, "הכותרת סופרת מסמכי גרסה"
    assert "1 קבצים" in text, text


def test_a_document_without_deleted_at_does_not_empty_the_bots_trash(bot_on_test_db,
                                                                     monkeypatch):
    """הסחיפה שהעותק השני הביא: ``None`` במפתח המיון החזיר סל **ריק**.

    הקוד הישן מיין בפייתון, ``_key`` החזיר ``None`` למסמך בלי
    ``deleted_at``, ההשוואה ל-``datetime`` זרקה ``TypeError``, וה-``except``
    החיצוני החזיר ``([], 0)``. הוובאפ החזיר ``datetime.min`` ושרד — אותה
    שאילתה, שתי התנהגויות.
    """
    _reset(bot_on_test_db)
    _seed_trashed(bot_on_test_db, file_name="dated.md", versions=1)
    orphan = _trash_doc("undated.md", 1, user_id=USER_ID,
                        deleted_at=None, expires_at=EXPIRES_AT)
    orphan.pop("deleted_at")
    bot_on_test_db.get_db().code_snippets.insert_one(orphan)

    text, markup = _bot_screen(monkeypatch)

    assert len(_restore_buttons(markup)) == 2, "הסל חזר חסר או ריק"
    assert "2 קבצים" in text, text


def test_the_bot_restore_brings_back_every_version(bot_on_test_db, monkeypatch):
    """מסלול הבקרה של הבוט, דרך ה-callback האמיתי."""
    import asyncio

    import conversation_handlers as ch

    _reset(bot_on_test_db)
    ids = _seed_trashed(bot_on_test_db, versions=3)

    async def _fake_edit(query, text, reply_markup=None, parse_mode=None):
        return None

    monkeypatch.setattr(ch.TelegramUtils, "safe_edit_message_text", _fake_edit)

    class _Q:
        def __init__(self):
            self.data = f"recycle_restore:{ids[1]}"
            self.message = types.SimpleNamespace()

        async def answer(self, *a, **k):
            return None

    class _U:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = types.SimpleNamespace(id=USER_ID)

    asyncio.run(ch.recycle_restore(_U(), types.SimpleNamespace(user_data={})))

    assert _active(bot_on_test_db) == 3, "השחזור בבוט החזיר גרסה אחת"
    assert _in_trash(bot_on_test_db) == 0

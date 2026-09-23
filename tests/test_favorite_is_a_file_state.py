"""מועדף הוא מצב של **קובץ**, לא של מסמך גרסה.

קובץ הוא ``(user_id, file_name)``; כל גרסה היא מסמך נפרד ב-``code_snippets``. עמוד המועדפים מציג קובץ אם **איזושהי** גרסה פעילה שלו מסומנת — הכלל שכבר כתוב ב-``Repository.is_favorite`` — ולכן כל כתיבה של הסימון חייבת לחול על הקובץ כולו. שני כשלים עלו בפרודקשן ב-23.9.2026, ושניהם נבדקים כאן מול מונגו אמיתי:

1. **פעולה מרובה לפי מזהה גרסה.** "הסר ממועדפים" בבחירה מרובה סימן רק את המסמך שהמזהה שלו נשלח. העמוד מוסר את המזהה של הגרסה **האחרונה** בלבד, ולכן קובץ עם כמה גרסאות היה נשאר במועדפים — אותו באג שתוקן במחיקה המרובה (``file_deletion.py``).
2. **גרסה חדשה שמאבדת את הסימון.** חמישה מתוך שבעת המסלולים שכותבים גרסה בנו את המסמך החדש ביד ולא העבירו את ``is_favorite``/``favorited_at``: עריכה, העלאה, שמירת מדריך משותף ו-Incident Story ב-``webapp/app.py``, ושמירה מאוסף משותף ב-``webapp/collections_api.py``. בפרודקשן נמצאו שני קבצים מועדפים שהגרסה האחרונה שלהם לא מסומנת.

הכלל של הירושה יושב בפונקציה אחת (``file_favorite.favorite_fields_for_new_version``), וכל כותב קורא לה. היא שואלת את **כל** הגרסאות הפעילות, ולא רק את האחרונה — אותה שאלה שהרשימה שואלת. לכן כל בדיקת כותב כאן רצה פעמיים: פעם כשהגרסה היחידה מסומנת, ופעם כשרק גרסה ישנה מסומנת והאחרונה לא. השני הוא המצב מהפרודקשן, ובכלל הקודם, שירש מהגרסה האחרונה בלבד, הגרסה החדשה יצאה בו לא מסומנת.

ועוד אחד, מהסקירה של ה-PR: עמוד המועדפים נשמר כ-HTML בקאש, ושינוי סימון לא ביטל אותו — קובץ שהוסר חזר ברענון עד שהקאש פג. הבדיקות שלו רצות עם ``CacheManager`` אמיתי מעל Redis מדומה, כי זה המצב שהייצור רץ בו.

השומר המבני שמוודא שכל כותב קורא לפונקציה נמצא לצד שומר חותמת התיאור ב-``tests/test_mcp_description_age.py``, על **אותה** רשימת כותבים — ולא כאן, כדי שלא תהיה רשימה שנייה שמתיישנת בנפרד (``bugbot-rules/derived-field-added-to-one-writer.md``). כאן יש לכל כותב בדיקה התנהגותית שקוראת את השדה בחזרה מהמסד, כי שומר מבני מוודא שהקוד **מזכיר** את הכלל ולא שהוא משתמש בתוצאה.

⚠️ מונגו אמיתי דרך ``wired_mongo``; בלי ``NOTE_FONTS_TEST_MONGO_URI`` נגיש הבדיקות האלה מדלגות. האם הן רצות ב-CI — ראו את ההערה ליד ``NOTE_FONTS_TEST_MONGO_URI`` ב-``.github/workflows/ci.yml``. הבדיקות של הכלל עצמו, בסוף הקובץ, רצות בכל סביבה. הרצה מקומית — כמו בראש ``tests/test_files_list_one_row_per_file.py``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase

import pytest

pytest.importorskip("flask")
pytest.importorskip("pymongo")

from bson import ObjectId  # noqa: E402

USER_ID = 8282
OTHER_USER = 9393
CREATED = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
FAVORITED = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)

#: איך הקובץ מסומן לפני הכתיבה: ``(מספר גרסאות, הגרסאות המסומנות)``. הגרסה החדשה תהיה ``מספר הגרסאות + 1``.
MARKED = [
    pytest.param(1, (1,), id="the-only-version-is-marked"),
    pytest.param(2, (1,), id="only-an-older-version-is-marked"),
]


class _CacheRecorder:
    """הקאש כבוי — כל בקשה מגיעה למסד — ומה שהראוטים מבקשים לבטל נרשם."""

    is_enabled = False

    def __init__(self):
        self.invalidated_users = []

    def invalidate_user_cache(self, user_id):
        self.invalidated_users.append(user_id)
        return 0


class _CacheThatFails(_CacheRecorder):
    """ניקוי שזורק — למשל באג בשכבת הקאש. הכתיבה עצמה כבר הצליחה."""

    def invalidate_user_cache(self, user_id):
        raise RuntimeError("cache layer is down")


@pytest.fixture(autouse=True)
def _empty_local_cache_store():
    """``@cached`` נופל ל-``_local_cache_store`` כש-Redis כבוי, והמילון הזה חי ברמת המודול — כלומר עובר בין טסטים. כמו ב-``tests/test_search_code_failure_is_not_cached.py``."""
    import cache_manager

    cache_manager._local_cache_store.clear()
    yield
    cache_manager._local_cache_store.clear()


@pytest.fixture
def wa(wired_mongo, monkeypatch):
    monkeypatch.setattr(wired_mongo, "cache", _CacheRecorder(), raising=True)
    wired_mongo.get_db().code_snippets.delete_many({})
    return wired_mongo


class _Manager:
    """``Repository`` צריך רק ``manager.collection``."""

    def __init__(self, collection):
        self.collection = collection


def _seed(wa, file_name, versions=3, *, favorite=(), user_id=USER_ID):
    """קובץ בכמה גרסאות פעילות; ``favorite`` הוא מספרי הגרסאות המסומנות. מחזיר את המזהים לפי הגרסה."""
    ids = []
    for version in range(1, versions + 1):
        code = f"# {file_name} גרסה {version}\n"
        doc = {
            "_id": ObjectId(),
            "user_id": user_id,
            "file_name": file_name,
            "code": code,
            "programming_language": "markdown",
            "description": "",
            "tags": [],
            "version": version,
            "is_active": True,
            "created_at": CREATED,
            "updated_at": CREATED + timedelta(hours=version),
            "file_size": len(code.encode("utf-8")),
            "lines_count": len(code.split("\n")),
        }
        if version in favorite:
            doc["is_favorite"] = True
            doc["favorited_at"] = FAVORITED
        wa.get_db().code_snippets.insert_one(doc)
        ids.append(doc["_id"])
    return ids


def _client(wa, user_id=USER_ID):
    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_data"] = {"id": user_id, "first_name": "בדיקה", "is_admin": False, "is_premium": False}
    return client


def _versions(wa, file_name, user_id=USER_ID):
    """כל הגרסאות הפעילות, מהמסד ולא מהתשובה של הראוט."""
    return list(wa.get_db().code_snippets.find(
        {"user_id": user_id, "file_name": file_name, "is_active": True},
        {"version": 1, "is_favorite": 1, "favorited_at": 1},
    ).sort("version", 1))


def _latest(wa, file_name, user_id=USER_ID):
    return _versions(wa, file_name, user_id)[-1]


# -------------------------------------------- פעולה מרובה חלה על הקובץ כולו


def test_bulk_unfavorite_takes_the_whole_file_out_of_favorites(wa):
    """המסלול מהעמוד: בחירה מרובה ← "הסר ממועדפים", עם המזהה של הגרסה האחרונה."""
    ids = _seed(wa, "plan.md", favorite=(1, 2, 3))

    response = _client(wa).post("/api/files/bulk-unfavorite", json={"file_ids": [str(ids[-1])]})

    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"success": True, "updated": 1}
    marked = [v["version"] for v in _versions(wa, "plan.md") if v.get("is_favorite") is True]
    assert marked == [], f"גרסאות שנשארו מסומנות — הקובץ נשאר במועדפים: {marked}"

    page = _client(wa).get("/files?category=favorites").get_data(as_text=True)
    assert "plan.md" not in page


def test_bulk_favorite_marks_every_active_version_of_the_file(wa):
    ids = _seed(wa, "notes.md")

    response = _client(wa).post("/api/files/bulk-favorite", json={"file_ids": [str(ids[-1])]})

    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"success": True, "updated": 1}
    versions = _versions(wa, "notes.md")
    assert all(v.get("is_favorite") is True for v in versions), versions
    assert len({v.get("favorited_at") for v in versions}) == 1, "כל הגרסאות חייבות לשאת את אותו זמן סימון"


def test_bulk_counts_files_and_not_versions(wa):
    """``bulk-actions.js`` מדפיס את ``updated`` כ"N קבצים", ולכן שני מזהים של אותו קובץ הם קובץ אחד.

    שני מזהים של אותו קובץ הם בדיוק מה שעמוד המועדפים הישן איפשר לבחור, כשהציג כל גרסה כשורה. מזהה אחד לכל קובץ לא היה מבדיל: שם מספר המסמכים ומספר הקבצים יוצאים שווים במקרה.
    """
    many = _seed(wa, "many.md", versions=3)
    one = _seed(wa, "one.md", versions=1)

    response = _client(wa).post(
        "/api/files/bulk-favorite", json={"file_ids": [str(many[-1]), str(many[-2]), str(one[-1])]}
    )

    assert response.get_json() == {"success": True, "updated": 2}


def test_bulk_favorite_does_not_touch_another_users_file(wa):
    """הבעלות נאכפת בשאילתה עצמה, כמו במחיקה המרובה."""
    theirs = _seed(wa, "theirs.md", versions=2, user_id=OTHER_USER)

    response = _client(wa).post("/api/files/bulk-favorite", json={"file_ids": [str(theirs[-1])]})

    assert response.status_code == 404
    assert all(v.get("is_favorite") is not True for v in _versions(wa, "theirs.md", OTHER_USER))


@pytest.mark.parametrize("route", ["/api/files/bulk-favorite", "/api/files/bulk-unfavorite"])
@pytest.mark.parametrize("body", [["not", "an", "object"], {"file_ids": "6540f2a7"}, {"file_ids": [123]}])
def test_bulk_favorites_reject_a_malformed_body_with_400(wa, route, body):
    """גוף שאינו בצורה הצפויה הוא שגיאת קלט (400), לא קריסה (500).

    רשימה בתור הגוף הפילה את ``data.get`` ב-``AttributeError``; מחרוזת בתור ``file_ids`` התפרקה לתווים בודדים.
    """
    response = _client(wa).post(route, json=body)

    assert response.status_code == 400, (route, body, response.get_json())


# ------------------------------------------------ ביטול הקאש אחרי שינוי סימון


def test_a_bulk_change_invalidates_the_users_cache_only_after_a_write(wa):
    """הביטול רץ אחרי כתיבה שנגעה במשהו — ולא על בקשה שנדחתה לפני הכתיבה."""
    ids = _seed(wa, "cached.md", versions=2)
    theirs = _seed(wa, "theirs.md", versions=1, user_id=OTHER_USER)

    assert _client(wa).post("/api/files/bulk-favorite", json={"file_ids": [str(theirs[-1])]}).status_code == 404
    assert _client(wa).post("/api/files/bulk-favorite", json={"file_ids": "x"}).status_code == 400
    assert wa.cache.invalidated_users == [], "ביטול קאש על בקשה שלא כתבה כלום"

    assert _client(wa).post("/api/files/bulk-favorite", json={"file_ids": [str(ids[-1])]}).status_code == 200
    assert wa.cache.invalidated_users == [USER_ID]


@pytest.mark.parametrize("route", ["bulk", "toggle"])
def test_a_failed_cache_cleanup_does_not_turn_a_saved_change_into_an_error(wa, monkeypatch, caplog, route):
    """הסימון כבר נשמר — כשל בניקוי הקאש אחריו אינו הופך אותו לשגיאה, ואינו נבלע בשקט.

    תשובת שגיאה הייתה שולחת את המשתמש ללחוץ שוב, ובטוגל לחיצה נוספת מחזירה את הסימון שהוא הרגע הסיר. אותו כלל כמו בשכבת המסד, ב-``tests/test_repository_invalidation_and_list_branch.py``.
    """
    monkeypatch.setattr(wa, "cache", _CacheThatFails(), raising=True)
    ids = _seed(wa, "flaky-cache.md", versions=2, favorite=(1, 2))

    with caplog.at_level(logging.WARNING):
        if route == "bulk":
            response = _client(wa).post("/api/files/bulk-unfavorite", json={"file_ids": [str(ids[-1])]})
            expected = {"success": True, "updated": 1}
        else:
            response = _client(wa).post(f"/api/favorite/toggle/{ids[-1]}")
            expected = {"ok": True, "state": False}

    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert response.get_json() == expected
    assert all(v.get("is_favorite") is False for v in _versions(wa, "flaky-cache.md"))
    assert any("files.favorite_cache_invalidation_failed" in r.getMessage() for r in caplog.records), (
        f"כשל הניקוי לא נרשם: {[r.getMessage() for r in caplog.records]}"
    )


class _DummyRedis:
    """Redis בזיכרון, עם ``scan_iter`` — כמו ב-``tests/test_cache_invalidate_file_related_covers_lists.py``.

    ``scan_iter`` מתעלם מ-``match`` ומחזיר את כל המפתחות, כך שההתאמה נעשית על ידי ``CacheManager`` עצמו, כמו מול Redis אמיתי. בלי ``scan_iter`` הקוד היה עובר למסלול אחר.
    """

    def __init__(self):
        self.store = {}

    def ping(self):
        return True

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        return True

    def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    def delete(self, *keys):
        count = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                count += 1
        return count

    def scan_iter(self, match=None, count=None):
        return list(self.store.keys())


@pytest.fixture
def page_cache(wa, monkeypatch):
    """``CacheManager`` אמיתי מעל Redis מדומה, כדי שעמוד הקבצים באמת יישמר בקאש — כמו בפרודקשן."""
    from cache_manager import CacheManager

    monkeypatch.setenv("REDIS_URL", "redis://dummy")
    manager = CacheManager()
    monkeypatch.setattr(manager, "redis_client", _DummyRedis(), raising=True)
    monkeypatch.setattr(manager, "is_enabled", True, raising=True)
    monkeypatch.setattr(wa, "cache", manager, raising=True)
    return manager


@pytest.mark.parametrize("route", ["bulk", "toggle"])
def test_a_file_taken_out_of_favorites_does_not_come_back_from_the_page_cache(wa, page_cache, route):
    """הסרה ממועדפים ואז רענון: הקובץ לא חוזר מה-HTML ששמור בקאש.

    עמוד המועדפים נשמר בקאש כ-HTML, ועד התיקון לא הטוגל ולא הסימון המרובה ביטלו אותו — הקובץ חזר ברענון עד שהקאש פג. ``?no_cache=1`` לא עוזר כאן: ``/files`` אינו קורא אותו.
    """
    ids = _seed(wa, "cached.md", versions=2, favorite=(1, 2))
    card = f'data-file-id="{ids[-1]}"'
    client = _client(wa)

    assert card in client.get("/files?category=favorites").get_data(as_text=True)
    cached_pages = [key for key in page_cache.redis_client.store if fnmatchcase(key, f"web:files:user:{USER_ID}:*")]
    assert cached_pages, "העמוד לא נשמר בקאש — הבדיקה לא הייתה בודקת כלום"

    if route == "bulk":
        response = client.post("/api/files/bulk-unfavorite", json={"file_ids": [str(ids[-1])]})
    else:
        response = client.post(f"/api/favorite/toggle/{ids[-1]}")
    assert response.status_code == 200, response.get_data(as_text=True)

    assert card not in client.get("/files?category=favorites").get_data(as_text=True)


# --------------------------------------- גרסה חדשה יורשת את הסימון — בכל כותב


def _assert_new_version_is_still_a_favorite(wa, file_name, expected_version):
    latest = _latest(wa, file_name)
    assert latest["version"] == expected_version, f"לא נכתבה גרסה חדשה: {latest}"
    assert latest.get("is_favorite") is True, f"הגרסה החדשה איבדה את סימון המועדף: {latest}"
    assert latest.get("favorited_at") == FAVORITED, f"זמן הסימון לא עבר לגרסה החדשה: {latest}"


@pytest.mark.parametrize("versions, favorite", MARKED)
def test_editing_in_the_webapp_keeps_the_file_a_favorite(wa, versions, favorite):
    ids = _seed(wa, "edited.md", versions=versions, favorite=favorite)

    response = _client(wa).post(f"/edit/{ids[-1]}", data={
        "file_name": "edited.md", "code": "# גרסה חדשה\n", "description": "", "language": "markdown",
    })

    assert response.status_code in (200, 302), response.get_data(as_text=True)[:300]
    _assert_new_version_is_still_a_favorite(wa, "edited.md", versions + 1)


def test_editing_a_file_whose_latest_version_lost_the_mark_keeps_it_in_favorites(wa):
    """המצב שנמצא בפרודקשן בשני קבצים: הגרסאות הישנות מסומנות, האחרונה לא.

    הממשק פותח לעריכה את הגרסה האחרונה, והיא לא מסומנת. הגרסה החדשה חייבת לרשת את המצב של הקובץ ולא של הגרסה שנפתחה — אחרת הרשימה והמסמך עונים תשובות שונות, והכוכב בעמוד הקובץ נראה כבוי. הבדיקה עוברת על שני הצדדים: הגרסה במסד, והשורה בעמוד המועדפים.
    """
    ids = _seed(wa, "partial.md", versions=2, favorite=(1,))

    response = _client(wa).post(f"/edit/{ids[-1]}", data={
        "file_name": "partial.md", "code": "# גרסה 3\n", "description": "", "language": "markdown",
    })
    assert response.status_code in (200, 302), response.get_data(as_text=True)[:300]

    _assert_new_version_is_still_a_favorite(wa, "partial.md", 3)
    newest = _latest(wa, "partial.md")
    page = _client(wa).get("/files?category=favorites").get_data(as_text=True)
    assert page.count('class="glass-card file-card"') == 1
    assert f'data-file-id="{newest["_id"]}"' in page, "הקובץ לא מוצג בגרסה האחרונה שלו"


def test_renaming_a_favorite_file_in_the_editor_keeps_it_a_favorite(wa):
    """עריכה שמשנה את שם הקובץ כותבת את הגרסה החדשה תחת השם החדש, ושם עוד אין אף גרסה.

    לכן העריכה שואלת גם את השם שממנו יצאה. בלי זה, שינוי שם היה מוציא קובץ מהמועדפים.
    """
    ids = _seed(wa, "old-name.md", versions=1, favorite=(1,))

    response = _client(wa).post(f"/edit/{ids[-1]}", data={
        "file_name": "new-name.md", "code": "# אחרי שינוי השם\n", "description": "", "language": "markdown",
    })

    assert response.status_code in (200, 302), response.get_data(as_text=True)[:300]
    _assert_new_version_is_still_a_favorite(wa, "new-name.md", 1)


@pytest.mark.parametrize("versions, favorite", MARKED)
def test_uploading_over_an_existing_file_keeps_it_a_favorite(wa, versions, favorite):
    _seed(wa, "uploaded.md", versions=versions, favorite=favorite)

    response = _client(wa).post("/upload", data={
        "file_name": "uploaded.md", "code": "# גרסה חדשה\n", "language": "markdown",
    })

    assert response.status_code in (200, 302), response.get_data(as_text=True)[:300]
    _assert_new_version_is_still_a_favorite(wa, "uploaded.md", versions + 1)


@pytest.mark.parametrize("versions, favorite", MARKED)
def test_restoring_an_old_version_keeps_the_file_a_favorite(wa, versions, favorite):
    ids = _seed(wa, "restored.md", versions=versions, favorite=favorite)

    response = _client(wa).post(f"/api/file/{ids[-1]}/restore", json={"version": 1})

    assert response.status_code == 200, response.get_json()
    _assert_new_version_is_still_a_favorite(wa, "restored.md", versions + 1)


@pytest.mark.parametrize("versions, favorite", MARKED)
def test_saving_a_shared_guide_over_an_existing_file_keeps_it_a_favorite(wa, monkeypatch, versions, favorite):
    _seed(wa, "guide.md", versions=versions, favorite=favorite)
    monkeypatch.setattr(
        wa, "get_internal_share",
        lambda share_id: {"code": "# מדריך\n", "file_name": "guide.md", "language": "markdown"},
    )

    response = _client(wa).post("/api/shared/save", json={"share_id": "abc"})

    assert response.status_code == 200, response.get_json()
    _assert_new_version_is_still_a_favorite(wa, "guide.md", versions + 1)


@pytest.mark.parametrize("versions, favorite", MARKED)
def test_writing_an_incident_story_over_an_existing_file_keeps_it_a_favorite(wa, versions, favorite):
    _seed(wa, "incident.md", versions=versions, favorite=favorite)

    wa._persist_story_markdown_file(user_id=USER_ID, file_name="incident.md", markdown="# סיפור\n")

    _assert_new_version_is_still_a_favorite(wa, "incident.md", versions + 1)


@pytest.mark.parametrize("versions, favorite", MARKED)
def test_saving_from_a_shared_collection_keeps_the_file_a_favorite(wa, versions, favorite):
    from webapp.collections_api import _save_shared_document_to_user

    _seed(wa, "shared.md", versions=versions, favorite=favorite)

    result = _save_shared_document_to_user(
        wa.get_db(), user_id=USER_ID,
        doc={"file_name": "shared.md", "content": "# משותף\n", "language": "markdown"},
    )

    assert result["ok"] is True, result
    _assert_new_version_is_still_a_favorite(wa, "shared.md", versions + 1)


@pytest.mark.parametrize("versions, favorite", MARKED)
def test_saving_through_the_bot_and_mcp_path_keeps_the_file_a_favorite(wa, versions, favorite):
    """``Repository.save_code_snippet`` — המסלול של הבוט ושל כלי הכתיבה ב-MCP."""
    from database.models import CodeSnippet
    from database.repository import Repository

    _seed(wa, "bot.md", versions=versions, favorite=favorite)

    saved = Repository(_Manager(wa.get_db().code_snippets)).save_code_snippet(
        CodeSnippet(user_id=USER_ID, file_name="bot.md", code="# גרסה חדשה\n", programming_language="markdown")
    )

    assert saved is True
    _assert_new_version_is_still_a_favorite(wa, "bot.md", versions + 1)


def test_save_file_does_not_bring_back_a_mark_that_was_removed(wa):
    """``Repository.save_file`` — עריכה בבוט, ייבוא מ-GitHub ומ-ZIP.

    עד התיקון הוא לקח את הסימון מ-``get_latest_version``, שנשמר בקאש, והעביר אותו מפורשות — ואז ``save_code_snippet`` לא הפעיל את הכלל המשותף. קובץ שהוסר ממועדפים וקיבל שמירה לפני שהקאש פג חזר למועדפים. כאן הקאש מחזיק את הגרסה המסומנת, הסימון מוסר במסד, והשמירה חייבת לראות את המסד.
    """
    from database.repository import Repository

    collection = wa.get_db().code_snippets
    repo = Repository(_Manager(collection))
    _seed(wa, "cached-mark.md", versions=1, favorite=(1,))
    assert repo.get_latest_version(USER_ID, "cached-mark.md")["is_favorite"] is True

    collection.update_many(
        {"user_id": USER_ID, "file_name": "cached-mark.md"},
        {"$set": {"is_favorite": False, "favorited_at": None}},
    )
    assert repo.get_latest_version(USER_ID, "cached-mark.md")["is_favorite"] is True, "הקאש לא החזיק את הגרסה — הבדיקה לא בודקת כלום"

    assert repo.save_file(USER_ID, "cached-mark.md", "# גרסה 2\n", "markdown") is True

    latest = _latest(wa, "cached-mark.md")
    assert latest["version"] == 2, latest
    assert latest.get("is_favorite") is False, f"סימון שהוסר חזר לחיים מהקאש: {latest}"


# ------------------------------------------------------ הכלל עצמו, מול המסד


def test_the_rule_ignores_versions_in_the_recycle_bin_and_takes_the_last_mark(wa):
    from file_favorite import favorite_fields_for_new_version

    collection = wa.get_db().code_snippets
    ids = _seed(wa, "binned.md", versions=2, favorite=(1,))
    collection.update_one({"_id": ids[0]}, {"$set": {"is_active": False}})
    # הסימון האחרון יושב בגרסה האמצעית — לא הראשונה שנכתבה ולא האחרונה — כדי שסדר הכתיבה או מספר הגרסה לא ייתנו את אותה תשובה במקרה.
    marks = _seed(wa, "remarked.md", versions=3, favorite=(1, 2, 3))
    later = FAVORITED + timedelta(days=3)
    collection.update_one({"_id": marks[1]}, {"$set": {"favorited_at": later}})

    assert favorite_fields_for_new_version(collection, USER_ID, "binned.md") == {
        "is_favorite": False, "favorited_at": None,
    }
    assert favorite_fields_for_new_version(collection, USER_ID, "remarked.md") == {
        "is_favorite": True, "favorited_at": later,
    }


def test_only_a_real_true_counts_as_marked_in_the_database(wa):
    """השאילתה מתאימה ``is_favorite: True``, ומונגו אינה ממירה ``1`` או ``"yes"`` לבוליאני.

    לערכים האלה יש כאן זמן סימון מאוחר יותר מהסימון האמיתי: אם הם היו נספרים, הם היו מנצחים במיון.
    """
    from file_favorite import favorite_fields_for_new_version

    collection = wa.get_db().code_snippets
    later = FAVORITED + timedelta(days=3)
    ids = _seed(wa, "loose.md", versions=3, favorite=(3,))
    collection.update_one({"_id": ids[0]}, {"$set": {"is_favorite": 1, "favorited_at": later}})
    collection.update_one({"_id": ids[1]}, {"$set": {"is_favorite": "yes", "favorited_at": later}})
    only_loose = _seed(wa, "only-loose.md", versions=1)
    collection.update_one({"_id": only_loose[0]}, {"$set": {"is_favorite": 1, "favorited_at": later}})

    assert favorite_fields_for_new_version(collection, USER_ID, "loose.md") == {
        "is_favorite": True, "favorited_at": FAVORITED,
    }
    assert favorite_fields_for_new_version(collection, USER_ID, "only-loose.md") == {
        "is_favorite": False, "favorited_at": None,
    }


# ------------------------------------------------------ הכלל עצמו, בכל סביבה


class _OneDoc:
    """אוסף שמחזיר מסמך אחד קבוע — לבדיקת ההחלטה על מה שחזר, בלי מסד."""

    def __init__(self, doc):
        self.doc = doc

    def find_one(self, *args, **kwargs):
        return self.doc


def test_the_rule_needs_a_file_name():
    """קריאה בלי שם קובץ היא שגיאה של הקורא — לא "לא מועדף" בשקט."""
    from file_favorite import favorite_fields_for_new_version

    with pytest.raises(ValueError):
        favorite_fields_for_new_version(_OneDoc(None), USER_ID)
    with pytest.raises(ValueError):
        favorite_fields_for_new_version(_OneDoc(None), USER_ID, "", None)


def test_the_rule_writes_an_explicit_not_favorite_when_nothing_is_marked():
    from file_favorite import favorite_fields_for_new_version

    assert favorite_fields_for_new_version(_OneDoc(None), USER_ID, "a.md") == {
        "is_favorite": False, "favorited_at": None,
    }


def test_the_mark_and_its_time_come_from_the_marked_version():
    from file_favorite import favorite_fields_for_new_version

    marked = {"is_favorite": True, "favorited_at": FAVORITED}
    assert favorite_fields_for_new_version(_OneDoc(marked), USER_ID, "a.md") == {
        "is_favorite": True, "favorited_at": FAVORITED,
    }


def test_only_a_real_true_counts_as_marked():
    """גם מול אוסף שאינו מונגו: מה שחזר נבדק שוב, ורק ``True`` בוליאני הוא סימון."""
    from file_favorite import favorite_fields_for_new_version

    for value in ("yes", 1):
        assert favorite_fields_for_new_version(_OneDoc({"is_favorite": value}), USER_ID, "a.md") == {
            "is_favorite": False, "favorited_at": None,
        }

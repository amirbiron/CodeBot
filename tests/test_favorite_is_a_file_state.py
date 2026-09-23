"""מועדף הוא מצב של **קובץ**, לא של מסמך גרסה.

קובץ הוא ``(user_id, file_name)``; כל גרסה היא מסמך נפרד ב-``code_snippets``. עמוד המועדפים מציג קובץ אם **איזושהי** גרסה פעילה שלו מסומנת — הכלל שכבר כתוב ב-``Repository.is_favorite`` — ולכן כל כתיבה של הסימון חייבת לחול על הקובץ כולו. שני כשלים עלו בפרודקשן ב-23.9.2026, ושניהם נבדקים כאן מול מונגו אמיתי:

1. **פעולה מרובה לפי מזהה גרסה.** "הסר ממועדפים" בבחירה מרובה סימן רק את המסמך שהמזהה שלו נשלח. העמוד מוסר את המזהה של הגרסה **האחרונה** בלבד, ולכן קובץ עם כמה גרסאות היה נשאר במועדפים — אותו באג שתוקן במחיקה המרובה (``file_deletion.py``).
2. **גרסה חדשה שמאבדת את הסימון.** חמישה מתוך שבעת המסלולים שכותבים גרסה בנו את המסמך החדש ביד ולא העבירו את ``is_favorite``/``favorited_at``: עריכה, העלאה, שמירת מדריך משותף ו-Incident Story ב-``webapp/app.py``, ושמירה מאוסף משותף ב-``webapp/collections_api.py``. בפרודקשן נמצאו שני קבצים מועדפים שהגרסה האחרונה שלהם לא מסומנת.

הכלל של הירושה יושב בפונקציה טהורה אחת (``file_favorite.favorite_fields_for_new_version``), וכל כותב קורא לה. השומר המבני שמוודא את זה נמצא לצד שומר חותמת התיאור ב-``tests/test_mcp_description_age.py``, על **אותה** רשימת כותבים — ולא כאן, כדי שלא תהיה רשימה שנייה שמתיישנת בנפרד (``bugbot-rules/derived-field-added-to-one-writer.md``). כאן יש לכל כותב בדיקה התנהגותית שקוראת את השדה בחזרה מהמסד, כי שומר מבני מוודא שהקוד **מזכיר** את הכלל ולא שהוא משתמש בתוצאה.

⚠️ מונגו אמיתי דרך ``wired_mongo``; בלי ``NOTE_FONTS_TEST_MONGO_URI`` הקובץ מדולג, וב-CI הוא אינו רץ (ראו ``docs/testing.rst``). הרצה מקומית — כמו בראש ``tests/test_files_list_one_row_per_file.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("flask")
pytest.importorskip("pymongo")

from bson import ObjectId  # noqa: E402

USER_ID = 8282
OTHER_USER = 9393
CREATED = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
FAVORITED = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)


class _CacheDisabled:
    is_enabled = False


@pytest.fixture
def wa(wired_mongo, monkeypatch):
    monkeypatch.setattr(wired_mongo, "cache", _CacheDisabled(), raising=True)
    wired_mongo.get_db().code_snippets.delete_many({})
    return wired_mongo


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


# --------------------------------------- גרסה חדשה יורשת את הסימון — בכל כותב


def _assert_new_version_is_still_a_favorite(wa, file_name, expected_version):
    latest = _latest(wa, file_name)
    assert latest["version"] == expected_version, f"לא נכתבה גרסה חדשה: {latest}"
    assert latest.get("is_favorite") is True, f"הגרסה החדשה איבדה את סימון המועדף: {latest}"
    assert latest.get("favorited_at") == FAVORITED, f"זמן הסימון לא עבר לגרסה החדשה: {latest}"


def test_editing_in_the_webapp_keeps_the_file_a_favorite(wa):
    ids = _seed(wa, "edited.md", versions=1, favorite=(1,))

    response = _client(wa).post(f"/edit/{ids[-1]}", data={
        "file_name": "edited.md", "code": "# גרסה 2\n", "description": "", "language": "markdown",
    })

    assert response.status_code in (200, 302), response.get_data(as_text=True)[:300]
    _assert_new_version_is_still_a_favorite(wa, "edited.md", 2)


def test_editing_a_file_whose_latest_version_lost_the_mark_keeps_it_in_favorites(wa):
    """המצב שנמצא בפרודקשן בשני קבצים: הגרסאות הישנות מסומנות, האחרונה לא.

    הממשק פותח לעריכה את הגרסה האחרונה, ולכן זו הגרסה שהעריכה יורשת ממנה — והיא לא מסומנת. מה שמחזיק את הקובץ במועדפים הוא הכלל ברמת הקובץ: איזושהי גרסה פעילה מסומנת. הבדיקה עוברת על שני הצדדים: כותבת דרך העריכה וקוראת דרך עמוד המועדפים.
    """
    ids = _seed(wa, "partial.md", versions=2, favorite=(1,))

    response = _client(wa).post(f"/edit/{ids[-1]}", data={
        "file_name": "partial.md", "code": "# גרסה 3\n", "description": "", "language": "markdown",
    })
    assert response.status_code in (200, 302), response.get_data(as_text=True)[:300]

    newest = _latest(wa, "partial.md")
    assert newest["version"] == 3
    page = _client(wa).get("/files?category=favorites").get_data(as_text=True)
    assert page.count('class="glass-card file-card"') == 1
    assert f'data-file-id="{newest["_id"]}"' in page, "הקובץ לא מוצג בגרסה האחרונה שלו"


def test_uploading_over_an_existing_file_keeps_it_a_favorite(wa):
    _seed(wa, "uploaded.md", versions=1, favorite=(1,))

    response = _client(wa).post("/upload", data={
        "file_name": "uploaded.md", "code": "# גרסה 2\n", "language": "markdown",
    })

    assert response.status_code in (200, 302), response.get_data(as_text=True)[:300]
    _assert_new_version_is_still_a_favorite(wa, "uploaded.md", 2)


def test_restoring_an_old_version_keeps_the_file_a_favorite(wa):
    ids = _seed(wa, "restored.md", versions=2, favorite=(1, 2))

    response = _client(wa).post(f"/api/file/{ids[-1]}/restore", json={"version": 1})

    assert response.status_code == 200, response.get_json()
    _assert_new_version_is_still_a_favorite(wa, "restored.md", 3)


def test_saving_a_shared_guide_over_an_existing_file_keeps_it_a_favorite(wa, monkeypatch):
    _seed(wa, "guide.md", versions=1, favorite=(1,))
    monkeypatch.setattr(
        wa, "get_internal_share",
        lambda share_id: {"code": "# מדריך\n", "file_name": "guide.md", "language": "markdown"},
    )

    response = _client(wa).post("/api/shared/save", json={"share_id": "abc"})

    assert response.status_code == 200, response.get_json()
    _assert_new_version_is_still_a_favorite(wa, "guide.md", 2)


def test_writing_an_incident_story_over_an_existing_file_keeps_it_a_favorite(wa):
    _seed(wa, "incident.md", versions=1, favorite=(1,))

    wa._persist_story_markdown_file(user_id=USER_ID, file_name="incident.md", markdown="# סיפור\n")

    _assert_new_version_is_still_a_favorite(wa, "incident.md", 2)


def test_saving_from_a_shared_collection_keeps_the_file_a_favorite(wa):
    from webapp.collections_api import _save_shared_document_to_user

    _seed(wa, "shared.md", versions=1, favorite=(1,))

    result = _save_shared_document_to_user(
        wa.get_db(), user_id=USER_ID,
        doc={"file_name": "shared.md", "content": "# משותף\n", "language": "markdown"},
    )

    assert result["ok"] is True, result
    _assert_new_version_is_still_a_favorite(wa, "shared.md", 2)


def test_saving_through_the_bot_and_mcp_path_keeps_the_file_a_favorite(wa):
    """``Repository.save_code_snippet`` — המסלול של הבוט ושל כלי הכתיבה ב-MCP."""
    from database.models import CodeSnippet
    from database.repository import Repository

    class _Manager:
        def __init__(self, collection):
            self.collection = collection

    _seed(wa, "bot.md", versions=1, favorite=(1,))

    saved = Repository(_Manager(wa.get_db().code_snippets)).save_code_snippet(
        CodeSnippet(user_id=USER_ID, file_name="bot.md", code="# גרסה 2\n", programming_language="markdown")
    )

    assert saved is True
    _assert_new_version_is_still_a_favorite(wa, "bot.md", 2)


# ----------------------------------------------------------- הכלל הטהור


def test_the_rule_inherits_from_the_first_marked_source():
    from file_favorite import favorite_fields_for_new_version

    marked = {"is_favorite": True, "favorited_at": FAVORITED}
    assert favorite_fields_for_new_version(None, {"is_favorite": False}, marked) == {
        "is_favorite": True, "favorited_at": FAVORITED,
    }


def test_the_rule_writes_an_explicit_not_favorite_when_nothing_is_marked():
    from file_favorite import favorite_fields_for_new_version

    assert favorite_fields_for_new_version(None, {}, {"is_favorite": False}) == {
        "is_favorite": False, "favorited_at": None,
    }


def test_only_a_real_true_counts_as_marked():
    """השאילתות במסד מתאימות ``is_favorite: True``, כלומר רק בוליאני אמיתי. ערך אחר אינו סימון."""
    from file_favorite import favorite_fields_for_new_version

    assert favorite_fields_for_new_version({"is_favorite": "yes"})["is_favorite"] is False
    assert favorite_fields_for_new_version({"is_favorite": 1})["is_favorite"] is False

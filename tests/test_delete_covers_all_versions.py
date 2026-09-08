"""מחיקה מורידה לסל את **כל** הגרסאות של הקובץ, בכל מסלול.

**למה זה קיים.** קובץ שהמשתמש רואה הוא ``(user_id, file_name)``; במסד כל
גרסה היא מסמך נפרד. כל מסך רשימה מקבץ לפי ``file_name`` ומוסר לממשק את
ה-``_id`` של הגרסה **האחרונה בלבד**. מסלולי המחיקה המרובה — בוובאפ
ובבוט — סימנו בדיוק את המסמך הזה, והגרסה שמתחתיו נשארה פעילה: הקובץ נעלם
מהמסך וחזר ברענון, גרסה אחת אחורה. קובץ עם גרסה יחידה נעלם סופית, כי לא
נשאר מתחתיו דבר — ולכן שני קבצים שנמחקו באותה פעולה התנהגו שונה.

הבדיקות רצות דרך ה-HTTP client ודרך ה-callback של הבוט — המסלולים
שהמשתמש עובר בהם — וקוראות בחזרה **מהמסד**, לא מערך ההחזרה של המחיקה.
"""

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

pytest.importorskip("flask")
pytest.importorskip("pymongo")

USER_ID = 4242
OTHER_USER = 9999
FILE = "amir.md"
STAMP = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)


def _seed(wired_mongo, file_name=FILE, versions=3, user_id=USER_ID):
    """קובץ אחד, כמה גרסאות, כולן פעילות. מחזיר את המזהים לפי סדר הגרסה."""
    db = wired_mongo.get_db()
    ids = []
    for v in range(1, versions + 1):
        oid = ObjectId()
        ids.append(oid)
        db.code_snippets.insert_one({
            "_id": oid,
            "user_id": user_id,
            "file_name": file_name,
            "code": f"# גרסה {v}",
            "programming_language": "markdown",
            "version": v,
            "is_active": True,
            "created_at": STAMP,
            "updated_at": STAMP + timedelta(minutes=v),
        })
    return ids


def _client(wired_mongo, user_id=USER_ID):
    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_data"] = {"id": user_id, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    return client


def _active(wired_mongo, file_name=FILE, user_id=USER_ID):
    """מספר הגרסאות שנשארו פעילות — נקרא מהמסד, לא מהתגובה."""
    return wired_mongo.get_db().code_snippets.count_documents(
        {"user_id": user_id, "file_name": file_name, "is_active": True})


def _reset(wired_mongo):
    wired_mongo.get_db().code_snippets.delete_many({})


def test_bulk_delete_in_the_webapp_trashes_every_version(wired_mongo):
    """המסלול שדווח: בחירה מרובה בעמוד הקבצים ← "העבר לסל"."""
    _reset(wired_mongo)
    ids = _seed(wired_mongo, versions=3)
    client = _client(wired_mongo)

    # העמוד שולח את המזהה של הגרסה האחרונה בלבד — כך הוא בנוי.
    resp = client.post("/api/files/bulk-delete",
                       json={"file_ids": [str(ids[-1])]})

    assert resp.status_code == 200, resp.data
    assert resp.get_json().get("success") is True, resp.get_json()
    assert _active(wired_mongo) == 0, (
        "נשארו גרסאות פעילות — הקובץ יחזור לרשימה ברענון")


def test_the_file_does_not_come_back_in_the_files_listing(wired_mongo):
    """הראיה שהמשתמש רואה: רענון עמוד הקבצים.

    ‏``_active`` בודק את המסד; זה בודק את מה שהמסך באמת מציג, כי הרשימה
    היא זו שמקבצת לפי שם ובוחרת את הגרסה הפעילה הגבוהה ביותר.
    """
    _reset(wired_mongo)
    ids = _seed(wired_mongo, versions=3)
    client = _client(wired_mongo)

    client.post("/api/files/bulk-delete", json={"file_ids": [str(ids[-1])]})

    page = client.get("/files")
    assert page.status_code == 200, page.status_code
    assert FILE.encode("utf-8") not in page.data, (
        "הקובץ חזר לעמוד הקבצים אחרי המחיקה")


def test_a_single_version_file_and_a_multi_version_file_behave_the_same(wired_mongo):
    """שני קבצים באותה פעולה — ההבדל היחיד ביניהם הוא מספר הגרסאות."""
    _reset(wired_mongo)
    multi = _seed(wired_mongo, file_name="many.md", versions=4)
    single = _seed(wired_mongo, file_name="one.md", versions=1)
    client = _client(wired_mongo)

    resp = client.post("/api/files/bulk-delete", json={
        "file_ids": [str(multi[-1]), str(single[-1])]})

    assert resp.status_code == 200, resp.data
    assert _active(wired_mongo, "many.md") == 0
    assert _active(wired_mongo, "one.md") == 0


def test_the_response_counts_files_and_not_documents(wired_mongo):
    """‏``deleted`` הוא מה שהמשתמש רואה כמספר קבצים.

    ‏``multi-select.js`` מדפיס ``${result.deleted} קבצים הועברו לסל``.
    אם השדה יחזיר מסמכים, קובץ אחד בן שש גרסאות יוצג כשישה קבצים.
    """
    _reset(wired_mongo)
    ids = _seed(wired_mongo, versions=6)
    client = _client(wired_mongo)

    body = client.post("/api/files/bulk-delete",
                       json={"file_ids": [str(ids[-1])]}).get_json()

    assert body["deleted"] == 1, body
    assert body["versions"] == 6, body


def test_a_file_of_another_user_is_not_touched(wired_mongo):
    """הבעלות נאכפת, ולא רק נבדקת מראש."""
    _reset(wired_mongo)
    theirs = _seed(wired_mongo, file_name="theirs.md", versions=2,
                   user_id=OTHER_USER)
    client = _client(wired_mongo)

    resp = client.post("/api/files/bulk-delete",
                       json={"file_ids": [str(theirs[-1])]})

    assert resp.status_code == 404, resp.data
    assert _active(wired_mongo, "theirs.md", user_id=OTHER_USER) == 2


def test_deleting_from_the_file_page_still_works(wired_mongo):
    """מסלול הבקרה — הוא תקין היום, וחייב להישאר תקין.

    אם **זה** נופל, ההשוואה בין המסלולים שגויה וצריך לעצור.
    """
    _reset(wired_mongo)
    ids = _seed(wired_mongo, versions=3)
    client = _client(wired_mongo)

    resp = client.post(f"/api/file/{ids[-1]}/trash", json={})

    assert resp.status_code == 200, resp.data
    assert _active(wired_mongo) == 0

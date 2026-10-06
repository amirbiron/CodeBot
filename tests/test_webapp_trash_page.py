"""עמוד הסל בוובאפ: המסלול המלא של קובץ בגרסה אחת.

**למה מונגו אמיתי ולא סטאב.** עד אוקטובר 2026 העמוד עשה ``find`` ומיין
בפייתון, ולכן סטאב ידני עם ``find``/``update_many``/``delete_many`` הספיק.
העמוד מריץ עכשיו אגרגציה אחת עם ``$unionWith``, שני ``$lookup`` ו-``$group``
(``file_deletion.recycle_bin_rows_pipeline``), ואין לסטאב ידני דרך לענות
עליה בלי לממש מחדש מנוע אגרגציה — כלומר להמציא תוצאות. הבדיקה הזו רצה
מול מונגו, ו-``wired_mongo`` מדלג כשאין אחד.

הקיבוץ עצמו, הבוט, העימוד והפעולות נבדקים ב-``tests/test_trash_one_row_per_file.py``.
כאן נשמר דווקא המקרה שהסטאב תיאר: קובץ בגרסה **אחת**, שלא אמור לקבל שום
badge של מספר גרסאות, לאורך מחיקה ← שחזור ← מחיקה סופית.
"""

import types
from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId
from webapp import app as webapp_app
from services.db_health_service import CollectionStat

pytest.importorskip("flask")
pytest.importorskip("pymongo")

USER_ID = 123
FILE = "deleted.py"
DELETED_AT = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)


def _client(wa):
    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
    return client


def _seed_one_trashed_version(wa):
    oid = ObjectId()
    wa.get_db().code_snippets.insert_one({
        "_id": oid,
        "user_id": USER_ID,
        "file_name": FILE,
        "code": "print(1)",
        "programming_language": "python",
        "version": 1,
        "is_active": False,
        "created_at": DELETED_AT - timedelta(days=1),
        "deleted_at": DELETED_AT,
        "deleted_expires_at": DELETED_AT + timedelta(days=30),
    })
    return oid


def test_trash_page_lists_items_and_restore_purge(wired_mongo):
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    db.large_files.delete_many({})
    oid = _seed_one_trashed_version(wired_mongo)
    client = _client(wired_mongo)

    resp = client.get("/trash")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "סל מחזור" in html
    assert FILE in html
    # גרסה אחת אינה "N גרסאות" — ה-badge מופיע רק כשיש יותר מאחת.
    # (המילה עצמה מופיעה גם בתפריט של ``base.html``, ולכן הבדיקה היא על
    # הטקסט של ה-badge.)
    assert "1 גרסאות" not in html

    restored = client.post(f"/api/trash/{oid}/restore", json={})
    assert restored.status_code == 200, restored.data
    assert restored.get_json().get("ok") is True
    assert db.code_snippets.count_documents(
        {"user_id": USER_ID, "file_name": FILE, "is_active": True}) == 1
    assert FILE not in client.get("/trash").get_data(as_text=True)

    # חזרה לסל, ואז מחיקה סופית — דרך הראוטים, ובקריאה מהמסד.
    db.code_snippets.delete_many({})
    oid = _seed_one_trashed_version(wired_mongo)
    purged = client.post(f"/api/trash/{oid}/purge", json={})
    assert purged.status_code == 200, purged.data
    assert purged.get_json().get("ok") is True
    assert db.code_snippets.count_documents({"user_id": USER_ID}) == 0
    assert FILE not in client.get("/trash").get_data(as_text=True)


def test_db_health_collections_endpoint_rate_limited(monkeypatch):
    monkeypatch.setenv("DB_HEALTH_TOKEN", "test-db-health-token")
    # חלון ארוך במכוון. מה שנבדק כאן הוא שבקשה שנייה **בתוך** החלון נחסמת,
    # ולא כמה זמן החלון נמשך — ולכן אסור שהטסט יתחרה בשעון. עם חלון קצר
    # (2 שניות) הוא היה נכשל ב-CI לסירוגין, כי תחת pytest -n auto כמה תהליכי
    # בדיקה מתחרים על אותו מעבד והחלון הספיק לפוג לפני הבקשה השנייה.
    monkeypatch.setenv("DB_HEALTH_COLLECTIONS_COOLDOWN_SEC", "3600")

    # Reset global per-process cooldown state between tests
    monkeypatch.setattr(webapp_app, "_DB_HEALTH_COLLECTIONS_LAST_REQUEST_MONO", None, raising=False)

    class _Svc:
        # סינכרוני, כמו SyncDatabaseHealthService.get_collection_stats שה-WebApp
        # מקבל בפועל (services/db_health_service.py). הסטאב היה אסינכרוני, ועבר רק
        # כי המעטפת שהוסרה עשתה await על מה שקיבלה — כלומר הוא לא בדק את החוזה האמיתי.
        def get_collection_stats(self, collection_name=None):
            return [CollectionStat(name="users", count=1)]

    monkeypatch.setattr(webapp_app, "_get_webapp_db_health_service", lambda: _Svc(), raising=True)

    flask_app = webapp_app.app
    with flask_app.test_client() as client:
        headers = {"Authorization": "Bearer test-db-health-token"}
        resp1 = client.get("/api/db/collections", headers=headers)
        assert resp1.status_code == 200
        payload1 = resp1.get_json()
        assert payload1 and payload1.get("count") == 1

        resp2 = client.get("/api/db/collections", headers=headers)
        assert resp2.status_code == 429
        payload2 = resp2.get_json()
        assert payload2 and payload2.get("error") == "rate_limited"
        # קרוב לחלון המלא, כי כמעט לא עבר זמן — ומעל כל השהיה סבירה בראנר,
        # כך שהבדיקה הזו גם היא אינה תלויה בשעון.
        assert int(payload2.get("retry_after_sec") or 0) > 3000
        assert resp2.headers.get("Retry-After")


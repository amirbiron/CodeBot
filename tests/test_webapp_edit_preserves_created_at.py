"""ראוטי הוובאפ שומרים את תאריך היצירה של הקובץ.

הראוטים האלה כותבים ל-``code_snippets`` ישירות ולא דרך ``Repository``, ולכן
תיקון שכבת ה-DB לבדו אינו מכסה אותם. הבדיקות עוברות דרך ה-HTTP client, כלומר
דרך אותו ממשק בדיוק שהדפדפן משתמש בו.

מוסכמת הריפו: fakes בעבודת יד, בלי mongomock, בלי ייבוא מ-conftest.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId

from webapp import app as webapp_app

USER_ID = 123
FILE_OID = ObjectId("0123456789abcdef01234567")
FILE_ID = str(FILE_OID)
ORIGINAL_CREATED_AT = datetime(2020, 1, 1, 8, 30, tzinfo=timezone.utc)


class _Result:
    def __init__(self, inserted_id=None, matched=0, modified=0):
        self.inserted_id = inserted_id
        self.matched_count = matched
        self.modified_count = modified


class FakeCollection:
    def __init__(self, docs: Optional[List[Dict[str, Any]]] = None):
        self.docs: List[Dict[str, Any]] = list(docs or [])

    def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return _Result(inserted_id=doc["_id"])

    def find_one(self, query=None, projection=None, sort=None):
        items = self._filter(query or {})
        if sort:
            for key, direction in reversed(list(sort)):
                items.sort(key=lambda d: d.get(key, 0), reverse=(int(direction) < 0))
        return dict(items[0]) if items else None

    def find(self, query=None, projection=None, **kwargs):
        return list(self._filter(query or {}))

    def update_many(self, query, update, **kwargs):
        items = self._filter(query)
        for doc in items:
            doc.update(update.get("$set", {}))
        return _Result(matched=len(items), modified=len(items))

    def update_one(self, query, update, **kwargs):
        return self.update_many(query, update)

    def count_documents(self, query=None, **kwargs):
        return len(self._filter(query or {}))

    def delete_many(self, query=None, **kwargs):
        return _Result()

    def aggregate(self, pipeline, **kwargs):
        return []

    def _filter(self, query):
        def matches(doc):
            for key, expected in query.items():
                if key in ("$or", "$and"):
                    continue
                if isinstance(expected, dict):
                    if "$ne" in expected and doc.get(key) == expected["$ne"]:
                        return False
                    continue
                if doc.get(key) != expected:
                    return False
            return True

        return [d for d in self.docs if matches(d)]


class FakeDB:
    """כל אוסף שלא הוגדר במפורש מקבל אוסף ריק — הראוט נוגע בכמה בדרך."""

    def __init__(self, code_snippets: FakeCollection):
        self.code_snippets = code_snippets
        self._others: Dict[str, FakeCollection] = {}

    def __getattr__(self, name):
        return self._others.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return getattr(self, name)


def _existing_doc(**overrides):
    doc = {
        "_id": FILE_OID,
        "user_id": USER_ID,
        "file_name": "demo.py",
        "programming_language": "python",
        "code": "print('v1')\n",
        "description": "",
        "tags": [],
        "version": 1,
        "is_active": True,
        "created_at": ORIGINAL_CREATED_AT,
        "updated_at": ORIGINAL_CREATED_AT,
    }
    doc.update(overrides)
    return doc


def _client(monkeypatch, db):
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
    return client


def _newest(collection: FakeCollection) -> Dict[str, Any]:
    return max(collection.docs, key=lambda d: int(d.get("version", 0) or 0))


def test_edit_route_keeps_the_original_created_at(monkeypatch):
    """POST /edit/<id> — עריכה דרך הדפדפן לא מאפסת את "נוצר"."""
    snippets = FakeCollection([_existing_doc()])
    db = FakeDB(snippets)
    monkeypatch.setattr(
        webapp_app,
        "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: (_existing_doc(), "regular"),
    )
    client = _client(monkeypatch, db)

    resp = client.post(
        f"/edit/{FILE_ID}",
        data={"file_name": "demo.py", "code": "print('v2')\n", "language": "python"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), resp.status_code

    assert len(snippets.docs) == 2, "ציפינו שתיווצר גרסה חדשה"
    latest = _newest(snippets)
    assert latest["version"] == 2
    assert latest["created_at"] == ORIGINAL_CREATED_AT
    assert latest["updated_at"] > ORIGINAL_CREATED_AT


def test_edit_route_keeps_created_at_when_the_file_is_renamed(monkeypatch):
    """שינוי שם תוך כדי עריכה: prev ריק תחת השם החדש, והתאריך בא מ-file."""
    snippets = FakeCollection([_existing_doc()])
    db = FakeDB(snippets)
    monkeypatch.setattr(
        webapp_app,
        "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: (_existing_doc(), "regular"),
    )
    client = _client(monkeypatch, db)

    resp = client.post(
        f"/edit/{FILE_ID}",
        data={"code": "print('v2')\n", "language": "python", "file_name": "renamed.py"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), resp.status_code

    created = [d for d in snippets.docs if d.get("file_name") == "renamed.py"]
    assert created, "ציפינו לגרסה חדשה תחת השם החדש"
    assert created[-1]["created_at"] == ORIGINAL_CREATED_AT


def test_restore_route_keeps_the_original_created_at(monkeypatch):
    """POST /api/file/<id>/restore — שחזור גרסה לא מאפס את "נוצר"."""
    v1 = _existing_doc(_id=ObjectId(), version=1, code="print('v1')\n")
    v2 = _existing_doc(_id=FILE_OID, version=2, code="print('v2')\n",
                       created_at=ORIGINAL_CREATED_AT)
    snippets = FakeCollection([v1, v2])
    db = FakeDB(snippets)
    monkeypatch.setattr(
        webapp_app,
        "_get_user_file_by_id",
        lambda db_ref, user_id, file_id: dict(v2),
    )
    client = _client(monkeypatch, db)

    resp = client.post(f"/api/file/{FILE_ID}/restore", json={"version": 1})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:400]

    latest = _newest(snippets)
    assert latest["version"] == 3
    assert latest["created_at"] == ORIGINAL_CREATED_AT

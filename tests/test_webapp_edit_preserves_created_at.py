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


class _Cursor(list):
    """מספיק כדי ש-‎.sort(key, direction)‎ של pymongo יעבוד על התוצאה."""

    def sort(self, key_or_list, direction=1):
        pairs = [(key_or_list, direction)] if isinstance(key_or_list, str) else list(key_or_list)
        for key, order in reversed(pairs):
            list.sort(self, key=lambda d: d.get(key, 0), reverse=(int(order) < 0))
        return self

    def limit(self, n):
        return _Cursor(self[:n])

    def skip(self, n):
        return _Cursor(self[n:])


def _matches(doc, query):
    """התאמה לשאילתת Mongo — fail-closed על מה שלא ממומש.

    אופרטור שלא ממומש מחזיר ``False`` ולא "מתאים לכולם". פייק מתירני היה
    גורם לשאילתה להחזיר את *כל* המסמכים, והטסט היה עובר מהסיבה הלא נכונה.

    לא זורקים חריגה במכוון: כל קריאת DB בראוטים הנבדקים עטופה ב-
    ``try/except Exception``, ולכן חריגה מכאן הייתה נבלעת שם ומחזירה בדיוק
    את אותו ירוק שקרי. תוצאה ריקה, לעומת זאת, מפילה את האסרשן בקול.
    זו גם ההתנהגות של רוב הפייקים הקיימים בריפו.
    """
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, cond) for cond in expected):
                return False
            continue
        if key == "$and":
            if not all(_matches(doc, cond) for cond in expected):
                return False
            continue
        if key.startswith("$"):
            return False  # אופרטור ברמת מסמך שלא ממומש
        value = doc.get(key)
        if isinstance(expected, dict):
            for op, operand in expected.items():
                if op == "$ne":
                    if value == operand:
                        return False
                elif op == "$in":
                    if value not in operand:
                        return False
                elif op == "$nin":
                    if value in operand:
                        return False
                elif op == "$exists":
                    if (key in doc) != bool(operand):
                        return False
                else:
                    return False  # אופרטור שדה שלא ממומש
        elif value != expected:
            return False
    return True


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

    def insert_many(self, docs, **kwargs):
        return _Result(inserted_id=[self.insert_one(d).inserted_id for d in docs])

    def find(self, query=None, projection=None, **kwargs):
        # קורסור ולא list: הראוט קורא ‎.sort('order', 1)‎ על התוצאה, ו-list.sort
        # לא מקבל ארגומנטים פוזיציוניים. ה-TypeError היה נבלע ב-except של הראוט.
        return _Cursor(self._filter(query or {}))

    def distinct(self, key, query=None, **kwargs):
        seen = []
        for doc in self._filter(query or {}):
            value = doc.get(key)
            if value is not None and value not in seen:
                seen.append(value)
        return seen

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
        return [d for d in self.docs if _matches(d, query or {})]


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


class TestFakeMatchesFailsClosed:
    """הפייק עצמו — לוגיקה לא טריוויאלית שצריכה בדיקה משלה.

    פייק שמתאים לכל מסמך על אופרטור שהוא לא מכיר גורם לשאילתה להחזיר את
    *כל* האוסף, והטסט שמעליו עובר מהסיבה הלא נכונה. לכן אופרטור לא ממומש
    מחזיר ``False`` ולא "מתאים".

    למה לא לזרוק חריגה: כל קריאת DB בראוטים הנבדקים עטופה ב-
    ``try/except Exception``, ולכן חריגה מכאן הייתה נבלעת שם ומחזירה בדיוק
    את אותו ירוק שקרי — רק עם יותר קוד.
    """

    DOC = {"user_id": 1, "file_name": "a.py", "is_active": True, "version": 3}

    def test_equality(self):
        assert _matches(self.DOC, {"user_id": 1}) is True
        assert _matches(self.DOC, {"user_id": 2}) is False

    def test_ne(self):
        assert _matches(self.DOC, {"version": {"$ne": 9}}) is True
        assert _matches(self.DOC, {"version": {"$ne": 3}}) is False

    def test_in_and_nin(self):
        assert _matches(self.DOC, {"version": {"$in": [3, 4]}}) is True
        assert _matches(self.DOC, {"version": {"$in": [4, 5]}}) is False
        assert _matches(self.DOC, {"version": {"$nin": [4, 5]}}) is True
        assert _matches(self.DOC, {"version": {"$nin": [3]}}) is False

    def test_exists(self):
        assert _matches(self.DOC, {"file_name": {"$exists": True}}) is True
        assert _matches(self.DOC, {"missing": {"$exists": True}}) is False

    def test_or_and_and(self):
        assert _matches(self.DOC, {"$or": [{"user_id": 9}, {"user_id": 1}]}) is True
        assert _matches(self.DOC, {"$or": [{"user_id": 9}, {"user_id": 8}]}) is False
        assert _matches(self.DOC, {"$and": [{"user_id": 1}, {"version": 3}]}) is True
        assert _matches(self.DOC, {"$and": [{"user_id": 1}, {"version": 9}]}) is False

    def test_unimplemented_field_operator_matches_nothing(self):
        """‏$gt לא ממומש — ולכן לא מתאים, במקום להתאים לכל מסמך."""
        assert _matches(self.DOC, {"version": {"$gt": 1}}) is False

    def test_unimplemented_document_operator_matches_nothing(self):
        assert _matches(self.DOC, {"$nor": [{"user_id": 9}]}) is False

    def test_cursor_supports_sort_like_pymongo(self):
        """‏find() חייב להחזיר קורסור: הראוט קורא ‎.sort('order', 1)‎ על התוצאה."""
        coll = FakeCollection([{"order": 2, "n": "b"}, {"order": 1, "n": "a"}])
        assert [d["n"] for d in coll.find({}).sort("order", 1)] == ["a", "b"]
        assert [d["n"] for d in coll.find({}).sort("order", -1)] == ["b", "a"]

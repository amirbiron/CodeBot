"""ראוטי הוובאפ: שמירת גרסה חותמת את זמן הכתיבה, וההיסטוריה מציגה אותו.

**למה זה קיים.** שמירה של קובץ **נעוץ** דרך הבוט או ה-MCP חתמה את שעתה על
כל הגרסאות הקודמות, וההיסטוריה בדפדפן הציגה את כולן כאותו רגע. ההצגה
עברה לשדה ``version_created_at``, שנכתב פעם אחת ב-insert ואינו מתעדכן.

הראוטים האלה כותבים ל-``code_snippets`` **ישירות**, בחיבור מונגו משלהם, ולא
דרך ``Repository`` — ולכן תיקון בשכבת ה-DB לבדו אינו מכסה אותם. הבדיקות
עוברות דרך ה-HTTP client, כלומר אותו ממשק שהדפדפן משתמש בו.

מוסכמת הריפו: fakes בעבודת יד, בלי mongomock, בלי ייבוא מ-conftest.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from bson import ObjectId

pytest.importorskip("flask")

from webapp import app as webapp_app  # noqa: E402

from file_dates import VERSION_CREATED_AT_FIELD  # noqa: E402

USER_ID = 321
ORIGINAL = datetime(2020, 1, 1, 8, 30, tzinfo=timezone.utc)


class _Result:
    def __init__(self, inserted_id=None, matched=0, modified=0):
        self.inserted_id = inserted_id
        self.matched_count = matched
        self.modified_count = modified


class _Cursor(list):
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
    """התאמה לשאילתת Mongo — fail-closed על אופרטור שלא ממומש.

    אופרטור לא ממומש מחזיר ``False`` ולא "מתאים לכולם": פייק מתירני היה
    מחזיר את כל המסמכים והבדיקה הייתה עוברת מהסיבה הלא נכונה.
    """
    for key, expected in (query or {}).items():
        if key == "$or":
            if not any(_matches(doc, cond) for cond in expected):
                return False
            continue
        if key == "$and":
            if not all(_matches(doc, cond) for cond in expected):
                return False
            continue
        if key.startswith("$"):
            return False
        value = doc.get(key)
        if isinstance(expected, dict):
            for op, operand in expected.items():
                if op == "$ne":
                    if value == operand:
                        return False
                elif op == "$in":
                    if value not in operand:
                        return False
                elif op == "$exists":
                    if (key in doc) != bool(operand):
                        return False
                else:
                    return False
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

    def find(self, query=None, projection=None, **kwargs):
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
        items = self._filter(query)
        if not items:
            return _Result()
        items[0].update(update.get("$set", {}))
        return _Result(matched=1, modified=1)

    def count_documents(self, query=None, **kwargs):
        return len(self._filter(query or {}))

    def delete_many(self, query=None, **kwargs):
        return _Result()

    def aggregate(self, pipeline, **kwargs):
        """מממש ``$match``/``$sort``/``$limit``/``$project`` בלבד.

        ``$addFields`` של ראוט ההיסטוריה מחשב ``file_size``/``lines_count``
        מתוך ``code`` **רק כשהם חסרים או אפס**; מסמכי הבדיקה נושאים אותם,
        ולכן דילוג על השלב שקול לחישוב עבור הקלט הזה. ``$project`` דווקא
        **כן** ממומש, כי אם השדה החדש לא ייכלל בו — זו בדיוק התקלה.
        """
        docs = [dict(d) for d in self.docs]
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if _matches(d, stage["$match"])]
            elif "$sort" in stage:
                for key, direction in reversed(list(stage["$sort"].items())):
                    docs.sort(key=lambda d: d.get(key, 0), reverse=(int(direction) < 0))
            elif "$limit" in stage:
                docs = docs[: int(stage["$limit"])]
            elif "$project" in stage:
                keep = {k for k, v in stage["$project"].items() if v}
                docs = [{k: v for k, v in d.items() if k in keep} for d in docs]
        return docs

    def _filter(self, query):
        return [d for d in self.docs if _matches(d, query or {})]


class FakeDB:
    def __init__(self, code_snippets: FakeCollection):
        self.code_snippets = code_snippets
        self._others: Dict[str, FakeCollection] = {}

    def __getattr__(self, name):
        return self._others.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return getattr(self, name)


def _version_doc(version: int, *, pinned: bool = False, oid=None, **overrides):
    doc = {
        "_id": oid or ObjectId(),
        "user_id": USER_ID,
        "file_name": "handoff.md",
        "programming_language": "markdown",
        "code": f"# גרסה {version}\n",
        "description": "",
        "tags": [],
        "version": version,
        "is_active": True,
        "created_at": ORIGINAL,
        "updated_at": ORIGINAL + timedelta(days=version),
        "file_size": 20,
        "lines_count": 2,
    }
    if pinned:
        doc.update({"is_pinned": True, "pinned_at": ORIGINAL, "pin_order": 6})
    doc.update(overrides)
    return doc


def _client(monkeypatch, db):
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    return client


def _by_version(collection: FakeCollection) -> List[Dict[str, Any]]:
    return sorted(collection.docs, key=lambda d: int(d.get("version", 0) or 0))


# --- שמירת גרסה מהדפדפן ----------------------------------------------------


def test_edit_route_stamps_the_new_version(monkeypatch):
    """POST /edit/<id> — הגרסה החדשה נושאת את זמן הכתיבה שלה."""
    existing = _version_doc(1)
    snippets = FakeCollection([existing])
    monkeypatch.setattr(
        webapp_app, "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: (dict(existing), "regular"),
    )
    client = _client(monkeypatch, FakeDB(snippets))

    resp = client.post(
        f"/edit/{existing['_id']}",
        data={"file_name": "handoff.md", "code": "# גרסה 2\n", "language": "markdown"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), resp.status_code

    docs = _by_version(snippets)
    assert len(docs) == 2, "ציפינו לגרסה חדשה"
    assert isinstance(docs[-1].get(VERSION_CREATED_AT_FIELD), datetime)


def test_edit_route_on_a_pinned_file_leaves_older_stamps_alone(monkeypatch):
    """הבאג שדווח, מצד הדפדפן: העברת הנעיצה לא נוגעת בחותמות ההיסטוריה."""
    v1 = _version_doc(1)
    v2 = _version_doc(2, pinned=True)
    snippets = FakeCollection([v1, v2])
    before = [v1["updated_at"], v2["updated_at"]]
    monkeypatch.setattr(
        webapp_app, "_get_user_any_file_by_id",
        lambda db_ref, user_id, file_id: (dict(v2), "regular"),
    )
    client = _client(monkeypatch, FakeDB(snippets))

    resp = client.post(
        f"/edit/{v2['_id']}",
        data={"file_name": "handoff.md", "code": "# גרסה 3\n", "language": "markdown"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), resp.status_code

    docs = _by_version(snippets)
    assert [d["version"] for d in docs] == [1, 2, 3]
    assert [d["updated_at"] for d in docs[:2]] == before, "חותמות ההיסטוריה זזו"
    assert [bool(d.get("is_pinned")) for d in docs] == [False, False, True]
    assert docs[-1].get("pin_order") == 6, "סדר הנעיצה עבר לגרסה החדשה"


def test_restore_route_stamps_the_new_version(monkeypatch):
    """POST /api/file/<id>/restore — שחזור גרסה יוצר שורה חדשה, ומסמן מתי."""
    v1 = _version_doc(1)
    v2 = _version_doc(2)
    snippets = FakeCollection([v1, v2])
    monkeypatch.setattr(
        webapp_app, "_get_user_file_by_id",
        lambda db_ref, user_id, file_id: dict(v2),
    )
    client = _client(monkeypatch, FakeDB(snippets))

    resp = client.post(f"/api/file/{v2['_id']}/restore", json={"version": 1})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    docs = _by_version(snippets)
    assert [d["version"] for d in docs] == [1, 2, 3]
    assert isinstance(docs[-1].get(VERSION_CREATED_AT_FIELD), datetime)
    assert docs[0]["updated_at"] == v1["updated_at"], "השחזור נגע בגרסה המקורית"


# --- תצוגת ההיסטוריה --------------------------------------------------------


def test_history_returns_the_write_time_of_each_version(monkeypatch):
    """GET /api/file/<id>/history — לכל גרסה הזמן שלה, לא זמן של הקובץ."""
    stamps = [ORIGINAL + timedelta(days=d) for d in (1, 2, 3)]
    docs = [
        _version_doc(i + 1, **{VERSION_CREATED_AT_FIELD: stamp})
        for i, stamp in enumerate(stamps)
    ]
    snippets = FakeCollection(docs)
    monkeypatch.setattr(
        webapp_app, "_get_user_file_by_id",
        lambda db_ref, user_id, file_id: dict(docs[-1]),
    )
    client = _client(monkeypatch, FakeDB(snippets))

    resp = client.get(f"/api/file/{docs[-1]['_id']}/history")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    payload = resp.get_json()
    assert payload.get("ok") is True, payload

    shown = [v.get("version_created_at") for v in payload["versions"]]
    assert all(shown), payload["versions"]
    assert len(set(shown)) == 3, shown


def test_history_derives_the_time_from_the_objectid_for_legacy_rows(monkeypatch):
    """מסמכים ישנים שה-``updated_at`` שלהם נדרס — הזמן בא מה-ObjectId."""
    clobbered = datetime(2026, 9, 16, 1, 52, 49, tzinfo=timezone.utc)
    oids = [ObjectId() for _ in range(3)]
    docs = [
        _version_doc(i + 1, oid=oid, updated_at=clobbered)
        for i, oid in enumerate(oids)
    ]
    for doc in docs:
        doc.pop(VERSION_CREATED_AT_FIELD, None)
    snippets = FakeCollection(docs)
    monkeypatch.setattr(
        webapp_app, "_get_user_file_by_id",
        lambda db_ref, user_id, file_id: dict(docs[-1]),
    )
    client = _client(monkeypatch, FakeDB(snippets))

    resp = client.get(f"/api/file/{docs[-1]['_id']}/history")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    payload = resp.get_json()

    by_version = {v["version"]: v for v in payload["versions"]}
    expected = {
        v: webapp_app.safe_iso(oid.generation_time, "version_created_at")
        for v, oid in zip((1, 2, 3), oids)
    }
    got = {v: by_version[v]["iso_version_created"] for v in (1, 2, 3)}
    assert got == expected, got
    # ולא הערך הדרוס, שהוא מה שהוצג עד התיקון.
    clobbered_iso = webapp_app.safe_iso(clobbered, "updated_at")
    assert clobbered_iso not in got.values()

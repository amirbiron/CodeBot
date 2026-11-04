"""שמירה עם שם אחר בעמוד העריכה כותבת קובץ אחר — והוא לא יורש מהקובץ שנערך.

``edit_file_page`` כותב את הגרסה תחת השם שבטופס, והקובץ שנערך נשאר פעיל עם כל הגרסאות שלו. כלומר בפועל זה קובץ חדש. עד 4.11.2026 המסלול העביר אליו בכל זאת את מה ששייך לקובץ שנערך, כאילו זה שינוי שם: תאריך היצירה, הפתקים, השיוך לאוספים, המועדף והנעיצה (והנעיצה גם הוסרה מהמקורי). בפרודקשן: קובץ שנשמר בשם חדש לא הופיע בראש ``/files``, שממוין לפי ``created_at``, והפתק שנכתב על הקובץ המקורי עבר לקובץ החדש.

שלושה מצבים נבדקים כאן, ובכל אחד גם הקובץ שנערך:

1. **שם שעדיין לא קיים** — קובץ בגרסה 1, עם תאריך יצירה של זמן השמירה, בלי פתקים, אוספים, מועדף ונעיצה, ועם מה שבטופס בלבד.
2. **שם שכבר תפוס על ידי קובץ אחר** — הגרסה הבאה של הקובץ ההוא, וכל מה שהשמירה ממלאת בעצמה בא ממנו בלבד.
3. **אותו שם** — לא השתנה: יורש הכל, כמו היום.

**הטופס נגזר מה-HTML** שהראוט מחזיר ב-GET, ולא נבנה ביד (``claude-md-snippets/testing.md``, כלל 1): התגיות, התיאור וקישור המקור מגיעים לשרת ממולאים מראש מהקובץ שנערך, וזה בדיוק מה שמבדיל "מה שבטופס" מ"ירושה". רק השדה שהמשתמש משנה — השם, או שדה שהוא מוחק — מוחלף לפני השליחה.

מונגו מוחלף בדמות שבנויה ביד, בלי mongomock ובלי ייבוא מ-conftest, כמו ב-``tests/test_webapp_edit_preserves_created_at.py``. ההתאמה לשאילתות היא fail-closed: אופרטור שלא ממומש לא מתאים לאף מסמך, כדי שתוצאה ריקה תפיל את האסרשן ולא תעבור בשקט דרך ה-``except`` של הראוט.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import pytest

pytest.importorskip("flask")

from bson import ObjectId  # noqa: E402

from sticky_notes_scope import make_scope_id  # noqa: E402
from webapp import app as webapp_app  # noqa: E402

USER_ID = 6262
ORIGINAL = "report.md"
NEW_NAME = "Environment-Variables.md"
TAKEN = "other.md"
ORIGINAL_CREATED_AT = datetime(2026, 9, 30, 5, 47, 2, tzinfo=timezone.utc)
TAKEN_CREATED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
FAVORITED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
PINNED_AT = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
SOURCE_URL = "https://github.com/example/report"
COLLECTION_ID = "6a0000000000000000000001"


# ------------------------------------------------------------------ דמות של מונגו


class _Result:
    def __init__(self, inserted_id=None, matched=0, modified=0):
        self.inserted_id = inserted_id
        self.inserted_ids = inserted_id
        self.matched_count = matched
        self.modified_count = modified
        self.acknowledged = True


def _sort_key(key):
    # ``None`` וחסר לפני כל ערך, כמו במונגו (null נמוך מכל טיפוס אחר במיון).
    return lambda d: (d.get(key) is not None, d.get(key) if d.get(key) is not None else 0)


class _Cursor(list):
    def sort(self, key_or_list, direction=1):
        pairs = [(key_or_list, direction)] if isinstance(key_or_list, str) else list(key_or_list)
        for key, order in reversed(pairs):
            list.sort(self, key=_sort_key(key), reverse=(int(order) < 0))
        return self

    def limit(self, n):
        return _Cursor(self[:n])


def _matches(doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
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
                elif op == "$nin":
                    if value in operand:
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
        self.docs: List[Dict[str, Any]] = [dict(d) for d in (docs or [])]

    def _filter(self, query):
        return [d for d in self.docs if _matches(d, query or {})]

    def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return _Result(inserted_id=doc["_id"])

    def insert_many(self, docs, **kwargs):
        return _Result(inserted_id=[self.insert_one(d).inserted_id for d in docs])

    def find_one(self, query=None, projection=None, sort=None, **kwargs):
        items = _Cursor(self._filter(query or {}))
        if sort:
            items.sort(list(sort))
        return dict(items[0]) if items else None

    def find(self, query=None, projection=None, **kwargs):
        return _Cursor(dict(d) for d in self._filter(query or {}))

    def distinct(self, key, query=None, **kwargs):
        seen: List[Any] = []
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
        items = self._filter(query)[:1]
        for doc in items:
            doc.update(update.get("$set", {}))
        return _Result(matched=len(items), modified=len(items))

    def count_documents(self, query=None, **kwargs):
        return len(self._filter(query or {}))

    def delete_many(self, query=None, **kwargs):
        return _Result()

    def aggregate(self, pipeline, **kwargs):
        return []


class FakeDB:
    """אוסף שלא הוגדר מקבל אוסף ריק — הראוט נוגע בכמה בדרך."""

    def __init__(self, **collections: FakeCollection):
        self._collections: Dict[str, FakeCollection] = dict(collections)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self._collections.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return getattr(self, name)


# ------------------------------------------------------------------ הטופס מה-HTML


class _EditFormParser(HTMLParser):
    """השדות שהדפדפן היה שולח מ-``#editForm``: ‏input עם ``name``, ‏textarea, וה-option הנבחר ב-select."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fields: Dict[str, str] = {}
        self.form_attrs: Optional[Dict[str, str]] = None
        self._in_form = False
        self._textarea: Optional[str] = None
        self._select: Optional[str] = None
        self._select_first: Optional[str] = None
        self._select_chosen: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "form" and a.get("id") == "editForm":
            self._in_form = True
            self.form_attrs = a
            return
        if not self._in_form:
            return
        name = a.get("name")
        if tag == "input" and name and a.get("type") != "file":
            self.fields[name] = a.get("value", "")
        elif tag == "textarea" and name:
            self._textarea = name
            self.fields[name] = ""
        elif tag == "select" and name:
            self._select = name
            self._select_first = None
            self._select_chosen = None
        elif tag == "option" and self._select:
            value = a.get("value", "")
            if self._select_first is None:
                self._select_first = value
            if "selected" in a:
                self._select_chosen = value

    def handle_endtag(self, tag):
        if tag == "form" and self._in_form:
            self._in_form = False
        elif tag == "textarea":
            self._textarea = None
        elif tag == "select" and self._select:
            chosen = self._select_chosen if self._select_chosen is not None else self._select_first
            self.fields[self._select] = chosen or ""
            self._select = None

    def handle_data(self, data):
        if self._textarea:
            self.fields[self._textarea] += data


def _form_from_page(client, file_id) -> Dict[str, str]:
    response = client.get(f"/edit/{file_id}")
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    parser = _EditFormParser()
    parser.feed(response.get_data(as_text=True))
    assert parser.form_attrs is not None, "לא נמצא #editForm בעמוד העריכה"
    assert parser.form_attrs.get("method", "").lower() == "post"
    # בלי ``action`` הדפדפן שולח לכתובת של העמוד עצמו.
    assert not parser.form_attrs.get("action"), parser.form_attrs
    for field in ("file_name", "code", "description", "tags", "language", "source_url", "source_url_touched"):
        assert field in parser.fields, f"השדה {field} חסר בטופס: {sorted(parser.fields)}"
    return parser.fields


def _submit(client, file_id, **changes) -> Any:
    form = _form_from_page(client, file_id)
    form.update(changes)
    return client.post(f"/edit/{file_id}", data=form, follow_redirects=False)


# ------------------------------------------------------------------ הנתונים


def _version_doc(file_name, version, *, created_at, **extra) -> Dict[str, Any]:
    code = f"# {file_name} v{version}\n"
    doc = {
        "_id": ObjectId(),
        "user_id": USER_ID,
        "file_name": file_name,
        "code": code,
        "programming_language": "markdown",
        "description": "",
        "tags": [],
        "version": version,
        "is_active": True,
        "created_at": created_at,
        "updated_at": created_at + timedelta(hours=version),
        "version_created_at": created_at + timedelta(hours=version),
        "is_favorite": False,
        "favorited_at": None,
        "file_size": len(code.encode("utf-8")),
        "lines_count": len(code.split("\n")),
    }
    doc.update(extra)
    return doc


class _World:
    """הקובץ שנערך — שתי גרסאות, מועדף, נעוץ, עם פתקים ובאוסף — ומסביבו המסד."""

    def __init__(self, *, taken: Optional[List[Dict[str, Any]]] = None):
        common = {
            "tags": ["פרנקפורט"],
            "source_url": SOURCE_URL,
            "is_favorite": True,
            "favorited_at": FAVORITED_AT,
        }
        self.v1 = _version_doc(ORIGINAL, 1, created_at=ORIGINAL_CREATED_AT, **common)
        # התיאור נקבע בגרסה 2. חותמת שגדולה מ-1 היא מה שמבדיל "נקבע עכשיו" בקובץ חדש
        # (1) מחישוב מול הקובץ שנערך, שהיה נותן ``None`` — ולכן גיל "לא ידוע".
        self.v2 = _version_doc(
            ORIGINAL, 2, created_at=ORIGINAL_CREATED_AT,
            description="דוח המיפוי", description_set_at_version=2,
            is_pinned=True, pinned_at=PINNED_AT, pin_order=3, **common,
        )
        self.snippets = FakeCollection([self.v1, self.v2] + list(taken or []))
        scope = make_scope_id(USER_ID, ORIGINAL)
        self.notes = FakeCollection([
            # נכתב על הגרסה הראשונה — נתפס דרך ``file_id``.
            {"_id": ObjectId(), "user_id": USER_ID, "file_id": str(self.v1["_id"]),
             "scope_id": scope, "file_name": ORIGINAL, "content": "פתק על הדוח"},
            # רק ``scope_id`` — נתפס דרך השם.
            {"_id": ObjectId(), "user_id": USER_ID, "scope_id": scope, "content": "פתק לפי שם"},
        ])
        self.items = FakeCollection([
            {"_id": ObjectId(), "user_id": USER_ID, "collection_id": COLLECTION_ID,
             "source": "regular", "file_name": ORIGINAL, "folder": "", "workspace_state": "todo"},
        ])
        self.db = FakeDB(code_snippets=self.snippets, sticky_notes=self.notes, collection_items=self.items)
        self.invalidated: List[Any] = []

    def original_docs(self) -> List[Dict[str, Any]]:
        return sorted((copy.deepcopy(d) for d in self.snippets.docs if d["file_name"] == ORIGINAL),
                      key=lambda d: d["version"])

    def docs_of(self, name) -> List[Dict[str, Any]]:
        return sorted((d for d in self.snippets.docs if d["file_name"] == name), key=lambda d: d["version"])

    def snapshot(self) -> Dict[str, Any]:
        return {
            "original": self.original_docs(),
            "notes": copy.deepcopy(self.notes.docs),
            "items": copy.deepcopy(self.items.docs),
        }


@pytest.fixture
def world(monkeypatch):
    w = _World()
    _wire(monkeypatch, w)
    return w


def _wire(monkeypatch, w: _World):
    monkeypatch.setattr(webapp_app, "get_db", lambda: w.db)
    monkeypatch.setattr(webapp_app.cache, "invalidate_user_cache", lambda uid: w.invalidated.append(uid) or 0)


def _client():
    client = webapp_app.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה", "is_admin": False, "is_premium": False}
    return client


def _only(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    assert len(docs) == 1, docs
    return docs[0]


# ------------------------------------------------------------------ 1. שם שעדיין לא קיים


def test_a_new_name_is_a_new_file_that_inherits_nothing(world):
    before = world.snapshot()
    started = datetime.now(timezone.utc)

    response = _submit(_client(), world.v2["_id"], file_name=NEW_NAME)

    assert response.status_code == 302, response.get_data(as_text=True)[:400]
    created = _only(world.docs_of(NEW_NAME))
    assert created["version"] == 1
    # תאריך היצירה הוא זמן השמירה — אותו רגע שנכתב ל-``version_created_at`` — ולא של הקובץ שנערך.
    assert created["created_at"] == created["version_created_at"], created
    assert created["created_at"] >= started
    assert created["is_favorite"] is False and created["favorited_at"] is None, created
    assert not created.get("is_pinned"), created
    # מה שבטופס, כמו שהיה ממולא מהקובץ שנערך.
    assert created["tags"] == ["פרנקפורט"]
    assert created["description"] == "דוח המיפוי"
    assert created["source_url"] == SOURCE_URL
    # התיאור נחשב "נקבע עכשיו" בקובץ החדש: החותמת היא הגרסה שלו, כלומר גיל 0.
    assert created["description_set_at_version"] == 1, created

    after = world.snapshot()
    assert after == before, "הקובץ שנערך, הפתקים או האוספים השתנו"
    assert not [n for n in world.notes.docs if n.get("file_name") == NEW_NAME
                or n.get("scope_id") == make_scope_id(USER_ID, NEW_NAME)
                or n.get("file_id") == str(created["_id"])]
    assert not [i for i in world.items.docs if i.get("file_name") == NEW_NAME]


def test_the_edited_file_keeps_its_pin_its_favorite_and_its_date(world):
    """הנעיצה בפרט: עד התיקון היא עברה לקובץ החדש **והוסרה מהמקורי**."""
    _submit(_client(), world.v2["_id"], file_name=NEW_NAME)

    latest = world.docs_of(ORIGINAL)[-1]
    assert latest["is_pinned"] is True and latest["pinned_at"] == PINNED_AT and latest["pin_order"] == 3
    assert all(d["is_favorite"] is True for d in world.docs_of(ORIGINAL))
    assert all(d["created_at"] == ORIGINAL_CREATED_AT for d in world.docs_of(ORIGINAL))


def test_fields_cleared_in_the_form_stay_empty_in_the_new_file(world):
    response = _submit(
        _client(), world.v2["_id"],
        file_name=NEW_NAME, tags="", description="", source_url="", source_url_touched="edited",
    )

    assert response.status_code == 302, response.get_data(as_text=True)[:400]
    created = _only(world.docs_of(NEW_NAME))
    assert created["tags"] == []
    assert created["description"] == ""
    assert "source_url" not in created
    assert "description_set_at_version" not in created


def test_a_source_link_the_form_did_not_send_is_not_taken_from_the_edited_file(world):
    """קישור המקור שהשמירה ממלאת בעצמה — כששדה הקישור הגיע ריק ולא "נערך".

    בטופס של היום, כשלקובץ יש קישור, השדה נשלח ממולא ו-``source_url_touched`` הוא ``edited``. אבל ``edit-draft.js`` משחזר טיוטה ומחשב את הדגל מחדש, ולכן שדה ריק עם ``0`` הוא מצב שהשרת מקבל. במצב הזה השמירה ממלאת מהקובץ שאליו נשמרים — וקובץ חדש אין לו ממה.
    """
    _submit(_client(), world.v2["_id"], file_name=NEW_NAME, source_url="", source_url_touched="0")

    assert "source_url" not in _only(world.docs_of(NEW_NAME))


def test_the_files_list_cache_is_cleared_so_the_new_file_shows_up(world):
    """עד התיקון הביטול הזה הגיע מהעברת האוספים. בלעדיו הקובץ החדש היה מופיע ב-``/files`` רק אחרי ``FILES_PAGE_CACHE_TTL``."""
    _submit(_client(), world.v2["_id"], file_name=NEW_NAME)

    assert world.invalidated == [USER_ID]


def test_a_failing_cache_clear_does_not_turn_a_saved_file_into_a_failure(world, monkeypatch, caplog):
    def _boom(uid):
        raise RuntimeError("cache layer is down")

    monkeypatch.setattr(webapp_app.cache, "invalidate_user_cache", _boom)

    with caplog.at_level("WARNING"):
        response = _submit(_client(), world.v2["_id"], file_name=NEW_NAME)

    assert response.status_code == 302, response.get_data(as_text=True)[:400]
    assert _only(world.docs_of(NEW_NAME))
    assert any("files.edit_new_name_cache_invalidation_failed" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------ 2. שם שכבר תפוס


def _taken_versions(**latest_extra) -> List[Dict[str, Any]]:
    base = {"description": "קובץ אחר", "tags": ["אחר"], "source_url": "https://example.com/other"}
    older = _version_doc(TAKEN, 1, created_at=TAKEN_CREATED_AT, **base)
    latest = _version_doc(TAKEN, 2, created_at=TAKEN_CREATED_AT, **base)
    latest.update(latest_extra)
    return [older, latest]


def test_a_taken_name_becomes_the_next_version_of_that_file_and_inherits_only_from_it(monkeypatch):
    w = _World(taken=_taken_versions())
    _wire(monkeypatch, w)
    before = w.snapshot()

    response = _submit(_client(), w.v2["_id"], file_name=TAKEN)

    assert response.status_code == 302, response.get_data(as_text=True)[:400]
    newest = w.docs_of(TAKEN)[-1]
    assert newest["version"] == 3
    assert newest["created_at"] == TAKEN_CREATED_AT
    # הקובץ שנערך מועדף ונעוץ, והקובץ שאליו נשמרים — לא.
    assert newest["is_favorite"] is False, newest
    assert not newest.get("is_pinned"), newest
    assert w.snapshot() == before


def test_empty_fields_on_a_taken_name_are_filled_from_that_file(monkeypatch):
    w = _World(taken=_taken_versions())
    _wire(monkeypatch, w)

    _submit(_client(), w.v2["_id"], file_name=TAKEN, tags="", description="", source_url="", source_url_touched="0")

    newest = w.docs_of(TAKEN)[-1]
    assert newest["tags"] == ["אחר"]
    assert newest["description"] == "קובץ אחר"
    assert newest["source_url"] == "https://example.com/other"


def test_a_pinned_and_favorite_taken_name_keeps_its_own_pin_and_mark(monkeypatch):
    taken = _taken_versions(is_pinned=True, pinned_at=PINNED_AT - timedelta(days=5), pin_order=7,
                            is_favorite=True, favorited_at=FAVORITED_AT - timedelta(days=5))
    w = _World(taken=taken)
    _wire(monkeypatch, w)

    _submit(_client(), w.v2["_id"], file_name=TAKEN)

    versions = w.docs_of(TAKEN)
    newest = versions[-1]
    assert newest["is_pinned"] is True and newest["pin_order"] == 7, newest
    assert newest["pinned_at"] == PINNED_AT - timedelta(days=5)
    assert newest["is_favorite"] is True and newest["favorited_at"] == FAVORITED_AT - timedelta(days=5)
    assert [d["version"] for d in versions if d.get("is_pinned")] == [3], "הנעיצה לא עברה לגרסה החדשה בלבד"
    # והקובץ שנערך נשאר נעוץ.
    assert w.docs_of(ORIGINAL)[-1]["is_pinned"] is True


# ------------------------------------------------------------------ 3. אותו שם — לא השתנה


def test_the_same_name_still_inherits_everything(world):
    response = _submit(_client(), world.v2["_id"], code="# גרסה 3\n")

    assert response.status_code == 302, response.get_data(as_text=True)[:400]
    versions = world.docs_of(ORIGINAL)
    newest = versions[-1]
    assert newest["version"] == 3
    assert newest["created_at"] == ORIGINAL_CREATED_AT
    assert newest["is_favorite"] is True and newest["favorited_at"] == FAVORITED_AT
    assert newest["is_pinned"] is True and newest["pinned_at"] == PINNED_AT and newest["pin_order"] == 3
    assert [d["version"] for d in versions if d.get("is_pinned")] == [3]
    assert newest["source_url"] == SOURCE_URL
    assert newest["description_set_at_version"] == 2
    # הפתקים והאוספים לא זזו.
    assert all(n.get("file_id", str(world.v1["_id"])) == str(world.v1["_id"]) for n in world.notes.docs)
    assert [i["file_name"] for i in world.items.docs] == [ORIGINAL]


def test_the_same_name_still_fills_cleared_tags_and_description_from_the_file(world):
    """ההתנהגות של היום, ששמירה באותו שם שומרת עליה: שדה ריק מתמלא מהקובץ."""
    _submit(_client(), world.v2["_id"], code="# גרסה 3\n", tags="", description="")

    newest = world.docs_of(ORIGINAL)[-1]
    assert newest["tags"] == ["פרנקפורט"]
    assert newest["description"] == "דוח המיפוי"

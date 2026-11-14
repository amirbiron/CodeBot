"""דמה של אוסף פתקים עם הסמנטיקה של מונגו שהקוד נשען עליה — משותפת לבדיקות הראוטים של הפתקים.

עד נובמבר 2026 הדמה ישבה בתוך ``tests/test_note_archive.py``; כשנוספה הנעיצה לעמוד הקבצים
(``tests/test_files_page_pins.py``) היא עברה לכאן, כדי שלא יהיה לה עותק שני שנסחף. **היא מחקה
במפורש** את מה שהקוד נשען עליו, כי בלעדיו בדיקה ירוקה אינה אומרת דבר
(``docs/dev/sticky_notes_extending_backend.rst``, "הכשל האמיתי כאן היה בבדיקה"):

- שוויון ל-``None`` תופס גם שדה **חסר** וגם ``null`` — ``active_notes_filter``
  (https://www.mongodb.com/docs/manual/tutorial/query-for-null-fields/).
- ``{"$type": "date"}`` תופס רק ``datetime`` — ``archived_notes_filter``, ``files_page_pinned_filter``.
- ``find_one_and_update`` מחזיר ``None`` כשהפילטר לא תפס, ואת המסמך **אחרי** הכתיבה עם
  ``ReturnDocument.AFTER``.

מה שדמה לא יכולה להוכיח — תוכנית השאילתה, האינדקס, מקביליות אמיתית — נבדק מול מונגו אמיתי
(``tests/test_note_archive_mongo.py``, ``tests/test_files_page_pins_mongo.py``).

``make_client`` היא פונקציה ולא fixture — ייבוא של fixture בין קבצים הוא ``TESTING-PATTERNS.md`` T3.
"""

from __future__ import annotations

import copy
import datetime as dt

import note_threads as nt


USER = 7
OTHER_USER = 8


_MISSING = object()


def _matches(doc, query):
    for key, cond in query.items():
        if key == "$or":
            # המסנן של פתקי קובץ (``list_notes``) — ``scope_id`` או אחד ממזהי הגרסאות.
            if not any(_matches(doc, sub) for sub in cond):
                return False
            continue
        value = doc.get(key, _MISSING)
        if isinstance(cond, dict) and any(k.startswith("$") for k in cond):
            for op, arg in cond.items():
                if op == "$type":
                    assert arg == "date", "הדמה מכירה רק $type: date"
                    if not isinstance(value, dt.datetime):
                        return False
                elif op == "$exists":
                    if (value is not _MISSING) != bool(arg):
                        return False
                elif op == "$in":
                    if value is _MISSING or value not in arg:
                        return False
                elif op == "$nin":
                    if value is not _MISSING and value in arg:
                        return False
                else:  # pragma: no cover - אופרטור שהקוד אינו שולח
                    raise AssertionError(f"הדמה אינה מכירה {op}")
        elif cond is None:
            # שוויון ל-null תופס גם שדה חסר
            if value is not _MISSING and value is not None:
                return False
        elif value is _MISSING or value != cond:
            return False
    return True


def _project(doc, projection):
    if not projection:
        return copy.deepcopy(doc)
    # **היטלה של החרגה** (כל הערכים אפס, כמו ``{"_id": 0}`` של ייצוא הגיבוי): הכול חוץ ממה שנמנה.
    # מונגו מבחין בין השתיים לפי הערכים — https://www.mongodb.com/docs/manual/tutorial/project-fields-from-query-results/
    if not any(projection.values()):
        return {k: copy.deepcopy(v) for k, v in doc.items() if k not in projection}
    keep = {k for k, v in projection.items() if v}
    out = {k: copy.deepcopy(v) for k, v in doc.items() if k in keep or k == "_id"}
    return out


class _Res:
    def __init__(self, modified_count=0, deleted_count=0, inserted_id=None):
        self.modified_count = modified_count
        self.deleted_count = deleted_count
        self.inserted_id = inserted_id


class _Cursor(list):
    def sort(self, spec, direction=None):
        keys = [(spec, direction)] if isinstance(spec, str) else list(spec)
        for field, way in reversed(keys):
            self[:] = sorted(
                self,
                key=lambda d: (d.get(field) is not None, d.get(field)),
                reverse=(way == -1),
            )
        return self


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.count_fails = False
        self.find_fails = False
        self.update_many_fails = False
        self.calls = []

    def find_one(self, query, projection=None):
        self.calls.append(("find_one", query))
        for doc in self.docs:
            if _matches(doc, query):
                return _project(doc, projection)
        return None

    def find(self, query, projection=None):
        self.calls.append(("find", query, projection))
        if self.find_fails:
            raise RuntimeError("find failed")
        return _Cursor(_project(d, projection) for d in self.docs if _matches(d, query))

    def count_documents(self, query):
        self.calls.append(("count", query))
        if self.count_fails:
            raise RuntimeError("count failed")
        return sum(1 for d in self.docs if _matches(d, query))

    def _apply(self, doc, update):
        for field, value in (update.get("$set") or {}).items():
            doc[field] = value
        for field in (update.get("$unset") or {}):
            doc.pop(field, None)

    def find_one_and_update(self, query, update, projection=None, return_document=None):
        self.calls.append(("find_one_and_update", query, update))
        for doc in self.docs:
            if _matches(doc, query):
                self._apply(doc, update)
                return _project(doc, projection)
        return None

    def update_many(self, query, update):
        self.calls.append(("update_many", query, update))
        if self.update_many_fails:
            from pymongo.errors import PyMongoError
            raise PyMongoError("down")
        n = 0
        for doc in self.docs:
            if _matches(doc, query):
                self._apply(doc, update)
                n += 1
        return _Res(modified_count=n)

    def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", f"{len(self.docs) + 1:024x}")
        self.docs.append(doc)
        return _Res(inserted_id=doc["_id"])

    def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if _matches(doc, query):
                self._apply(doc, update)
                return _Res(modified_count=1)
        return _Res()

    def delete_one(self, query):
        for doc in self.docs:
            if _matches(doc, query):
                self.docs.remove(doc)
                return _Res(deleted_count=1)
        return _Res()

    def delete_many(self, query):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, query)]
        return _Res(deleted_count=before - len(self.docs))

    def aggregate(self, pipeline):
        return iter([])


class _DB:
    def __init__(self):
        self.sticky_notes = _Coll()
        self.note_reminders = _Coll()
        self.note_boards = _Coll()
        self._threads = _Coll()

    def __getitem__(self, name):
        assert name == nt.NOTE_THREADS_COLLECTION
        return self._threads


def make_client(monkeypatch, flask):
    from webapp import sticky_notes_api

    db = _DB()
    monkeypatch.setattr(sticky_notes_api, "get_db", lambda: db)
    monkeypatch.setattr(sticky_notes_api, "_ensure_indexes", lambda: None)
    monkeypatch.setattr(sticky_notes_api, "_current_user_is_admin", lambda: False)
    # הדמה עובדת עם מזהים כמחרוזת; ``ObjectId`` אמיתי היה הופך אותם לטיפוס אחר.
    monkeypatch.setattr(sticky_notes_api, "ObjectId", lambda x: _hex(x))

    app = flask.Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sticky_notes_api.sticky_notes_bp)
    test_client = app.test_client()
    with test_client.session_transaction() as sess:
        sess["user_id"] = USER
    test_client.db = db
    test_client.api = sticky_notes_api
    return test_client


def _hex(value):
    from webapp.sticky_notes_api import InvalidId

    text = str(value)
    if len(text) != 24 or any(c not in "0123456789abcdef" for c in text):
        raise InvalidId(text)
    return text

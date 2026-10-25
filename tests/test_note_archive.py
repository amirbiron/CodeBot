"""ארכיון הפתקים — השכבה הטהורה, הראוטים בוובאפ, והקישור הקבוע. רץ ב-CI.

**הדמה כאן מחקה במפורש את הסמנטיקה של מונגו שהקוד נשען עליה**, כי בלעדיה בדיקה ירוקה
אינה אומרת דבר (``docs/dev/sticky_notes_extending_backend.rst``, "הכשל האמיתי כאן היה
בבדיקה"):

- שוויון ל-``None`` תופס גם שדה **חסר** וגם ``null`` — זו כל ההגדרה של ``active_notes_filter``
  (https://www.mongodb.com/docs/manual/tutorial/query-for-null-fields/).
- ``{"$type": "date"}`` תופס רק ``datetime`` — ``archived_notes_filter``.
- ``find_one_and_update`` מחזיר ``None`` כשהפילטר לא תפס, ואת המסמך **אחרי** הכתיבה עם
  ``ReturnDocument.AFTER``.

מה שדמה לא יכולה להוכיח — תוכנית השאילתה, האינדקס, מקביליות אמיתית — נבדק מול מונגו אמיתי
ב-``tests/test_note_archive_mongo.py``, שאינו רץ ב-CI.
"""

from __future__ import annotations

import copy
import datetime as dt

import pytest

flask = pytest.importorskip("flask")

import note_threads as nt
import sticky_notes_target as snt


NOW = dt.datetime(2026, 10, 25, 9, 0, tzinfo=dt.timezone.utc)


# ---------------------------------------------------------------------------
# השכבה הטהורה
# ---------------------------------------------------------------------------


def test_archive_is_a_fourth_target_kind_identified_by_a_date():
    assert snt.note_target_kind({"archived_at": NOW}) == "archive"
    assert snt.note_target_ref({"archived_at": NOW}) == {"target": "archive"}


def test_an_archive_stamp_that_is_not_a_date_is_not_an_archive():
    """אותה הגדרה כמו ``archived_notes_filter`` (``$type: "date"``): מחרוזת אינה חותמת."""
    assert snt.note_target_kind({"archived_at": "2026-10-25"}) == "unknown"
    assert snt.note_target_kind({"archived_at": None}) == "unknown"


def test_an_archived_note_that_still_carries_a_board_is_ambiguous():
    with pytest.raises(snt.NoteTargetError):
        snt.validate_note_target({"archived_at": NOW, "board_id": "b1"})


def test_build_note_target_builds_an_archive_target_and_refuses_a_non_date():
    assert snt.build_note_target(archived_at=NOW) == {"archived_at": NOW}
    with pytest.raises(snt.NoteTargetError):
        snt.build_note_target(archived_at="2026-10-25")
    with pytest.raises(snt.NoteTargetError):
        snt.build_note_target(archived_at=NOW, board_id="b1")


def test_the_archive_update_drops_every_field_of_every_other_target():
    """הרשימה נגזרת מ-``TARGET_FIELDS`` — כל שדה של כל סוג שאינו ארכיון נמחק."""
    update = snt.archive_note_update(archived_at=NOW, title="שם")
    other_fields = {
        field for kind, fields in snt.TARGET_FIELDS.items() if kind != "archive" for field in fields
    }
    assert other_fields <= set(update["$unset"])
    assert set(snt.ARCHIVE_DROPPED_PLACEMENT_FIELDS) <= set(update["$unset"])
    assert update["$set"] == {"archived_at": NOW, "title": "שם", "updated_at": NOW}
    assert "width" not in update["$unset"] and "height" not in update["$unset"]


def test_the_archive_update_refuses_a_missing_or_raw_title():
    with pytest.raises(snt.NoteTargetError):
        snt.archive_note_update(archived_at=NOW, title="")
    with pytest.raises(snt.NoteTargetError):
        snt.archive_note_update(archived_at=NOW, title="  שם  ")


@pytest.mark.parametrize(
    ("requested", "current", "given", "expected"),
    [
        (None, "שם קיים", False, ("שם קיים", None)),
        (None, "", False, ("", "title_required")),
        (None, None, False, ("", "title_required")),
        ("  שם   חדש ", "ישן", True, ("שם חדש", None)),
        ("", "ישן", True, ("", "title_required")),
        (5, "ישן", True, ("", "title_required")),
        (["a"], "ישן", True, ("", "title_required")),
        ("א" * snt.MAX_NOTE_TITLE, None, True, ("א" * snt.MAX_NOTE_TITLE, None)),
        ("א" * (snt.MAX_NOTE_TITLE + 1), None, True, ("", "title_too_long")),
    ],
)
def test_resolve_archive_title(requested, current, given, expected):
    assert snt.resolve_archive_title(requested, current, requested_given=given) == expected


def test_the_active_and_archived_filters_are_the_shapes_the_index_answers():
    """הצורות נבחרו במדידה (``tests/test_note_archive_mongo.py``); שינוי צורה מפיל כאן קודם."""
    assert snt.active_notes_filter(7) == {"user_id": 7, "archived_at": None}
    assert snt.archived_notes_filter(7) == {"user_id": 7, "archived_at": {"$type": "date"}}
    assert snt.ARCHIVE_LIST_SORT == (("archived_at", -1), ("_id", -1))


def test_the_archive_cap_is_its_own_number():
    assert snt.MAX_ARCHIVED_NOTES_PER_USER == 500
    assert snt.MAX_ARCHIVED_NOTES_PER_USER != snt.MAX_NOTES_PER_USER


# ---------------------------------------------------------------------------
# דמה עם סמנטיקת מונגו
# ---------------------------------------------------------------------------


_MISSING = object()


def _matches(doc, query):
    for key, cond in query.items():
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


USER = 7
OTHER_USER = 8
OID = "a" * 24
OID2 = "b" * 24


@pytest.fixture
def client(monkeypatch):
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


def _board_note(**extra):
    doc = {
        "_id": OID, "user_id": USER, "board_id": "board-1", "content": "# כותרת\nגוף",
        "color": "yellow", "mode": "surface", "width": 300, "height": 240,
        "created_at": NOW, "updated_at": NOW,
    }
    doc.update(extra)
    return doc


# ---------------------------------------------------------------------------
# POST /note/<id>/archive
# ---------------------------------------------------------------------------


def test_archiving_a_titled_board_note_moves_it_to_the_archive(client):
    client.db.sticky_notes.docs.append(_board_note(title="שם"))

    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})
    body = res.get_json()

    assert res.status_code == 200, body
    assert body["ok"] is True and body["already_archived"] is False
    stored = client.db.sticky_notes.docs[0]
    assert snt.note_target_kind(stored) == "archive"
    for field in ("board_id", "mode", "file_id", "repo_name", "repo_path"):
        assert field not in stored
    assert stored["title"] == "שם"
    assert stored["width"] == 300
    # התשובה ממה שהכתיבה השאירה — עם ``archived_at``, בלי לוח
    assert body["note"]["archived_at"] is not None
    assert body["note"]["board_id"] == ""


def test_a_note_without_a_title_is_refused_and_nothing_is_written(client):
    client.db.sticky_notes.docs.append(_board_note())

    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})

    assert res.status_code == 400
    assert res.get_json()["error"] == "title_required"
    assert snt.note_target_kind(client.db.sticky_notes.docs[0]) == "board"


def test_a_title_in_the_request_is_saved_as_the_note_title(client):
    client.db.sticky_notes.docs.append(_board_note())

    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={"title": "  שם   מהחלון "})

    assert res.status_code == 200
    assert client.db.sticky_notes.docs[0]["title"] == "שם מהחלון"


def test_a_title_longer_than_the_cap_is_refused_not_cut(client):
    client.db.sticky_notes.docs.append(_board_note())

    res = client.post(
        f"/api/sticky-notes/note/{OID}/archive", json={"title": "א" * (snt.MAX_NOTE_TITLE + 1)}
    )

    assert res.status_code == 400
    assert res.get_json() == {"ok": False, "error": "title_too_long", "max": snt.MAX_NOTE_TITLE}
    assert "title" not in client.db.sticky_notes.docs[0]


def test_a_body_that_is_not_an_object_is_400(client):
    client.db.sticky_notes.docs.append(_board_note(title="שם"))
    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json=["x"])
    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_payload"


def test_a_note_of_another_user_is_404(client):
    client.db.sticky_notes.docs.append(_board_note(user_id=OTHER_USER, title="שם"))
    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})
    assert res.status_code == 404
    assert snt.note_target_kind(client.db.sticky_notes.docs[0]) == "board"


def test_an_already_archived_note_is_ok_without_a_write(client):
    """לחיצה כפולה, או מכשיר שני שעוד מציג את הפתק על הלוח — לא שגיאה, ולא כתיבה."""
    client.db.sticky_notes.docs.append(
        {"_id": OID, "user_id": USER, "archived_at": NOW, "title": "ישן", "content": ""}
    )

    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={"title": "חדש"})

    assert res.status_code == 200
    assert res.get_json()["already_archived"] is True
    assert client.db.sticky_notes.docs[0]["title"] == "ישן"
    assert not any(c[0] == "find_one_and_update" for c in client.db.sticky_notes.calls)


def test_the_write_is_conditional_on_the_note_not_being_archived_yet(client):
    """ה-CAS: הפילטר של הכתיבה נושא ``archived_at: None``, כלומר "עדיין לא בארכיון"."""
    client.db.sticky_notes.docs.append(_board_note(title="שם"))
    client.post(f"/api/sticky-notes/note/{OID}/archive", json={})
    writes = [c for c in client.db.sticky_notes.calls if c[0] == "find_one_and_update"]
    assert writes and writes[0][1] == {"_id": OID, "user_id": USER, "archived_at": None}


def test_a_note_archived_between_the_read_and_the_write_is_already_archived(client, monkeypatch):
    """הכתיבה לא תפסה כי בקשה מקבילה הקדימה — התשובה היא "כבר בארכיון", לא כשל ולא הצלחה כפולה."""
    coll = client.db.sticky_notes
    coll.docs.append(_board_note(title="שם"))
    real = coll.find_one_and_update

    def racing(query, update, **kw):
        coll.docs[0].pop("board_id", None)
        coll.docs[0]["archived_at"] = NOW
        return real(query, update, **kw)

    monkeypatch.setattr(coll, "find_one_and_update", racing)
    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})

    assert res.status_code == 200
    assert res.get_json()["already_archived"] is True


def test_a_note_deleted_between_the_read_and_the_write_is_404(client, monkeypatch):
    coll = client.db.sticky_notes
    coll.docs.append(_board_note(title="שם"))
    real = coll.find_one_and_update

    def deleting(query, update, **kw):
        coll.docs.clear()
        return real(query, update, **kw)

    monkeypatch.setattr(coll, "find_one_and_update", deleting)
    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})

    assert res.status_code == 404
    # הקוד של הראוט, ולא 404 של ראוט שאינו קיים
    assert res.get_json() == {"ok": False, "error": "note_not_found"}


def test_the_archive_cap_refuses_and_counts_only_archived_notes(client):
    coll = client.db.sticky_notes
    coll.docs.append(_board_note(title="שם"))
    for i in range(snt.MAX_ARCHIVED_NOTES_PER_USER):
        coll.docs.append({"_id": f"{i:024x}", "user_id": USER, "archived_at": NOW, "content": ""})
    # פתקים פעילים רבים אינם נספרים בתקרת הארכיון
    for i in range(10):
        coll.docs.append({"_id": f"f{i:023x}", "user_id": USER, "board_id": "x"})

    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})

    assert res.status_code == 409
    assert res.get_json() == {
        "ok": False, "error": "archive_quota_exceeded", "max": snt.MAX_ARCHIVED_NOTES_PER_USER,
    }
    assert snt.note_target_kind(coll.docs[0]) == "board"


def test_an_admin_is_exempt_from_the_archive_cap(client, monkeypatch):
    monkeypatch.setattr(client.api, "_current_user_is_admin", lambda: True)
    coll = client.db.sticky_notes
    coll.docs.append(_board_note(title="שם"))
    for i in range(snt.MAX_ARCHIVED_NOTES_PER_USER):
        coll.docs.append({"_id": f"{i:024x}", "user_id": USER, "archived_at": NOW, "content": ""})

    assert client.post(f"/api/sticky-notes/note/{OID}/archive", json={}).status_code == 200


def test_a_failed_count_refuses_the_archive(client):
    client.db.sticky_notes.docs.append(_board_note(title="שם"))
    client.db.sticky_notes.count_fails = True

    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})

    assert res.status_code == 409
    assert res.get_json()["error"] == "note_quota_unknown"


def test_archiving_resolves_the_open_threads_of_the_note_and_only_them(client):
    client.db.sticky_notes.docs.append(_board_note(title="שם"))
    threads = client.db._threads.docs
    threads.extend([
        {"_id": 1, "user_id": USER, "note_id": OID, "status": "open"},
        {"_id": 2, "user_id": USER, "note_id": OID, "status": "resolved", "resolved_at": NOW},
        {"_id": 3, "user_id": USER, "note_id": OID2, "status": "open"},
        {"_id": 4, "user_id": OTHER_USER, "note_id": OID, "status": "open"},
    ])

    body = client.post(f"/api/sticky-notes/note/{OID}/archive", json={}).get_json()

    assert body["threads_resolved"] == 1
    by_id = {t["_id"]: t for t in threads}
    assert by_id[1]["status"] == "resolved"
    assert by_id[1]["resolved_by"] == {"kind": "user", "client": None, "working_on": None}
    assert by_id[2]["resolved_at"] == NOW  # שרשור שכבר נפתר אינו נכתב שוב
    assert by_id[3]["status"] == "open"
    assert by_id[4]["status"] == "open"


def test_a_failure_to_resolve_threads_does_not_undo_the_archive(client):
    """ההעברה כבר נכתבה. ``threads_resolved: null`` אומר ללקוח שהשרשורים לא נסגרו."""
    client.db.sticky_notes.docs.append(_board_note(title="שם"))
    client.db._threads.update_many_fails = True

    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})
    body = res.get_json()

    assert res.status_code == 200
    assert body["threads_resolved"] is None
    assert snt.note_target_kind(client.db.sticky_notes.docs[0]) == "archive"


def test_the_reminder_of_an_archived_note_stays_active(client):
    client.db.sticky_notes.docs.append(_board_note(title="שם"))
    reminder = {"user_id": USER, "note_id": OID, "status": "pending", "remind_at": NOW}
    client.db.note_reminders.docs.append(dict(reminder))

    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})

    assert res.status_code == 200
    assert snt.note_target_kind(client.db.sticky_notes.docs[0]) == "archive"
    assert client.db.note_reminders.docs == [reminder]


# ---------------------------------------------------------------------------
# GET /archive ו-GET /archive/<id>
# ---------------------------------------------------------------------------


def _archived(oid, when, **extra):
    doc = {"_id": oid, "user_id": USER, "archived_at": when, "title": f"t-{oid[:2]}",
           "content": "גוף ארוך", "color": "#FFFFCC"}
    doc.update(extra)
    return doc


def test_the_list_is_newest_first_without_bodies_and_with_the_cap(client):
    coll = client.db.sticky_notes
    coll.docs.extend([
        _archived("1" * 24, NOW - dt.timedelta(days=2)),
        _archived("2" * 24, NOW),
        _archived("3" * 24, NOW - dt.timedelta(days=1)),
        _board_note(title="לוח"),  # לא בארכיון
        _archived("4" * 24, NOW, user_id=OTHER_USER),
    ])

    res = client.get("/api/sticky-notes/archive")
    body = res.get_json()

    assert res.status_code == 200
    assert [n["id"] for n in body["notes"]] == ["2" * 24, "3" * 24, "1" * 24]
    assert body["count"] == 3
    assert body["max"] == snt.MAX_ARCHIVED_NOTES_PER_USER
    assert set(body["notes"][0]) == {"id", "title", "color", "color_id", "archived_at"}
    find = [c for c in coll.calls if c[0] == "find"][0]
    assert "content" not in find[2]  # ההיטלה עצמה, לא רק הסריאלייזר
    assert res.headers["Cache-Control"] == "no-store"


def test_the_list_tells_an_admin_there_is_no_cap(client, monkeypatch):
    monkeypatch.setattr(client.api, "_current_user_is_admin", lambda: True)
    assert client.get("/api/sticky-notes/archive").get_json()["max"] is None


def test_a_list_that_failed_is_500_not_an_empty_archive(client):
    client.db.sticky_notes.find_fails = True

    res = client.get("/api/sticky-notes/archive")

    assert res.status_code == 500
    assert res.get_json() == {"ok": False, "error": "Failed to list archived notes"}


def test_one_archived_note_is_returned_whole(client):
    client.db.sticky_notes.docs.append(_archived(OID, NOW))

    res = client.get(f"/api/sticky-notes/archive/{OID}")
    body = res.get_json()

    assert res.status_code == 200
    assert body["note"]["content"] == "גוף ארוך"
    assert body["note"]["id"] == OID


def test_a_note_that_is_not_in_the_archive_is_404_on_the_archive_route(client):
    client.db.sticky_notes.docs.append(_board_note(title="שם"))
    res = client.get(f"/api/sticky-notes/archive/{OID}")
    assert res.status_code == 404
    assert res.get_json() == {"ok": False, "error": "note_not_found"}


def test_a_bad_id_is_400_on_the_archive_route(client):
    assert client.get("/api/sticky-notes/archive/xyz").status_code == 400


# ---------------------------------------------------------------------------
# תקרת המשתמש אינה סופרת את הארכיון
# ---------------------------------------------------------------------------


def test_creating_a_board_note_counts_only_active_notes(client, monkeypatch):
    """1000 פתקים פעילים חוסמים; 1000 שחלקם בארכיון — לא. תקרת הארכיון היא בנוסף."""
    coll = client.db.sticky_notes
    monkeypatch.setattr(client.api, "_resolve_owned_board", lambda db, uid, bid: {"_id": bid})
    for i in range(snt.MAX_NOTES_PER_USER - 1):
        coll.docs.append({"_id": f"{i:024x}", "user_id": USER, "board_id": "other"})
    coll.docs.append({"_id": "e" * 24, "user_id": USER, "archived_at": NOW})

    assert client.post("/api/sticky-notes/board/board-1", json={"content": "x"}).status_code == 201

    coll.docs.append({"_id": "d" * 24, "user_id": USER, "board_id": "other"})
    res = client.post("/api/sticky-notes/board/board-1", json={"content": "y"})
    assert res.status_code == 409
    assert res.get_json()["error"] == "note_quota_exceeded"

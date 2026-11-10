"""נעיצת פתקים לראש עמוד הקבצים — השכבה הטהורה, הראוטים, ההעברה לארכיון, הגיבוי והשחזור, והעמוד. רץ ב-CI.

הראוטים נבדקים מול הדמה המשותפת עם הסמנטיקה של מונגו (``tests/_notes_mongo_fake.py``): שוויון ל-``None``
שתופס גם שדה חסר, ``$type: "date"`` שתופס רק תאריך, ו-``find_one_and_update`` שמחזיר ``None`` כשהפילטר
לא תפס. מה שהדמה אינה יכולה להוכיח — התוכנית מול האינדקס, מרוץ אמיתי, שני הבוטסטראפים — נבדק מול מונגו
אמיתי ב-``tests/test_files_page_pins_mongo.py``, והזרימה בדפדפן ב-``tests/test_files_page_pins_browser.py``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

flask = pytest.importorskip("flask")

import sticky_notes_target as snt  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _notes_mongo_fake import USER, _Coll, make_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2026, 11, 10, 9, 0, tzinfo=dt.timezone.utc)
OID = "a" * 24
FIELD = snt.FILES_PAGE_PIN_FIELD


# ---------------------------------------------------------------------------
# השכבה הטהורה
# ---------------------------------------------------------------------------


def test_the_field_is_not_called_pinned_and_the_cap_is_four():
    """``pinned`` תפוס פעמיים (``is-pinned`` בפתקים, ``is_pinned`` בקבצים). התקרה — הכרעת המשתמש."""
    assert FIELD == "files_page_pinned_at"
    assert snt.MAX_FILES_PAGE_PINNED_NOTES == 4


def test_the_pinned_filter_is_the_shape_the_index_answers():
    """``$type: "date"`` ולא ``$exists`` — רק כך הגבולות על ``files_page_pinned_idx`` מדלגים על פתק שאינו
    נעוץ (נמדד ב-``tests/test_files_page_pins_mongo.py``); ורק פתקים פעילים."""
    assert snt.files_page_pinned_filter(7) == {"user_id": 7, FIELD: {"$type": "date"}, "archived_at": None}
    assert snt.FILES_PAGE_PINNED_SORT == ((FIELD, 1), ("_id", 1))


def test_the_pinned_filter_is_built_on_the_active_filter_and_not_a_copy_of_it(monkeypatch):
    """"פתק פעיל" מוגדר במקום אחד (``active_notes_filter``). עותק שלו כאן היה נשאר מאחור ביום שההגדרה משתנה."""
    monkeypatch.setattr(snt, "active_notes_filter", lambda user_id: {"user_id": int(user_id), "archived_at": None, "probe": 1})
    assert snt.files_page_pinned_filter(7)["probe"] == 1


@pytest.mark.parametrize(
    ("value", "given", "expected"),
    [
        (None, False, (4, None)),          # לא נשלח — התקרה הכללית
        (None, True, (4, None)),           # null — כמו לא נשלח
        (2, True, (2, None)),              # מכשיר צר מוריד
        (0, True, (0, None)),              # אין מקום לכרטיס בכלל
        (9, True, (4, None)),              # מכשיר רחב אינו מעלה
        (True, True, (0, "invalid_device_limit")),   # ``bool`` הוא ``int`` בפייתון
        (2.0, True, (0, "invalid_device_limit")),
        ("2", True, (0, "invalid_device_limit")),
        (-1, True, (0, "invalid_device_limit")),
        ([2], True, (0, "invalid_device_limit")),
    ],
)
def test_the_device_limit_only_lowers_the_cap(value, given, expected):
    assert snt.files_page_pin_limit(value, given=given) == expected


def test_archiving_drops_the_pin():
    """פתק שעובר לארכיון יורד מהנעיצה — השדה ברשימת השדות שההעברה מוחקת."""
    assert FIELD in snt.ARCHIVE_DROPPED_PLACEMENT_FIELDS
    update = snt.archive_note_update(archived_at=NOW, title="שם")
    assert FIELD in update["$unset"]


# ---------------------------------------------------------------------------
# הראוטים
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    return make_client(monkeypatch, flask)


def _board_note(oid=OID, **extra):
    doc = {
        "_id": oid, "user_id": USER, "board_id": "board-1", "content": "# כותרת\nגוף", "color": "yellow",
        "mode": "surface", "width": 300, "height": 240, "created_at": NOW, "updated_at": NOW,
    }
    doc.update(extra)
    return doc


def _pinned(i, **extra):
    return _board_note(oid=f"{i + 1:024x}", title=f"נעוץ {i}", **{FIELD: NOW + dt.timedelta(minutes=i)}, **extra)


def _calls(coll, kind):
    return [c for c in coll.calls if c[0] == kind]


def _pin(client, oid=OID, body=None):
    return client.post(f"/api/sticky-notes/note/{oid}/files-page-pin", json={} if body is None else body)


def test_pinning_a_board_note_writes_the_date_and_answers_from_what_was_written(client):
    coll = client.db.sticky_notes
    coll.docs.append(_board_note())

    res = _pin(client)
    body = res.get_json()

    assert res.status_code == 200, body
    assert body["ok"] is True and body["already_pinned"] is False
    stored = coll.docs[0]
    assert isinstance(stored[FIELD], dt.datetime)
    assert body[FIELD] == stored[FIELD].isoformat()
    assert body["note"][FIELD] == stored[FIELD].isoformat()
    # הנעיצה אינה עריכה: ``updated_at`` לא זז (``prev_updated_at`` של לשונית אחרת, ו"עודכן לאחרונה")
    assert stored["updated_at"] == NOW
    # הפתק נשאר פתק לוח, באותו מצב — הנעיצה היא שדה לצד היעד ולא במקומו
    assert snt.note_target_kind(stored) == "board" and stored["mode"] == "surface"


def test_the_write_is_conditional_on_an_active_board_note_that_is_not_pinned_yet(client):
    client.db.sticky_notes.docs.append(_board_note())
    _pin(client)

    [(_, query, update)] = _calls(client.db.sticky_notes, "find_one_and_update")
    assert query[FIELD] is None
    assert query["archived_at"] is None
    assert query["board_id"] == {"$nin": [None, ""]}
    assert query["user_id"] == USER and query["_id"] == OID
    assert set(update) == {"$set"} and set(update["$set"]) == {FIELD}


def test_an_already_pinned_note_is_ok_without_a_write(client):
    client.db.sticky_notes.docs.append(_board_note(**{FIELD: NOW}))

    res = _pin(client)

    assert res.status_code == 200
    assert res.get_json() == {"ok": True, "already_pinned": True, FIELD: NOW.isoformat()}
    assert not _calls(client.db.sticky_notes, "find_one_and_update")


def test_a_note_of_another_user_is_404(client):
    client.db.sticky_notes.docs.append(_board_note(user_id=USER + 1))

    assert _pin(client).status_code == 404


def test_an_archived_note_is_refused(client):
    client.db.sticky_notes.docs.append({"_id": OID, "user_id": USER, "archived_at": NOW, "title": "x"})

    res = _pin(client)

    assert res.status_code == 409
    assert res.get_json()["error"] == "note_archived"


def test_only_a_board_note_can_be_pinned(client):
    client.db.sticky_notes.docs.append({"_id": OID, "user_id": USER, "file_id": "f1", "content": "x"})

    res = _pin(client)

    assert res.status_code == 400
    assert res.get_json()["error"] == "not_a_board_note"


def test_the_cap_refuses_the_fifth_and_does_not_unpin_the_old_ones(client):
    coll = client.db.sticky_notes
    for i in range(snt.MAX_FILES_PAGE_PINNED_NOTES):
        coll.docs.append(_pinned(i))
    coll.docs.append(_board_note())

    res = _pin(client)

    assert res.status_code == 409
    assert res.get_json() == {
        "ok": False, "error": "files_page_pins_full", "max": 4, "pinned": 4, "device_limited": False,
    }
    assert FIELD not in coll.docs[-1]
    assert all(isinstance(d[FIELD], dt.datetime) for d in coll.docs[:4])


def test_an_admin_is_not_exempt_from_the_cap(client, monkeypatch):
    """תקרה של צורת-תוכן: עם ``is_admin=True`` הפטור היה מקדים כל בדיקה, והתקרה הייתה קבוע מת אצל אדמין."""
    monkeypatch.setattr(client.api, "_current_user_is_admin", lambda: True)
    coll = client.db.sticky_notes
    for i in range(snt.MAX_FILES_PAGE_PINNED_NOTES):
        coll.docs.append(_pinned(i))
    coll.docs.append(_board_note())

    assert _pin(client).status_code == 409


def test_an_archived_note_that_somehow_kept_its_pin_is_not_counted(client):
    """הספירה היא של פתקים פעילים בלבד — ``files_page_pinned_filter``."""
    coll = client.db.sticky_notes
    for i in range(3):
        coll.docs.append(_pinned(i))
    coll.docs.append({"_id": "f" * 24, "user_id": USER, "archived_at": NOW, FIELD: NOW})
    coll.docs.append(_board_note())

    assert _pin(client).status_code == 200


def test_a_failed_count_refuses_the_pin(client):
    client.db.sticky_notes.docs.append(_board_note())
    client.db.sticky_notes.count_fails = True

    res = _pin(client)

    assert res.status_code == 409
    assert res.get_json()["error"] == "note_quota_unknown"
    assert FIELD not in client.db.sticky_notes.docs[0]


def test_a_narrow_device_lowers_the_cap(client):
    coll = client.db.sticky_notes
    for i in range(2):
        coll.docs.append(_pinned(i))
    coll.docs.append(_board_note())

    res = _pin(client, body={"device_limit": 2})

    assert res.status_code == 409
    assert res.get_json() == {
        "ok": False, "error": "files_page_pins_full", "max": 2, "pinned": 2, "device_limited": True,
    }
    # בקרה: אותו מצב, ממכשיר שנכנסים בו שלושה — עובר
    assert _pin(client, body={"device_limit": 3}).status_code == 200


def test_a_wide_device_does_not_raise_the_cap(client):
    coll = client.db.sticky_notes
    for i in range(snt.MAX_FILES_PAGE_PINNED_NOTES):
        coll.docs.append(_pinned(i))
    coll.docs.append(_board_note())

    res = _pin(client, body={"device_limit": 10})

    assert res.status_code == 409
    assert res.get_json()["max"] == 4 and res.get_json()["device_limited"] is False


@pytest.mark.parametrize("bad", [True, "2", -1, 2.5, [1], {"n": 1}])
def test_a_device_limit_that_is_not_a_count_is_400(client, bad):
    client.db.sticky_notes.docs.append(_board_note())

    res = _pin(client, body={"device_limit": bad})

    assert res.status_code == 400
    assert res.get_json()["error"] == "invalid_device_limit"
    assert FIELD not in client.db.sticky_notes.docs[0]


def test_a_body_that_is_not_an_object_is_400(client):
    client.db.sticky_notes.docs.append(_board_note())

    res = client.post(f"/api/sticky-notes/note/{OID}/files-page-pin", json=[1])

    assert res.status_code == 400 and res.get_json()["error"] == "invalid_payload"


@pytest.mark.parametrize("raw", ["{", "null", "[1"], ids=["broken-json", "json-null", "broken-list"])
def test_a_body_that_was_sent_but_is_not_an_object_is_400_and_not_an_empty_body(client, raw):
    """``get_json(silent=True)`` מחזיר ``None`` גם על JSON פגום ועל ``null``. עד התיקון ``_json_object``
    הפך כל ``None`` למילון ריק, והנעיצה רצה בלי ה-``device_limit`` שהלקוח שלח."""
    client.db.sticky_notes.docs.append(_board_note())

    res = client.post(f"/api/sticky-notes/note/{OID}/files-page-pin", data=raw, content_type="application/json")

    assert res.status_code == 400 and res.get_json()["error"] == "invalid_payload"
    assert FIELD not in client.db.sticky_notes.docs[0]


def test_an_empty_body_is_still_the_defaults(client):
    """גוף ריק באמת — ולא גוף שלא פוענח — הוא "בלי ``device_limit``": התקרה הכללית."""
    client.db.sticky_notes.docs.append(_board_note())

    res = client.post(f"/api/sticky-notes/note/{OID}/files-page-pin", data="", content_type="application/json")

    assert res.status_code == 200, res.get_json()
    assert isinstance(client.db.sticky_notes.docs[0][FIELD], dt.datetime)


def _write_lost_to(client, monkeypatch, change):
    """הכתיבה המותנית לא תופסת, כי ``change`` שינה את הפתק בין הקריאה לכתיבה — כמו בקשה מקבילה."""
    coll = client.db.sticky_notes
    real = coll.find_one_and_update

    def racing(query, update, projection=None, return_document=None):
        change(coll)
        return real(query, update, projection=projection, return_document=return_document)

    monkeypatch.setattr(coll, "find_one_and_update", racing)


def test_a_note_pinned_between_the_read_and_the_write_is_already_pinned(client, monkeypatch):
    client.db.sticky_notes.docs.append(_board_note())
    _write_lost_to(client, monkeypatch, lambda coll: coll.docs[0].__setitem__(FIELD, NOW))

    res = _pin(client)

    assert res.status_code == 200
    assert res.get_json()["already_pinned"] is True


def test_a_note_archived_between_the_read_and_the_write_is_refused(client, monkeypatch):
    client.db.sticky_notes.docs.append(_board_note())

    def archive(coll):
        doc = coll.docs[0]
        doc.pop("board_id")
        doc["archived_at"] = NOW

    _write_lost_to(client, monkeypatch, archive)

    res = _pin(client)

    assert res.status_code == 409 and res.get_json()["error"] == "note_archived"


def test_a_note_deleted_between_the_read_and_the_write_is_404(client, monkeypatch):
    client.db.sticky_notes.docs.append(_board_note())
    _write_lost_to(client, monkeypatch, lambda coll: coll.docs.clear())

    assert _pin(client).status_code == 404


def test_unpinning_removes_the_field_and_keeps_the_note_on_its_board(client):
    coll = client.db.sticky_notes
    coll.docs.append(_board_note(**{FIELD: NOW}))

    res = client.delete(f"/api/sticky-notes/note/{OID}/files-page-pin")

    assert res.status_code == 200
    assert res.get_json() == {"ok": True, "already_unpinned": False, FIELD: None}
    assert FIELD not in coll.docs[0]
    assert coll.docs[0]["board_id"] == "board-1" and coll.docs[0]["updated_at"] == NOW
    [(_, query, update)] = _calls(coll, "find_one_and_update")
    assert query[FIELD] == {"$exists": True}
    assert update == {"$unset": {FIELD: ""}}


def test_unpinning_a_note_that_is_not_pinned_is_ok(client):
    client.db.sticky_notes.docs.append(_board_note())

    res = client.delete(f"/api/sticky-notes/note/{OID}/files-page-pin")

    assert res.status_code == 200 and res.get_json()["already_unpinned"] is True


def test_unpinning_a_note_that_does_not_exist_is_404(client):
    assert client.delete(f"/api/sticky-notes/note/{OID}/files-page-pin").status_code == 404


def test_the_list_is_in_pin_order_with_labels_and_only_active_pinned_notes(client):
    coll = client.db.sticky_notes
    coll.docs.append(_pinned(2))
    coll.docs.append(_pinned(0))
    # בלי שם — התווית היא השורה הראשונה של התוכן (``note_label``)
    coll.docs.append(_board_note(oid="c" * 24, content="\n  שורה   ראשונה \nשנייה", **{FIELD: NOW + dt.timedelta(minutes=1)}))
    coll.docs.append(_board_note(oid="d" * 24))                                   # לא נעוץ
    coll.docs.append({"_id": "e" * 24, "user_id": USER, "archived_at": NOW, FIELD: NOW})   # בארכיון

    res = client.get("/api/sticky-notes/files-page")
    body = res.get_json()

    assert res.status_code == 200, body
    assert [n["label"] for n in body["notes"]] == ["נעוץ 0", "שורה ראשונה", "נעוץ 2"]
    assert body["count"] == 3 and body["max"] == 4
    assert set(body["notes"][0]) == {"id", "label", "color", "color_id", FIELD}
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", body["notes"][0]["color"])
    [(_, query, projection)] = _calls(coll, "find")
    assert query == snt.files_page_pinned_filter(USER)
    assert set(snt.NOTE_LABEL_FIELDS) <= set(projection)


def test_a_list_that_failed_is_500_not_an_empty_list(client):
    client.db.sticky_notes.find_fails = True

    res = client.get("/api/sticky-notes/files-page")

    assert res.status_code == 500


def test_one_pinned_note_is_returned_whole_and_others_are_404(client):
    coll = client.db.sticky_notes
    coll.docs.append(_board_note(**{FIELD: NOW}))
    coll.docs.append(_board_note(oid="b" * 24))

    res = client.get(f"/api/sticky-notes/files-page/{OID}")
    body = res.get_json()

    assert res.status_code == 200, body
    assert body["note"]["id"] == OID and body["note"]["content"] == "# כותרת\nגוף"
    assert body["note"][FIELD] == NOW.isoformat()
    assert client.get(f"/api/sticky-notes/files-page/{'b' * 24}").status_code == 404
    assert client.get("/api/sticky-notes/files-page/zzz").status_code == 400


def test_archiving_a_pinned_note_unpins_it(client):
    coll = client.db.sticky_notes
    coll.docs.append(_board_note(title="שם", **{FIELD: NOW}))

    res = client.post(f"/api/sticky-notes/note/{OID}/archive", json={})

    assert res.status_code == 200, res.get_json()
    assert FIELD not in coll.docs[0]
    assert res.get_json()["note"][FIELD] is None
    assert client.get("/api/sticky-notes/files-page").get_json()["notes"] == []


def test_the_board_list_carries_the_pin_so_the_menu_knows_its_state(client):
    coll = client.db.sticky_notes
    client.db.note_boards.docs.append({"_id": "b" * 24, "user_id": USER, "name": "לוח"})
    coll.docs.append(_board_note(board_id="b" * 24, **{FIELD: NOW}))

    res = client.get(f"/api/sticky-notes/board/{'b' * 24}")
    body = res.get_json()

    assert res.status_code == 200, body
    assert body["notes"][0][FIELD] == NOW.isoformat()


def test_the_mcp_serializer_carries_the_pin():
    from mcp_server.backend import _as_note

    assert _as_note({"_id": "x", FIELD: NOW})[FIELD] == NOW.isoformat()
    assert _as_note({"_id": "x"})[FIELD] is None


# ---------------------------------------------------------------------------
# גיבוי ושחזור
# ---------------------------------------------------------------------------


class _PinCountFails(_Coll):
    """ספירת הנעוצים — ורק היא — נופלת בכשל מסד. ספירות התקרה של השחזור עוברות."""

    def count_documents(self, query):
        if FIELD in query:
            from pymongo.errors import PyMongoError

            raise PyMongoError("down")
        return super().count_documents(query)


class _PinCountBug(_Coll):
    """הספירה של הנעוצים זורקת חריגה שאינה כשל מסד — באג, ולא הסיכון שהמצב הוצהר בשבילו."""

    def count_documents(self, query):
        if FIELD in query:
            raise TypeError("bug")
        return super().count_documents(query)


def _restore(notes, sticky=None):
    from services.personal_backup_service import PersonalBackupService

    raw = SimpleNamespace(sticky_notes=sticky if sticky is not None else _Coll(), note_boards=_Coll())
    raw.note_boards.docs.append({"_id": "b" * 24, "user_id": USER, "name": "לוח עבודה", "is_default": True})
    service = PersonalBackupService(SimpleNamespace(db=raw))
    errors: list[str] = []
    count = service._restore_sticky_notes(USER, notes, errors)
    return raw, count, errors


def _backup_note(content, pinned_minutes=None):
    note = {"board_name": "לוח עבודה", "board_id": "old", "content": content, "color": "yellow"}
    if pinned_minutes is not None:
        note[FIELD] = (NOW + dt.timedelta(minutes=pinned_minutes)).isoformat()
    return note


def test_the_export_writes_the_pin_as_iso(monkeypatch):
    from services.personal_backup_service import PersonalBackupService

    sticky = _Coll([_board_note(**{FIELD: NOW})])
    raw = SimpleNamespace(sticky_notes=sticky, note_boards=_Coll([{"_id": "board-1", "user_id": USER, "name": "לוח"}]),
                          code_snippets=_Coll())
    exported = PersonalBackupService(SimpleNamespace(db=raw))._export_sticky_notes(USER)

    assert exported[0][FIELD] == NOW.isoformat()


def test_a_restored_board_note_comes_back_pinned_with_its_pin_time():
    raw, count, errors = _restore([_backup_note("א", pinned_minutes=3), _backup_note("ב")])

    assert count == 2 and errors == []
    by_content = {d["content"]: d for d in raw.sticky_notes.docs}
    assert by_content["א"][FIELD] == NOW + dt.timedelta(minutes=3)
    assert FIELD not in by_content["ב"]


def test_without_room_the_note_comes_back_unpinned_and_the_summary_says_so():
    sticky = _Coll([_pinned(i) for i in range(3)])
    raw, count, errors = _restore([_backup_note("מאוחר", pinned_minutes=9), _backup_note("מוקדם", pinned_minutes=1)], sticky)

    assert count == 2
    by_content = {d["content"]: d for d in raw.sticky_notes.docs}
    # מקום אחד נשאר — והוא של הראשון בתור לפי זמן הנעיצה, ולא לפי סדר הגיבוי
    assert by_content["מוקדם"][FIELD] == NOW + dt.timedelta(minutes=1)
    assert FIELD not in by_content["מאוחר"]
    # הפתק עצמו חזר — ללוח שלו
    assert by_content["מאוחר"]["board_id"] == "b" * 24
    assert len(errors) == 1 and "בלי הנעיצה" in errors[0]


class _CountsPinCounts(_Coll):
    """סופר כמה פעמים נספרו הנעוצים — ורק אותם; ספירות התקרה של השחזור אינן בספירה."""

    def __init__(self, docs):
        super().__init__(docs)
        self.pin_counts = 0

    def count_documents(self, query):
        if FIELD in query:
            self.pin_counts += 1
        return super().count_documents(query)


def test_once_the_files_page_is_full_the_remaining_pins_are_skipped_without_counting_each():
    """השחזור רק מוסיף נעיצות, ולכן כשהתקרה מלאה גם השאר לא ייכנסו. ספירה לכל נעיצה שנשארה הייתה
    שולחת, בגיבוי של אלפי פתקי לוח, אלפי ספירות אחרי שכבר ברור שאין מקום."""
    sticky = _CountsPinCounts([_pinned(i) for i in range(3)])
    raw, count, errors = _restore([_backup_note(f"פתק {i}", pinned_minutes=i + 1) for i in range(6)], sticky)

    assert count == 6
    assert sum(1 for d in raw.sticky_notes.docs if FIELD in d and d.get("content", "").startswith("פתק")) == 1
    # ספירה אחת שמצאה מקום, ואחת שמצאה מלא — ולא שש
    assert sticky.pin_counts == 2, sticky.pin_counts
    assert len(errors) == 1 and errors[0].startswith("5 פתקים שוחזרו בלי הנעיצה"), errors


def test_a_failed_pin_count_restores_the_notes_without_pins(caplog):
    raw, count, errors = _restore([_backup_note("א", pinned_minutes=1)], _PinCountFails())

    assert count == 1
    assert FIELD not in raw.sticky_notes.docs[0]
    assert len(errors) == 1 and "בלי הנעיצה" in errors[0]
    assert any("files-page pins failed" in r.getMessage() for r in caplog.records)


def test_a_bug_in_the_pin_count_is_not_reported_as_a_missing_room():
    """רק ``PyMongoError`` הוא "לא הצלחתי לספור" (R10). באג עולה ל-``except`` של השחזור, שאומר "שגיאה"."""
    raw, count, errors = _restore([_backup_note("א", pinned_minutes=1)], _PinCountBug())

    assert FIELD not in raw.sticky_notes.docs[0]
    assert errors == ["שגיאה בשחזור פתקיות"]


# ---------------------------------------------------------------------------
# עמוד הקבצים
# ---------------------------------------------------------------------------


class _EmptySnippets:
    def aggregate(self, _pipeline, **_kwargs):
        return []

    def distinct(self, _field, _query=None):
        return []


class _Users:
    def __init__(self, prefs, reads=None):
        self.prefs = prefs
        self.reads = reads

    def find_one(self, query, projection=None):
        if self.reads is not None:
            self.reads.append((query, projection))
        return {"user_id": 123, "ui_prefs": dict(self.prefs)}


class _RecordingCache:
    """קאש שזוכר את המפתחות — כדי לראות שהעדפה שמרונדרת ל-HTML היא חלק מהמפתח."""

    is_enabled = True

    def __init__(self):
        self.store: dict = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, *args, **kwargs):
        self.store[key] = value
        return True


@pytest.fixture
def files_page(monkeypatch):
    from webapp import app as webapp_app

    state = {"prefs": {}, "cache": _RecordingCache(), "user_reads": []}

    def _db():
        return SimpleNamespace(code_snippets=_EmptySnippets(), users=_Users(state["prefs"], state["user_reads"]))

    monkeypatch.setattr(webapp_app, "get_db", _db, raising=True)
    monkeypatch.setattr(webapp_app, "cache", state["cache"], raising=True)

    def render(*, admin=False):
        monkeypatch.setenv("ADMIN_USER_IDS", "123" if admin else "999")
        with webapp_app.app.test_client() as c:
            with c.session_transaction() as sess:
                sess["user_id"] = 123
                sess["user_data"] = {"id": 123, "first_name": "Test"}
            response = c.get("/files")
        assert response.status_code == 200
        return response.get_data(as_text=True)

    return render, state


def test_the_page_has_the_region_and_loads_what_the_opened_note_needs_for_every_user(files_page):
    render, _ = files_page
    html = render(admin=False)

    assert 'id="filesPageNotes"' in html and 'id="filesPageCards"' in html
    assert 'data-testid="files-notes-state-error"' in html
    scripts = re.findall(r'<script src="/static/([^"?]+)\?v=[^"]+"(?: defer)?>', html)
    for needed in ("js/admonition-icons.js", "js/utils/rtl-code.js", "js/utils/text-highlight.js", "js/toast.js",
                   "js/sticky-notes.js", "js/note-cards.js", "js/files-page-notes.js"):
        assert needed in scripts, f"{needed} לא נטען, או בלי ?v="
    # הסדר: התלויות, המנהל, רכיב הכרטיס, ואז הדבק של העמוד
    order = [scripts.index(n) for n in ("js/sticky-notes.js", "js/note-cards.js", "js/files-page-notes.js")]
    assert order == sorted(order)
    assert scripts.count("js/admonition-icons.js") == 1, "נטען פעמיים אצל אדמין?"
    for css in ("css/sticky-notes.css", "css/note-cards.css", "css/files-page-notes.css", "css/toast.css"):
        assert re.search(rf'href="/static/{re.escape(css)}\?v=', html), css


def test_an_admin_loads_each_script_once(files_page):
    render, _ = files_page
    html = render(admin=True)

    scripts = re.findall(r'<script src="/static/([^"?]+)\?v=[^"]+"(?: defer)?>', html)
    assert scripts.count("js/admonition-icons.js") == 1
    assert scripts.count("js/utils/rtl-code.js") == 1
    assert scripts.index("js/admonition-icons.js") < scripts.index("js/live-preview.js")


def test_the_opened_note_follows_the_boards_handwriting_setting(files_page):
    """הפתק הנעוץ הוא פתק לוח: ``note_font_surface = 'files'`` קורא את ההעדפה של הלוחות."""
    render, state = files_page
    state["prefs"]["note_fonts"] = {"board": True, "md": False, "repo": False}
    assert "window.STICKY_FONT_FROM_SETTINGS = true;" in render()
    state["prefs"]["note_fonts"] = {"board": False, "md": True, "repo": True}
    state["cache"].store.clear()
    assert "window.STICKY_FONT_FROM_SETTINGS = false;" in render()


def test_the_note_font_setting_is_part_of_the_page_cache_key(files_page):
    """ההעדפה מרונדרת לתוך ה-HTML שנשמר בקאש. בלי המפתח, שינוי שלה היה מוגש עם הדגל הישן עד שה-TTL פוקע."""
    render, state = files_page
    state["prefs"]["note_fonts"] = {"board": True, "md": False, "repo": False}
    first = render()
    state["prefs"]["note_fonts"] = {"board": False, "md": False, "repo": False}
    second = render()

    assert "window.STICKY_FONT_FROM_SETTINGS = true;" in first
    assert "window.STICKY_FONT_FROM_SETTINGS = false;" in second, "הוגש HTML מהקאש עם הדגל הישן"
    files_keys = [k for k in state["cache"].store if k.startswith("web:files:user:123:")]
    assert len(files_keys) == 2, files_keys


def test_the_cache_key_and_the_page_read_one_user_document(files_page):
    """המפתח והרינדור נבנים מאותו מסמך משתמש (``_request_user_doc``, בלי היטלה): שליפה נפרדת למפתח
    (``ETAG_USER_PROJECTION``) הייתה שאילתה שנייה בכל cache miss, ושינוי העדפה בין שתי השליפות היה שומר
    HTML של מסמך אחד תחת מפתח של אחר. (השליפה המוקרנת של התצוגה המצומצמת — ``_resolve_files_compact_view``
    — קדמה לשינוי, ואינה חלק מהבדיקה.)"""
    from webapp import app as webapp_app

    render, state = files_page
    render()
    whole = [q for q, projection in state["user_reads"] if projection is None]
    for_the_key = [q for q, projection in state["user_reads"] if projection == webapp_app.ETAG_USER_PROJECTION]
    assert (len(whole), for_the_key) == (1, []), state["user_reads"]


def test_a_database_in_its_cooldown_still_serves_the_cached_page(files_page, monkeypatch):
    """``get_db()`` מחזיר ``None`` בחלון הצינון שלו. המפתח נבנה אז מברירות המחדל — מה ש-``inject_globals``
    מרנדר באותו מצב — והעמוד שכבר בקאש יוצא ממנו, ולא נופל ב-500 על ``None.users``."""
    from webapp import app as webapp_app

    render, state = files_page
    first = render()
    monkeypatch.setattr(webapp_app, "get_db", lambda: None, raising=True)
    assert render() == first


# ---------------------------------------------------------------------------
# החוזה מול ה-JS
# ---------------------------------------------------------------------------


def test_the_field_name_in_the_browser_is_the_field_name_in_python():
    js = (ROOT / "webapp/static/js/sticky-notes.js").read_text(encoding="utf-8")
    match = re.search(r"const FILES_PAGE_PIN_FIELD = '([^']+)';", js)
    assert match, "FILES_PAGE_PIN_FIELD לא נמצא ב-sticky-notes.js"
    assert match.group(1) == FIELD


def test_the_answer_shapes_the_browser_reads_are_the_ones_the_server_sends(client):
    """``_afterFilesPagePinAnswer`` קורא ``files_page_pinned_at``, ``max``, ``pinned`` ו-``device_limited`` —
    בדיוק המפתחות שהראוט שולח."""
    js = (ROOT / "webapp/static/js/sticky-notes.js").read_text(encoding="utf-8")
    for key in ("answer.max", "answer.pinned", "answer.device_limited", "answer[FILES_PAGE_PIN_FIELD]",
                "'files_page_pins_full'", "note_quota_unknown", "note_archived", "not_a_board_note"):
        assert key in js, key
    coll = client.db.sticky_notes
    for i in range(4):
        coll.docs.append(_pinned(i))
    coll.docs.append(_board_note())
    assert set(json.loads(_pin(client).get_data())) == {"ok", "error", "max", "pinned", "device_limited"}

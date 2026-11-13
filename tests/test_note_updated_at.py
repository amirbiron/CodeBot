"""``updated_at`` של פתק זז רק כשהתוכן או השם באמת משתנים — בוובאפ (PUT ו-batch) וב-MCP.

עד נובמבר 2026 כל כתיבה לפתק קידמה את ``updated_at``: מזעור ופתיחה, הזזה, שינוי גודל, צבע, מצב
— וגם פתיחה אוטומטית של פתק ממוזער כשנכנסים אליו מקישור. "פתקים אחרונים" בדשבורד ממיין לפיו,
ולכן פתק שרק נפתח קפץ לראש הכרטיס. הכלל עכשיו במקום אחד, ``sticky_notes_target.drop_unchanged_edits``,
ושלושת הכותבים קוראים לו.

הבדיקות נעשות דרך הראוטים (``tests/_notes_mongo_fake.py``) ודרך ``ProductionBackend.update_note``,
ולא רק על הפונקציה הטהורה: כותב שלא קורא לה היה עובר בדיקה של הפונקציה בלבד.
"""

from __future__ import annotations

import datetime as dt

import pytest

flask = pytest.importorskip("flask")

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _notes_mongo_fake import USER, _Coll, make_client  # noqa: E402

import sticky_notes_target as snt  # noqa: E402

NOW = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.timezone.utc)
OID = "a" * 24
OTHER_COLOR = next(c for c in snt.NOTE_COLOR_ORDER if c != "yellow")


def _note(**extra):
    doc = {
        "_id": OID, "user_id": USER, "board_id": "board-1", "content": "גוף הפתק", "title": "שם",
        "color": "yellow", "mode": "surface", "is_minimized": True, "position_x": 10, "position_y": 20,
        "width": 300, "height": 240, "created_at": NOW, "updated_at": NOW,
    }
    doc.update(extra)
    return doc


@pytest.fixture
def client(monkeypatch):
    c = make_client(monkeypatch, flask)
    c.db.sticky_notes.docs.append(_note())
    writes = []
    real = c.db.sticky_notes.update_one

    def recording_update_one(query, update, upsert=False):
        writes.append(update)
        return real(query, update, upsert=upsert)

    monkeypatch.setattr(c.db.sticky_notes, "update_one", recording_update_one)
    c.writes = writes
    return c


def _stored(client):
    return client.db.sticky_notes.docs[0]


def _put(client, body):
    return client.put(f"/api/sticky-notes/note/{OID}", json=body)


def _batch(client, body):
    res = client.post("/api/sticky-notes/batch", json={"updates": [dict(body, id=OID)]})
    assert res.status_code == 200, res.get_json()
    (item,) = res.get_json()["results"]
    return item


#: עדכונים שאינם עריכה — כל אחד נשלח לבדו, ו-``updated_at`` נשאר.
NOT_EDITS = {
    "פתיחה ממזעור": ({"is_minimized": False}, "is_minimized", False),
    "הזזה": ({"position": {"x": 400, "y": 500}}, "position_x", 400),
    "שינוי גודל": ({"size": {"width": 500, "height": 400}}, "width", 500),
    "צבע": ({"color": OTHER_COLOR}, "color", OTHER_COLOR),
    "מצב ההצמדה": ({"mode": "screen"}, "mode", "screen"),
    "אותו תוכן, עם מזעור": ({"content": "גוף הפתק", "is_minimized": False}, "is_minimized", False),
    "אותו שם, עם מזעור": ({"title": "שם", "is_minimized": False}, "is_minimized", False),
}


# -- PUT --------------------------------------------------------------------------------


@pytest.mark.parametrize("body, field, value", NOT_EDITS.values(), ids=NOT_EDITS.keys())
def test_a_put_that_is_not_an_edit_keeps_updated_at(client, body, field, value):
    res = _put(client, body)

    assert res.status_code == 200, res.get_json()
    assert _stored(client)[field] == value, "השינוי עצמו נשמר"
    assert _stored(client)["updated_at"] == NOW
    assert res.get_json()["updated_at"] == NOW.isoformat(), "האסימון הוא הזמן ששמור, לא זמן חדש"


def test_a_put_with_unchanged_content_does_not_write_the_content_back(client):
    """תוכן ששווה למה ששמור יוצא מהעדכון — כדי לא לדרוס שינוי של כותב מקביל בתוכן שנקרא לפני רגע."""
    _put(client, {"content": "גוף הפתק", "is_minimized": False})

    (update,) = client.writes
    assert "content" not in update.get("$set", {}) and "updated_at" not in update.get("$set", {})


def test_a_put_that_changes_nothing_does_not_write(client):
    res = _put(client, {"content": "גוף הפתק"})

    assert res.status_code == 200 and res.get_json()["updated_at"] == NOW.isoformat()
    assert client.writes == []


@pytest.mark.parametrize("body, field, value", [
    ({"content": "גוף חדש"}, "content", "גוף חדש"),
    ({"title": "שם חדש"}, "title", "שם חדש"),
], ids=["תוכן", "שם"])
def test_a_put_that_edits_the_content_or_the_title_moves_updated_at(client, body, field, value):
    res = _put(client, body)

    stored = _stored(client)
    assert res.status_code == 200, res.get_json()
    assert stored[field] == value and stored["updated_at"] > NOW
    assert res.get_json()["updated_at"] == stored["updated_at"].isoformat()


def test_clearing_a_title_is_an_edit_only_when_there_was_one(client):
    res = _put(client, {"title": ""})
    assert res.status_code == 200 and "title" not in _stored(client)
    assert _stored(client)["updated_at"] > NOW

    _stored(client)["updated_at"] = NOW
    res = _put(client, {"title": ""})
    assert res.status_code == 200 and _stored(client)["updated_at"] == NOW


def test_a_stale_tab_still_gets_a_conflict_on_an_edit(client):
    """ההגנה מדריסה בין לשוניות נשארת: עריכה עם אסימון ישן מקבלת 409."""
    res = _put(client, {"content": "גוף חדש", "prev_updated_at": (NOW - dt.timedelta(minutes=1)).isoformat()})

    assert res.status_code == 409 and _stored(client)["content"] == "גוף הפתק"


# -- batch ------------------------------------------------------------------------------


@pytest.mark.parametrize("body, field, value", NOT_EDITS.values(), ids=NOT_EDITS.keys())
def test_a_batch_item_that_is_not_an_edit_keeps_updated_at(client, body, field, value):
    item = _batch(client, body)

    assert item["ok"] is True and item["updated_at"] == NOW.isoformat()
    assert _stored(client)[field] == value and _stored(client)["updated_at"] == NOW


def test_a_batch_item_that_changes_nothing_does_not_write(client):
    item = _batch(client, {"content": "גוף הפתק"})

    assert item["ok"] is True and item["updated_at"] == NOW.isoformat()
    assert client.writes == []


def test_a_batch_item_that_edits_the_content_moves_updated_at(client):
    item = _batch(client, {"content": "גוף חדש", "is_minimized": False})

    stored = _stored(client)
    assert stored["content"] == "גוף חדש" and stored["updated_at"] > NOW
    assert item["updated_at"] == stored["updated_at"].isoformat()


# -- MCP --------------------------------------------------------------------------------


@pytest.fixture
def mcp():
    from bson import ObjectId

    from mcp_server.backend import ProductionBackend

    oid = ObjectId()
    coll = _Coll([_note(_id=oid)])
    backend = ProductionBackend.__new__(ProductionBackend)
    backend._notes_coll = lambda: coll
    # הצילום לפני דריסת תוכן נבדק במקום אחר; כאן רק זמן העדכון.
    backend._snapshot_note = lambda user_id, note: (True, None)
    return backend, coll, str(oid)


@pytest.mark.parametrize("fields", [{"color": OTHER_COLOR}, {"is_minimized": False}, {"line_start": 4}],
                         ids=["צבע", "מזעור", "שורה"])
def test_an_mcp_update_that_is_not_an_edit_keeps_updated_at(mcp, fields):
    backend, coll, oid = mcp

    answer = backend.update_note(USER, note_id=oid, fields=fields)

    assert answer["ok"] is True
    key, value = next(iter(fields.items()))
    assert coll.docs[0][key] == value and coll.docs[0]["updated_at"] == NOW


def test_an_mcp_update_with_the_same_content_does_not_write(mcp):
    backend, coll, oid = mcp

    answer = backend.update_note(USER, note_id=oid, fields={"content": "גוף הפתק"})

    assert answer["ok"] is True and answer["content_changed"] is False
    assert [c for c in coll.calls if c[0] == "find_one_and_update"] == []


def test_an_mcp_update_that_edits_the_content_moves_updated_at(mcp):
    backend, coll, oid = mcp

    answer = backend.update_note(USER, note_id=oid, fields={"content": "גוף חדש"})

    assert answer["ok"] is True and answer["content_changed"] is False
    assert coll.docs[0]["content"] == "גוף חדש" and coll.docs[0]["updated_at"] > NOW


# -- הכלל עצמו --------------------------------------------------------------------------


def test_drop_unchanged_edits_keeps_what_is_not_an_edit_and_reports_what_is():
    stored = {"content": "א", "title": "שם", "color": "yellow"}

    same = snt.drop_unchanged_edits(stored, {"content": "א", "title": "שם", "color": "green"})
    assert same == (({"color": "green"}), {}, ())

    changed = snt.drop_unchanged_edits(stored, {"content": "ב", "color": "yellow"})
    assert changed.set_fields == {"content": "ב", "color": "yellow"} and changed.edited == ("content",)

    cleared = snt.drop_unchanged_edits(stored, {}, {"title": ""})
    assert cleared.unset_fields == {"title": ""} and cleared.edited == ("title",)

    nothing_to_clear = snt.drop_unchanged_edits({"content": "א"}, {}, {"title": ""})
    assert nothing_to_clear.unset_fields == {"title": ""} and nothing_to_clear.edited == ()

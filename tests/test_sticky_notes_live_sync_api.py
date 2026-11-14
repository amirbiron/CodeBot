"""מה שהשרת נותן לעדכון בזמן אמת של הפתקים: ``?versions=1``, ``GET /note/<id>``, ואסימון ששווה למה שנשמר.

הלקוח (``webapp/static/js/sticky-notes.js``) דוגם כל כמה שניות את המזהים והאסימונים של הפתקים במשטח,
ומושך במלואו רק פתק שהשתנה. ההשוואה היא **במחרוזת** — האסימון שבתשובת הכתיבה מול האסימון שבדגימה —
ולכן הבדיקות כאן מוודאות שתי הבטחות: שהדגימה קלה ונאמנה לרשימה, ושכל דלת שמחזירה אסימון מחזירה בדיוק
את מה שהמסד יחזיר עליו אחר כך.

הדמה (``tests/_notes_mongo_fake.py``) אינה מחקה את החיתוך של ``bson`` לאלפית שנייה, ולכן הבדיקה על
האסימון נשענת על המיקרו-שניות של מה שנכתב, ובנוסף על סבב אמיתי דרך ``bson`` המותקן.
"""

from __future__ import annotations

import datetime as dt

import pytest

flask = pytest.importorskip("flask")

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _notes_mongo_fake import OTHER_USER, USER, make_client  # noqa: E402

NOW = dt.datetime(2026, 11, 1, 12, 0, 0, 123000, tzinfo=dt.timezone.utc)
BOARD = "b" * 24
N1, N2, N3, FOREIGN, ARCHIVED = ("1" * 24, "2" * 24, "3" * 24, "4" * 24, "5" * 24)


def _note(note_id, **extra):
    doc = {
        "_id": note_id, "user_id": USER, "board_id": BOARD, "content": "גוף ארוך " * 50, "title": "",
        "color": "yellow", "mode": "surface", "position_x": 10, "position_y": 20, "width": 300,
        "height": 240, "created_at": NOW, "updated_at": NOW,
    }
    doc.update(extra)
    return doc


@pytest.fixture
def client(monkeypatch):
    c = make_client(monkeypatch, flask)
    c.db.note_boards.docs.append({"_id": BOARD, "user_id": USER, "name": "לוח"})
    c.db.sticky_notes.docs.extend([
        _note(N1),
        _note(N2, color="blue", updated_at=NOW + dt.timedelta(seconds=5)),
        _note(FOREIGN, user_id=OTHER_USER),
        # העברה לארכיון מוחקת את שדות היעד (``archive_note_update``), ולכן אין לו ``board_id``.
        _note(ARCHIVED, board_id=None, archived_at=NOW),
    ])
    return c


def test_board_versions_carry_id_token_and_color_and_no_body(client):
    res = client.get(f"/api/sticky-notes/board/{BOARD}?versions=1")
    assert res.status_code == 200
    assert res.headers.get("Cache-Control") == "no-store"
    body = res.get_json()
    assert body["ok"] is True
    by_id = {n["id"]: n for n in body["notes"]}
    assert set(by_id) == {N1, N2}
    for note in body["notes"]:
        assert set(note) == {"id", "updated_at", "color"}
    # הדגימה שולפת רק את שלושת השדות — הגוף לא עובר ברשת ולא נקרא מהמסד.
    (find_call,) = [c for c in client.db.sticky_notes.calls if c[0] == "find"]
    assert find_call[2] == {"_id": 1, "updated_at": 1, "color": 1}, find_call[2]


def test_board_versions_list_exactly_what_the_full_list_shows_with_the_same_strings(client):
    full = client.get(f"/api/sticky-notes/board/{BOARD}").get_json()["notes"]
    versions = client.get(f"/api/sticky-notes/board/{BOARD}?versions=1").get_json()["notes"]
    assert all(set(n) == {"id", "updated_at", "color"} for n in versions), "קיבלתי את הרשימה המלאה ולא דגימה"
    assert {n["id"]: (n["updated_at"], n["color"]) for n in full} == {
        n["id"]: (n["updated_at"], n["color"]) for n in versions
    }


def test_versions_of_a_board_that_is_not_yours_is_404(client):
    client.db.note_boards.docs[0]["user_id"] = OTHER_USER
    res = client.get(f"/api/sticky-notes/board/{BOARD}?versions=1")
    assert res.status_code == 404


def test_file_versions_do_not_write(client):
    """הרשימה המלאה של קובץ משלימה ``scope_id`` לפתקים ישנים; הדגימה, שרצה כל כמה שניות, אינה כותבת."""
    from _notes_mongo_fake import _Coll

    # קובץ שהשם שלו נמצא — ולכן לרשימה המלאה יש ``scope_id`` להשלים בפתק הישן שבלעדיו.
    client.db.code_snippets = _Coll([{"_id": "f" * 24, "user_id": USER, "file_name": "a.md"}])
    client.db.sticky_notes.docs.append(_note(N3, board_id=None, file_id="f" * 24))
    full = client.get(f"/api/sticky-notes/{'f' * 24}")
    assert [c for c in client.db.sticky_notes.calls if c[0] == "update_many"], "בלי השלמה ברשימה המלאה הבדיקה אינה בודקת דבר"
    client.db.sticky_notes.calls.clear()
    client.db.sticky_notes.docs[-1].pop("scope_id", None)
    assert full.status_code == 200
    res = client.get(f"/api/sticky-notes/{'f' * 24}?versions=1")
    assert res.status_code == 200
    assert [n["id"] for n in res.get_json()["notes"]] == [N3]
    assert not [c for c in client.db.sticky_notes.calls if c[0] == "update_many"]


def test_repo_versions_use_the_repo_filter(client, monkeypatch):
    client.db.sticky_notes.docs.append(_note(N3, board_id=None, repo_name="CodeBot", repo_path="docs/a.md"))
    seen = []
    monkeypatch.setattr(client.api, "repo_file_exists", lambda *a, **k: seen.append(a) or True)
    res = client.get("/api/sticky-notes/repo/CodeBot/docs/a.md?versions=1")
    assert res.status_code == 200
    assert [n["id"] for n in res.get_json()["notes"]] == [N3]
    assert seen == [], "בדיקת המניפסט שייכת לטעינה המלאה, לא לדגימה"


def test_get_note_returns_the_full_note_of_its_owner(client):
    res = client.get(f"/api/sticky-notes/note/{N2}")
    assert res.status_code == 200
    assert res.headers.get("Cache-Control") == "no-store"
    note = res.get_json()["note"]
    assert note["id"] == N2
    assert note["content"] == "גוף ארוך " * 50
    assert note["updated_at"] == (NOW + dt.timedelta(seconds=5)).isoformat()


def test_get_note_returns_an_archived_note_so_the_client_can_tell_it_left(client):
    note = client.get(f"/api/sticky-notes/note/{ARCHIVED}").get_json()["note"]
    assert note["archived_at"] is not None


@pytest.mark.parametrize("note_id,status", [(FOREIGN, 404), ("6" * 24, 404), ("not-an-id", 400)])
def test_get_note_refuses_what_is_not_yours(client, note_id, status):
    res = client.get(f"/api/sticky-notes/note/{note_id}")
    assert res.status_code == status
    assert res.get_json()["ok"] is False


def _assert_stored_resolution(stamp):
    assert isinstance(stamp, dt.datetime)
    assert stamp.microsecond % 1000 == 0, "נכתב זמן ברזולוציה שהמסד אינו שומר"


def test_an_edit_answers_with_the_token_the_database_will_hold(client):
    res = client.put(f"/api/sticky-notes/note/{N1}", json={"content": "חדש", "prev_updated_at": NOW.isoformat()})
    assert res.status_code == 200
    stored = client.db.sticky_notes.docs[0]["updated_at"]
    _assert_stored_resolution(stored)
    assert res.get_json()["updated_at"] == client.api._note_token({"updated_at": stored})


def test_a_batch_edit_answers_with_the_token_the_database_will_hold(client):
    res = client.post("/api/sticky-notes/batch", json={"updates": [{"id": N1, "content": "חדש"}]})
    (item,) = res.get_json()["results"]
    stored = client.db.sticky_notes.docs[0]["updated_at"]
    _assert_stored_resolution(stored)
    assert item["updated_at"] == client.api._note_token({"updated_at": stored})


def test_a_new_board_note_answers_with_its_token(client):
    res = client.post(f"/api/sticky-notes/board/{BOARD}", json={"content": "", "position": {"x": 1, "y": 2}})
    assert res.status_code == 201, res.get_json()
    body = res.get_json()
    doc = next(d for d in client.db.sticky_notes.docs if d["_id"] == body["id"])
    _assert_stored_resolution(doc["updated_at"])
    assert doc["created_at"] == doc["updated_at"]
    assert body["updated_at"] == client.api._note_token(doc)


def test_the_stored_resolution_survives_a_real_bson_round_trip(client):
    """הבטחת ``_stored_now``: מה שנכתב חוזר מהמסד באותה מחרוזת. נמדד מול ``bson`` המותקן."""
    bson = pytest.importorskip("bson")
    from bson.codec_options import CodecOptions

    stamp = client.api._stored_now()
    back = bson.decode(bson.encode({"t": stamp}), codec_options=CodecOptions(tz_aware=True))["t"]
    assert back.isoformat() == stamp.isoformat()

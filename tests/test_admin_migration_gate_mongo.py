"""שער ה-dry-run בעמוד המיגרציה — מול **מונגו אמיתי** ודרך הראוט עצמו.

השער הקודם היה שדה מוסתר בטופס (``dry_run_seen=1``). שדה מוסתר הוא קלט
מהלקוח: כל POST של אדמין נשא אותו בלי שדבר הוצג, ולכן "ההחלה נפתחת רק
אחרי dry-run" לא היה נכון. השער עבר לסשן: ה-dry-run מנפיק אסימון אקראי
ושומר לצידו את מספר הקבצים המושפעים, וההחלה מאמתת את שניהם.

כל בדיקה כאן מאמתת גם שה-DB **לא השתנה** כשהשער דחה — סירוב שמדווח
בטקסט אבל כותב בכל זאת אינו שער.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from mongo_it import make_mongo_db_fixture, requires_mongo

pytestmark = requires_mongo

mongo_db = make_mongo_db_fixture("codebot_mig_gate_it_")

ADMIN_ID = 4242
ORIGIN = datetime(2024, 1, 1, tzinfo=timezone.utc)
LATER = ORIGIN + timedelta(days=5)

URL = "/admin/migrations/created-at"


@pytest.fixture
def client(mongo_db, monkeypatch):
    import webapp.app as W

    monkeypatch.setattr(W, "get_db", lambda: mongo_db)
    monkeypatch.setattr(W, "is_admin", lambda uid: int(uid) == ADMIN_ID)
    W.app.config["TESTING"] = True
    c = W.app.test_client()
    with c.session_transaction() as sess:
        sess["user_id"] = ADMIN_ID
        sess["user_data"] = {"id": ADMIN_ID, "first_name": "a", "username": "a"}
    return c


def _seed_broken(mongo_db, name: str, latest_created=LATER):
    """קובץ שגרסתו האחרונה נושאת "נוצר" מאוחר — מועמד לתיקון."""
    mongo_db.code_snippets.insert_many([
        {"user_id": 1, "file_name": name, "version": 1, "is_active": True,
         "created_at": ORIGIN, "updated_at": ORIGIN},
        {"user_id": 1, "file_name": name, "version": 2, "is_active": True,
         "created_at": latest_created, "updated_at": latest_created},
    ])


def _latest_created(mongo_db, name: str):
    return mongo_db.code_snippets.find_one({"file_name": name, "version": 2})["created_at"]


def _token(html: str):
    m = re.search(r'name="gate_token" value="([^"]+)"', html)
    return m.group(1) if m else None


def _text(resp) -> str:
    return resp.get_data(as_text=True)


def test_apply_without_dry_run_is_refused_and_writes_nothing(client, mongo_db):
    _seed_broken(mongo_db, "x.py")
    body = _text(client.post(URL, data={"action": "apply"}))
    assert "יש להריץ dry-run" in body
    assert _latest_created(mongo_db, "x.py") == LATER, "נכתב למרות הסירוב"


def test_forged_hidden_field_does_not_open_the_gate(client, mongo_db):
    """‏``dry_run_seen=1`` — השדה של הגרסה הקודמת — כבר לא פותח כלום."""
    _seed_broken(mongo_db, "x.py")
    body = _text(client.post(URL, data={"action": "apply", "dry_run_seen": "1"}))
    assert "יש להריץ dry-run" in body
    assert _latest_created(mongo_db, "x.py") == LATER


def test_forged_token_does_not_open_the_gate(client, mongo_db):
    _seed_broken(mongo_db, "x.py")
    client.post(URL, data={"action": "dry_run"})
    body = _text(client.post(URL, data={"action": "apply", "gate_token": "z" * 32}))
    assert "יש להריץ dry-run" in body
    assert _latest_created(mongo_db, "x.py") == LATER


def test_gate_refuses_when_the_affected_set_changed_since_the_dry_run(client, mongo_db):
    """מה שאושר חייב להיות מה שיוחל — אחרת סירוב ובקשה להריץ מחדש."""
    _seed_broken(mongo_db, "x.py")
    token = _token(_text(client.post(URL, data={"action": "dry_run"})))
    assert token

    _seed_broken(mongo_db, "y.py")  # קובץ שבור נוסף אחרי ההצגה
    body = _text(client.post(URL, data={"action": "apply", "gate_token": token}))
    assert "השתנתה מאז ה-dry-run" in body
    assert _latest_created(mongo_db, "x.py") == LATER
    assert _latest_created(mongo_db, "y.py") == LATER


def test_dry_run_then_apply_migrates_and_consumes_the_token(client, mongo_db):
    _seed_broken(mongo_db, "x.py")
    dry = _text(client.post(URL, data={"action": "dry_run"}))
    token = _token(dry)
    assert token and 'value="apply"' in dry
    assert _latest_created(mongo_db, "x.py") == LATER, "dry-run כתב — הוא אמור לקרוא בלבד"

    body = _text(client.post(URL, data={"action": "apply", "gate_token": token}))
    assert "האימות בקריאה חוזרת עבר" in body
    assert _latest_created(mongo_db, "x.py") == ORIGIN

    # האסימון נצרך: הרצה חוזרת עם אותו אסימון נדחית
    again = _text(client.post(URL, data={"action": "apply", "gate_token": token}))
    assert "יש להריץ dry-run" in again


def test_get_does_not_offer_apply_before_a_dry_run(client, mongo_db):
    _seed_broken(mongo_db, "x.py")
    body = _text(client.get(URL))
    assert 'value="apply"' not in body

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


def test_dry_run_then_apply_migrates_and_clears_the_token_from_the_session(client, mongo_db):
    _seed_broken(mongo_db, "x.py")
    dry = _text(client.post(URL, data={"action": "dry_run"}))
    token = _token(dry)
    assert token and 'value="apply"' in dry
    assert _latest_created(mongo_db, "x.py") == LATER, "dry-run כתב — הוא אמור לקרוא בלבד"

    body = _text(client.post(URL, data={"action": "apply", "gate_token": token}))
    assert "האימות בקריאה חוזרת עבר" in body
    assert _latest_created(mongo_db, "x.py") == ORIGIN

    # האסימון נוקה מהסשן, ולכן **לקוח שממשיך עם העוגייה המעודכנת** נדחה.
    # זו אינה חד-פעמיות: עותק ישן של העוגייה עדיין יעבור — ראו הבדיקה
    # המקבילית בהמשך, שמודדת את זה במפורש.
    again = _text(client.post(URL, data={"action": "apply", "gate_token": token}))
    assert "יש להריץ dry-run" in again


def test_get_does_not_offer_apply_before_a_dry_run(client, mongo_db):
    _seed_broken(mongo_db, "x.py")
    body = _text(client.get(URL))
    assert 'value="apply"' not in body


def test_concurrent_applies_never_corrupt_the_data(client, mongo_db):
    """שתי בקשות מקבילות עם אותו אסימון — הנתונים נכונים בכל תזמון.

    ‏``TESTING-PATTERNS`` T1(d): תכונת "חד-פעמי" נבדקת במקביל, לא ברצף.
    ההרצה המקבילית גילתה שני דברים שהבדיקה הסדרתית הסתירה:

    1. **השער אינו נעילה.** הסשן הוא עוגייה חתומה, ולכן השרת אינו יכול
       לבטל עותק שכבר בידי הלקוח. נמדד: שתי בקשות מקבילות התקבלו שתיהן.
    2. **התוצאה תלוית-תזמון.** לפעמים בדיקת החתימה מספיקה לתפוס את
       השנייה (היא מודדת ``count_affected`` מחדש, ואם הראשונה כבר סיימה
       המספר השתנה), ולפעמים לא. מדדתי את שני המצבים על אותו קוד.

    לכן הבדיקה אינה קובעת כמה בקשות התקבלו — קביעה כזו הייתה flaky
    מעצם היותה תלוית-תזמון. היא קובעת את מה שנכון תמיד: **הנתונים
    נכונים, וההחלה אינה זוחלת בהרצה חוזרת**, כי ``apply`` מחשב את
    קבוצת המושפעים מחדש בכל קריאה.

    השער נשאר תהליכי ולא נעילה **במכוון**: נעילה אמיתית דורשת מצב בצד
    השרת, וההגנה האמיתית — אידמפוטנטיות — כבר קיימת ונבדקת.
    """
    import threading

    for i in range(4):
        _seed_broken(mongo_db, f"c{i}.py")

    token = _token(_text(client.post(URL, data={"action": "dry_run"})))
    assert token

    import webapp.app as W

    def _twin():
        """לקוח נפרד שנושא עותק של אותה עוגיית סשן — כמו לשונית שנייה."""
        twin = W.app.test_client()
        for cookie in client._cookies.values():
            twin.set_cookie(cookie.key, cookie.value)
        return twin

    bodies = {}
    start = threading.Barrier(2)

    def run(idx):
        c = _twin()
        start.wait()
        bodies[idx] = _text(c.post(URL, data={"action": "apply", "gate_token": token}))

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # אף בקשה לא קרסה, ואף אחת לא נדחתה בטענה שלא רץ dry-run.
    assert len(bodies) == 2
    for body in bodies.values():
        assert "יש להריץ dry-run" not in body

    # הקביעה שנכונה בכל תזמון: המיגרציה הושלמה והנתונים נכונים.
    for i in range(4):
        assert _latest_created(mongo_db, f"c{i}.py") == ORIGIN

    from services import created_at_migration as mig

    assert mig.count_affected(mongo_db) == 0, "נשארו קבצים לא מתוקנים"

    # וההיסטוריה לא נפגעה: גרסה 1 שומרת על התאריך שלה.
    for i in range(4):
        v1 = mongo_db.code_snippets.find_one({"file_name": f"c{i}.py", "version": 1})
        assert v1["created_at"] == ORIGIN

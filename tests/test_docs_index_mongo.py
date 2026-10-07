"""ה-lease ומעבר שלם של אינדקס התיעוד — מול **מונגו אמיתי**, ולא מול דמה.

``test_docs_index_service.py`` בודק את ההחלטות של המעבר מול ``_fake_mongo``, שמחזיק מנעול על כל
עדכון. מה שרק שרת עונה עליו הוא אם ``find_one_and_update`` ו-``update_one`` עם תנאי באמת מבטיחים
את מה שה-lease נשען עליו כשכמה threads מתחרים: מריץ אחד לוקח אותו, ובקשה שנכנסת ברגע השחרור לא
הולכת לאיבוד. לכן הן כאן, עם threads אמיתיים.

מתי הן רצות: כש-``NOTE_FONTS_TEST_MONGO_URI``, או ``MONGODB_URL`` כשהוא ריק, מצביע לשרת נגיש. כשאין
שם שרת הן מדלגות; כשיש שרת והחיבור נכשל מסיבה אחרת — אימות, כתובת — הן נכשלות. ראו ``mongo_client``.
הרצה מקומית::

    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017/?directConnection=true' \\
        python -m pytest tests/test_docs_index_mongo.py

**בטיחות מחיקה:** כל בדיקה עובדת על מסד עם שם ייחודי משלה, וה-teardown מוחק רק מסד שמתחיל
בתחילית שלמטה.
"""

from __future__ import annotations

import os
import random
import threading
import time
import uuid
from datetime import timezone

import pytest

pymongo = pytest.importorskip("pymongo")

from _docs_index_harness import SHA_A, fill, make_world, run_request  # noqa: E402
from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

from services import docs_index_service as svc  # noqa: E402
from services import docs_search_contract as contract  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_docs_index_it_"

_MONGO_URL = (
    os.environ.get("NOTE_FONTS_TEST_MONGO_URI") or os.environ.get("MONGODB_URL") or ""
).strip()

#: הדילוג ברמת המודול נשען על ה-ENV בלבד ואינו נוגע ברשת; הנגישות נבדקת ב-``mongo_client``.
pytestmark = pytest.mark.skipif(
    not _MONGO_URL,
    reason="דורש NOTE_FONTS_TEST_MONGO_URI או MONGODB_URL",
)


@pytest.fixture(scope="module")
def mongo_client():
    """לקוח מחובר, או דילוג — **רק** כשאין שרת בקצה השני.

    ``ServerSelectionTimeoutError`` הוא "אין שרת", וכך גם מארח שאינו נפתר. כל חריגה אחרת עולה
    ומכשילה. אותו כלל כמו ``mongo_client`` ב-``test_metrics_storage_flush_mongo.py``. סיבת הדילוג
    אינה מצטטת את החריגה: היא נגזרת מחיבור שהכתובת שלו יכולה לשאת סיסמה (K13). ``tz_aware`` — כמו
    הלקוחות של הוובאפ (``services/db_provider.py``).
    """
    client = pymongo.MongoClient(
        _MONGO_URL, serverSelectionTimeoutMS=2000, tz_aware=True, tzinfo=timezone.utc
    )
    try:
        client.admin.command("ping")
    except ServerSelectionTimeoutError:
        client.close()
        pytest.skip("אין שרת מונגו נגיש בכתובת שהוגדרה")
    except Exception:
        client.close()
        raise
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def db(mongo_client):
    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    try:
        yield mongo_client[name]
    finally:
        # מוחקים רק מסד שנוצר כאן — השם נבדק מול התחילית לפני המחיקה.
        assert name.startswith(_TEST_DB_PREFIX)
        mongo_client.drop_database(name)


@pytest.fixture
def world(monkeypatch, db):
    return make_world(monkeypatch, db)


def _request(trigger=svc.TRIGGER_MANUAL_CHECK):
    return {"trigger": trigger, "commit": None, "approved_fingerprint": None, "requested_by": None,
            "requested_at": None}


def test_one_of_many_concurrent_requests_takes_the_lease(world, monkeypatch):
    started = []
    lock = threading.Lock()

    def record(target):
        with lock:
            started.append(target)

    monkeypatch.setattr(svc, "_runner_factory", record)
    barrier = threading.Barrier(16)
    results = []

    def ask():
        barrier.wait()
        results.append(svc.request_pass(world.db, trigger=svc.TRIGGER_PUSH))

    threads = [threading.Thread(target=ask) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(results) == [svc.REQUEST_QUEUED] * 15 + [svc.REQUEST_STARTED]
    assert len(started) == 1


def test_a_request_racing_the_release_is_run_by_exactly_one_runner(db, monkeypatch):
    """הבקשה שנכנסת בזמן שהמריץ משחרר רצה פעם אחת בדיוק: או שהמריץ לוקח אותה, או שהיא נשארת
    ממתינה והשולח מחזיק ב-lease (והמריץ שלו ייקח אותה) — לא שניהם, ולא אף אחד. השולח יכול לקחת
    lease פנוי גם אחרי שהמריץ כבר הריץ את הבקשה שלו; אז אין לו מה להריץ, וזה תקין. 200 סבבים, כל
    אחד עם thread שמתחרה בשחרור.

    **ההשהיה האקראית (עם seed לכל סבב) היא מה שמפזר את הסבבים בין שני הענפים.** בלעדיה השולח הקדים
    את השחרור בכל 200 הסבבים, כלומר רק ענף אחד נבדק. עם 0–4 ms לפני הבקשה ו-0–1 ms בינה לבין
    הניסיון לקחת את ה-lease נמדדו 25 סבבים של השולח ו-175 של המריץ (7.10.2026, MongoDB 8.0.32
    מקומי). הסדר המסוכן — הבקשה נכנסת אחרי הלקיחה האחרונה של המריץ ולפני השחרור שלו — נבדק באופן
    דטרמיניסטי ב-``test_docs_index_service.py``; כאן נבדק שהאינווריאנט מחזיק מול שרת אמיתי."""
    ran = []
    monkeypatch.setattr(svc, "_run_guarded", lambda _db, holder, request: ran.append((holder, request["trigger"])))
    state = db[contract.STATE_COLLECTION]
    for round_number in range(200):
        state.delete_many({})
        ran.clear()
        svc._put_pending(db, _request())
        assert svc._take_lease(db, "runner")
        taken_by_sender = []
        rng = random.Random(round_number)

        def send():
            time.sleep(rng.random() * 0.004)
            svc._put_pending(db, _request(svc.TRIGGER_DEPLOY))
            time.sleep(rng.random() * 0.001)
            if svc._take_lease(db, "sender"):
                taken_by_sender.append(True)

        sender = threading.Thread(target=send)
        sender.start()
        svc._run_until_idle(db, "runner")
        sender.join(timeout=30)

        deploy_runs = [holder for holder, trigger in ran if trigger == svc.TRIGGER_DEPLOY]
        current = svc.read_state(db)
        pending = current["pending"]
        ran_by_runner = deploy_runs == ["runner"]
        # השולח מחזיק ב-lease והבקשה שלו ממתינה — המריץ שהוא מעלה ייקח אותה.
        waits_for_sender = (
            pending is not None and pending["trigger"] == svc.TRIGGER_DEPLOY and current["lease_holder"] == "sender"
        )
        observed = (round_number, deploy_runs, pending, current["lease_holder"])
        assert len(deploy_runs) <= 1, observed
        # פעם אחת בדיוק: או שהמריץ הריץ אותה, או שהיא ממתינה למריץ של השולח — לא שניהם, ולא אף אחד.
        assert ran_by_runner != waits_for_sender, observed
        if not taken_by_sender:
            assert current["lease_holder"] is None, observed


def test_a_full_pass_writes_what_it_verified(world):
    fill(world)

    state = svc.read_state(world.db)
    assert (state["indexed_source_commit"], state["chunk_count"], state["section_count"]) == (SHA_A, 4, 4)
    assert state["indexed_at"].tzinfo is not None
    chunks = list(world.db[contract.CHUNKS_COLLECTION].find({}, {contract.VECTOR_FIELD: 1}))
    assert len(chunks) == 4 and all(len(c[contract.VECTOR_FIELD]) == 4 for c in chunks)
    assert run_request(world, svc.TRIGGER_DEPLOY, commit=SHA_A)["status"] == svc.STATUS_UNCHANGED

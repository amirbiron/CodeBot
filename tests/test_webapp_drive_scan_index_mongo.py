"""האינדקס של הסריקה של גיבויי ה-Drive בוובאפ — מול **מונגו אמיתי**: ``explain`` על הפילטר שהסריקה שולחת.

``tests/test_webapp_drive_scan_index.py`` מוכיח שמסלול העלייה **מבקש** אינדקס על שדות הפילטר. מה שרק שרת עונה עליו הוא אם התכנון של השאילתה **בוחר** בו (``IXSCAN`` עם שם האינדקס) — ושבלעדיו זו סריקה מלאה (``COLLSCAN``), כלומר שהבדיקה יכולה להיכשל.

מתי הן רצות, ומה מדלג: כמו ב-``tests/test_recycle_bin_ttl_index_mongo.py`` — ``NOTE_FONTS_TEST_MONGO_URI``, או ``MONGODB_URL`` כשהוא ריק; דילוג **רק** על ``ServerSelectionTimeoutError``.

**בטיחות מחיקה:** כל בדיקה עובדת על מסד עם שם ייחודי משלה, וה-teardown מוחק רק מסד שמתחיל בתחילית שלמטה.
"""

from __future__ import annotations

import functools
import os
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

import drive_owner  # noqa: E402
from database.manager import DatabaseManager  # noqa: E402
from test_webapp_drive_scan_index import INDEX_NAME, requested_scan_index  # noqa: E402
from webapp.backup_scheduler import _drive_claim_filter  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_drive_scan_idx_it_"

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
    """לקוח מחובר, או דילוג — **רק** כשאין שרת בקצה השני (``ServerSelectionTimeoutError``, כולל מארח שאינו נפתר). כל חריגה אחרת — אימות, ``mongodb+srv://`` שאינו נפתר — עולה ומכשילה. סיבת הדילוג אינה מצטטת את החריגה: הכתובת יכולה לשאת סיסמה."""
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
def mongo_db(mongo_client):
    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    try:
        yield mongo_client[name]
    finally:
        # סורג בטיחות: מוחקים רק מסד שנוצר כאן
        if name.startswith(_TEST_DB_PREFIX):
            mongo_client.drop_database(name)


def _seed(db) -> str:
    """משתמשים בכל המצבים שהסריקה פוגשת: תזמון וובאפ שהגיע זמנו, תזמון וובאפ עתידי, תזמון כבוי, ותזמון של הבוט בלבד."""
    prefs = drive_owner.drive_fields(drive_owner.WEBAPP).prefs
    now = datetime.now(timezone.utc)
    past = (now - timedelta(hours=1)).isoformat()
    future = (now + timedelta(days=1)).isoformat()
    docs = [{"user_id": 1, prefs: {"schedule_key": "daily", "schedule_next_at": past}}]
    docs += [{"user_id": 100 + i, prefs: {"schedule_key": "weekly", "schedule_next_at": future}} for i in range(20)]
    docs += [{"user_id": 200 + i, prefs: {"schedule_key": "off", "schedule_next_at": None}} for i in range(20)]
    docs += [{"user_id": 300 + i, "drive_prefs": {"schedule": "daily"}} for i in range(20)]
    db.users.insert_many(docs)
    return now.isoformat()


def _winning_stages(plan: dict) -> list:
    """כל השלבים בתוכנית המנצחת, מלמעלה למטה, עם שם האינדקס כשיש."""
    stages = [(plan.get("stage"), plan.get("indexName"))]
    for key in ("inputStage", "queryPlan"):
        if isinstance(plan.get(key), dict):
            stages += _winning_stages(plan[key])
    for child in plan.get("inputStages") or []:
        stages += _winning_stages(child)
    return stages


def _explain_claim(db, now_iso: str) -> list:
    """``explain`` על אותה פקודה שהסריקה שולחת: ``findAndModify`` עם ``_drive_claim_filter``."""
    prefs = drive_owner.drive_fields(drive_owner.WEBAPP).prefs
    result = db.command(
        "explain",
        {
            "findAndModify": "users",
            "query": _drive_claim_filter(now_iso),
            "update": {"$set": {f"{prefs}.schedule_next_at": "sentinel"}},
        },
        verbosity="queryPlanner",
    )
    return _winning_stages(result["queryPlanner"]["winningPlan"])


def test_the_scan_uses_the_index_that_startup_creates_and_scans_the_whole_collection_without_it(mongo_db):
    now_iso = _seed(mongo_db)

    # בלי האינדקס — סריקה מלאה: מוכיח שהבדיקה שלמטה יכולה להיכשל
    assert ("COLLSCAN", None) in _explain_claim(mongo_db, now_iso)

    fake = types.SimpleNamespace(db=mongo_db)
    create = functools.partial(DatabaseManager.safe_create_index, fake)
    assert create("users", requested_scan_index(), name=INDEX_NAME) is True

    stages = _explain_claim(mongo_db, now_iso)
    assert ("IXSCAN", INDEX_NAME) in stages
    assert all(stage != "COLLSCAN" for stage, _ in stages)

"""כתיבת המדדים של ``monitoring/metrics_storage.py`` — מול **מונגו אמיתי**, ולא מול דמה.

הבדיקות ב-``test_metrics_storage_write_outcomes.py`` מוכיחות מה הכותב עושה עם כל
תשובה. מה שהן לא יכולות להוכיח הוא מה השרת עונה: שכפילות על ``_id`` חוזרת עם
``keyPattern`` שהוא ``{"_id": 1}`` — הסימן שעליו הכותב קובע "כבר שמור" — ושבסוף
התהליך כל מדד שמור במסד פעם אחת בדיוק. את אלה רק שרת עונה, ולכן הן כאן.

התרחיש הוא התקלה מהפרודקשן (6.10.2026): הכתיבה הגיעה לשרת ונכתבה, והתשובה לא
חזרה. ``_ReplyLostOnce`` מדמה רק את החלק הזה — הכתיבה עצמה אמיתית.

מתי הן רצות: כש-``NOTE_FONTS_TEST_MONGO_URI``, או ``MONGODB_URL`` כשהוא ריק,
מצביע לשרת נגיש. כשאין שם שרת הן מדלגות; כשיש שרת והחיבור נכשל מסיבה
אחרת — אימות, כתובת — הן נכשלות. ראו ``mongo_client``.

**בטיחות מחיקה:** כל בדיקה עובדת על מסד עם שם ייחודי משלה, וה-teardown מוחק
רק מסד שמתחיל בתחילית שלמטה.
"""

from __future__ import annotations

import os
import uuid
from datetime import timezone

import pytest

pymongo = pytest.importorskip("pymongo")

from _metrics_writer_harness import fresh_writer  # noqa: E402
from pymongo.errors import AutoReconnect, ServerSelectionTimeoutError  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_metrics_it_"

_MONGO_URL = (
    os.environ.get("NOTE_FONTS_TEST_MONGO_URI") or os.environ.get("MONGODB_URL") or ""
).strip()

#: הדילוג ברמת המודול נשען על ה-ENV בלבד ואינו נוגע ברשת: בדיקת נגישות כאן
#: הייתה פותחת חיבור בכל איסוף של pytest, גם בהרצה שאינה כוללת את הקובץ.
#: הנגישות נבדקת ב-``mongo_client``, כשהבדיקות באמת עומדות לרוץ.
pytestmark = pytest.mark.skipif(
    not _MONGO_URL,
    reason="דורש NOTE_FONTS_TEST_MONGO_URI או MONGODB_URL",
)


@pytest.fixture(scope="module")
def mongo_client():
    """לקוח מחובר, או דילוג — **רק** כשאין שרת בקצה השני.

    ``ServerSelectionTimeoutError`` הוא "אין שרת", וכך גם מארח שאינו נפתר. כל חריגה
    אחרת עולה ומכשילה: אימות שגוי (``OperationFailure``), ``mongodb+srv://`` שאינו
    נפתר (``ConfigurationError``). אותו כלל כמו ``mongo_client`` ב-
    ``test_recycle_bin_ttl_index_mongo.py``.

    סיבת הדילוג אינה מצטטת את החריגה: היא נגזרת מחיבור שהכתובת שלו יכולה לשאת
    סיסמה (K13).
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
def metrics_collection(mongo_client):
    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    try:
        yield mongo_client[name]["service_metrics"]
    finally:
        # מוחקים רק מסד שנוצר כאן — השם נבדק מול התחילית לפני המחיקה.
        assert name.startswith(_TEST_DB_PREFIX)
        mongo_client.drop_database(name)


class _ReplyLostOnce:
    """הכתיבה הראשונה מגיעה לשרת ונכתבת, והתשובה שלה לא חוזרת.

    זה מה שקרה ב-Atlas בהחלפת primary: pymongo זרק ``_OperationCancelled``, תת-מחלקה
    של ``AutoReconnect``, אחרי שהשרת כבר כתב. כאן נזרק ``AutoReconnect`` עצמו — הכותב
    מטפל בכל תת-העץ באותה צורה. כל קריאה אחרת עוברת לאוסף האמיתי כמו שהיא.
    """

    def __init__(self, collection):
        self._collection = collection
        self.attempts = 0

    def insert_many(self, documents, ordered=True):
        self.attempts += 1
        result = self._collection.insert_many(documents, ordered=ordered)
        if self.attempts == 1:
            raise AutoReconnect("connection closed")
        return result


def test_a_reply_lost_after_the_server_wrote_leaves_each_metric_stored_once(
    monkeypatch, metrics_collection
):
    collection = _ReplyLostOnce(metrics_collection)
    ms, events = fresh_writer(monkeypatch, collection)
    paths = [f"/api/route-{index}" for index in range(8)]
    for path in paths:
        ms.enqueue_request_metric(200, 0.01, extra={"method": "GET", "path": path, "handler": "h"})

    ms.flush(force=True)
    assert metrics_collection.count_documents({}) == len(paths), "השרת כתב"
    assert len(ms._buf) == len(paths), "התשובה אבדה — הבאצ' חוזר לתור"

    ms.flush(force=True)
    assert len(ms._buf) + len(ms._agg) == 0, "השרת ענה בכפילויות על _id — הכול כבר שמור"
    assert metrics_collection.count_documents({}) == len(paths), "כל מדד שמור פעם אחת"
    assert sorted(metrics_collection.distinct("path")) == sorted(paths)

    resolved = [event for event in events if event[0] == "metrics_db_batch_resolved"]
    assert len(resolved) == 1
    _, severity, fields = resolved[0]
    # ‏already_stored הוא הוכחה לשדה שהשרת מחזיר: הכותב סופר "כבר שמור" רק כש-
    # ``keyPattern`` הוא ``{"_id": 1}``.
    assert (severity, fields["already_stored"], fields["inserted"], fields["dropped"]) == (
        "info",
        len(paths),
        0,
        0,
    )

    ms.flush(force=True)
    assert collection.attempts == 2, "אין מה לשלוח"

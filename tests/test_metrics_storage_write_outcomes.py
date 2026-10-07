"""מה ``monitoring/metrics_storage.py`` עושה עם כל תוצאה של כתיבת באצ' מדדים.

הלולאה שהקובץ הזה נולד ממנה (6.10.2026, ``service_metrics`` בוובאפ): החלפת
primary ב-Atlas קטעה כתיבה של 23 מדדים **אחרי** שהשרת כבר כתב אותם
(``operation cancelled``). הכותב החזיר את כל הבאצ' לתור, וכל ניסיון מאז נענה
ב-E11000 על אותם ``_id`` — לכל תשובה הכותב הגיב שוב באותה החזרה לתור, בלי
הפסקה בין ניסיונות, ושורת הלוג של כל ניסיון הדפיסה את כל המסמכים.

הבדיקות כאן עוברות דרך אותו ממשק שהאפליקציה משתמשת בו —
``enqueue_request_metric`` ואז ``flush`` — ורק האוסף מוחלף בדמה (``_FakeServer``).
את מה שרק שרת אמיתי עונה בודק ``test_metrics_storage_flush_mongo.py``.
"""

from __future__ import annotations

import logging
import time
import types
import uuid

import pytest

pymongo = pytest.importorskip("pymongo")

import pymongo.errors as pymongo_errors  # noqa: E402
from _metrics_writer_harness import fresh_writer  # noqa: E402
from bson import ObjectId  # noqa: E402
from bson.errors import InvalidDocument  # noqa: E402

#: המרווח שה-``flush`` ממתין בין ניסיונות, בשניות (``METRICS_FLUSH_INTERVAL_SEC``).
_INTERVAL = 5

#: חמישה נתיבים שונים — חמישה מסמכי rollup בבאצ' אחד.
_PATHS = ("/api/snippets", "/api/snippets/languages", "/api/me", "/static/app.css", "/metrics")


class _Clock:
    """מחליף את ``time`` של המודול, כדי שהמרווח בין ניסיונות ייבדק בלי לחכות.

    מתחיל שעה אחרי עכשיו: ערך ההתחלה של חותמת הניסיון האחרון במודול הוא
    ``time.time()`` של רגע הייבוא, והבדיקות צריכות שהניסיון הראשון יהיה מותר.
    """

    def __init__(self) -> None:
        self.now = time.time() + 3600

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeServer:
    """אוסף מונגו מאחורי ``insert_many(..., ordered=False)``, כפי ש-pymongo 4.15.3 מציג אותו.

    כל קריאה צורכת צעד אחד מ-``plan``:

    - ``"write"`` — כותב כמו שרת: מסמך שה-``_id`` שלו כבר שמור נדחה בקוד 11000,
      מסמך שהנתיב שלו ב-``reject`` נדחה בקוד שנקבע שם, וכל השאר נשמרים. אם היו
      דחיות, ``BulkWriteError`` נזרק אחרי שכל המסמכים נוסו — כמו ב-``ordered=False``.
    - ``("lost_reply", exc)`` — כותב כמו ``"write"``, ואז זורק ``exc``: השרת כתב,
      והתשובה לא הגיעה.
    - ``("raise", exc)`` — זורק בלי לכתוב.
    - ``("write_concern_error", code)`` — כותב הכול, ומחזיר שגיאת write concern.

    ה-``details`` של ``BulkWriteError`` בנוי כמו ש-pymongo בונה אותו
    (``pymongo/bulk_shared.py``, ``_merge_command``: ``index`` ו-``op`` לכל שגיאה,
    ו-``nInserted``), ו-``keyPattern``/``keyValue`` הם מה שהשרת מחזיר על כפילות —
    כך הם הגיעו מ-Atlas בלוגים של הפרודקשן.

    ``driver_assigns_ids`` מחקה את ``gen()`` של ``insert_many``, שמוסיף ``_id`` למילון
    עצמו כשאין לו. בלעדיו הדמה כותבת מה שקיבלה, וכך אפשר לבדוק שה-``_id`` מגיע מהכותב.
    """

    def __init__(self, plan, *, reject=None, driver_assigns_ids=True):
        self.plan = list(plan)
        self.reject = dict(reject or {})
        self.driver_assigns_ids = driver_assigns_ids
        self.stored = {}
        #: לכל קריאה — ה-``_id`` של כל מסמך כפי שהגיע, לפני שה"דרייבר" נגע בו.
        self.calls = []

    def insert_many(self, documents, ordered=True):
        assert ordered is False, "הכותב נשען על כתיבה לא-מסודרת: כל מסמך מנוסה"
        documents = list(documents)
        self.calls.append([doc.get("_id") for doc in documents])
        if self.driver_assigns_ids:
            for doc in documents:
                if "_id" not in doc:
                    doc["_id"] = ObjectId()
        step = self.plan.pop(0) if self.plan else "write"
        if isinstance(step, tuple) and step[0] == "raise":
            raise step[1]

        write_errors = []
        inserted = 0
        for index, doc in enumerate(documents):
            doc_id = doc.get("_id")
            if doc_id is not None and doc_id in self.stored:
                write_errors.append(
                    {
                        "index": index,
                        "code": 11000,
                        "errmsg": (
                            "E11000 duplicate key error collection: code_keeper_bot.service_metrics"
                            f" index: _id_ dup key: {{ _id: {doc_id!r} }}"
                        ),
                        "keyPattern": {"_id": 1},
                        "keyValue": {"_id": doc_id},
                        "op": doc,
                    }
                )
                continue
            rejection = self.reject.get(doc.get("path"))
            if rejection is not None:
                code, key_pattern = rejection
                error = {
                    "index": index,
                    "code": code,
                    "errmsg": f"rejected: {doc.get('path')}",
                    "op": doc,
                }
                if key_pattern is not None:
                    error["keyPattern"] = key_pattern
                write_errors.append(error)
                continue
            # בלי ``_id`` — השרת מוסיף אחד בעצמו, ולכן אותו מילון שנשלח פעמיים נשמר פעמיים.
            self.stored[doc_id if doc_id is not None else ObjectId()] = dict(doc)
            inserted += 1

        if isinstance(step, tuple) and step[0] == "lost_reply":
            raise step[1]
        concern_errors = []
        if isinstance(step, tuple) and step[0] == "write_concern_error":
            concern_errors.append({"code": step[1], "errmsg": "waiting for replication timed out"})
        if write_errors or concern_errors:
            raise pymongo_errors.BulkWriteError(
                {
                    "writeErrors": write_errors,
                    "writeConcernErrors": concern_errors,
                    "nInserted": inserted,
                    "nUpserted": 0,
                    "nMatched": 0,
                    "nModified": 0,
                    "nRemoved": 0,
                    "upserted": [],
                }
            )
        return types.SimpleNamespace(
            inserted_ids=[doc.get("_id") for doc in documents], acknowledged=True
        )


def _writer(monkeypatch, server):
    """מודול טרי מחובר לדמה (``fresh_writer``), עם שעון שבשליטת הבדיקה."""
    monkeypatch.setenv("METRICS_FLUSH_INTERVAL_SEC", str(_INTERVAL))
    ms, events = fresh_writer(monkeypatch, server)
    clock = _Clock()
    monkeypatch.setattr(ms, "time", clock)
    return ms, events, clock


def _enqueue(ms, paths=_PATHS):
    for path in paths:
        ms.enqueue_request_metric(200, 0.01, extra={"method": "GET", "path": path, "handler": "h"})


def _pending(ms) -> int:
    return len(ms._buf) + len(ms._agg)


def _named(events, name):
    return [event for event in events if event[0] == name]


def test_after_a_lost_reply_the_retry_finds_the_batch_stored_and_the_queue_drains(monkeypatch):
    """התקלה מהפרודקשן, צעד אחר צעד: הכתיבה נכנסה, התשובה אבדה, הניסיון הבא נענה בכפילויות."""
    cancelled = pymongo_errors._OperationCancelled("operation cancelled")
    server = _FakeServer([("lost_reply", cancelled), "write"])
    ms, events, clock = _writer(monkeypatch, server)
    _enqueue(ms)

    ms.flush()
    assert len(server.stored) == len(_PATHS)
    # התוצאה לא ידועה לכותב, ולכן הבאצ' חוזר לתור כמו שהוא.
    assert _pending(ms) == len(_PATHS)

    clock.advance(_INTERVAL)
    ms.flush()
    assert _pending(ms) == 0, "כפילות על _id היא מסמך שכבר שמור — לא סיבה לנסות שוב"
    assert len(server.stored) == len(_PATHS), "כל מדד נשמר פעם אחת בדיוק"

    resolved = _named(events, "metrics_db_batch_resolved")
    assert len(resolved) == 1
    _, severity, fields = resolved[0]
    assert severity == "info"
    # כל שדות האירוע, ולא רק מה שהתרחיש הזה מזיז: שדה שנשמט, או שעבר לתוך שדה
    # אחר, שובר את מי שקורא את הלוג.
    assert fields == {"count": len(_PATHS), **_outcome(0, len(_PATHS), {})}

    clock.advance(_INTERVAL)
    ms.flush()
    assert len(server.calls) == 2, "התור ריק — אין מה לשלוח"


_OUTAGES = [
    pymongo_errors.AutoReconnect("connection closed"),
    pymongo_errors.NetworkTimeout("timed out"),
    pymongo_errors.NotPrimaryError("not primary"),
    pymongo_errors.ServerSelectionTimeoutError("No primary available for writes, Timeout: 2.0s"),
    pymongo_errors.WaitQueueTimeoutError("timed out waiting for a connection"),
    pymongo_errors._OperationCancelled("operation cancelled"),
    pymongo_errors.ExecutionTimeout("operation exceeded time limit", 50),
]


@pytest.mark.parametrize("outage", _OUTAGES, ids=lambda exc: type(exc).__name__)
def test_an_outage_requeues_the_batch_with_the_ids_it_was_sent_with(monkeypatch, outage):
    """תקלה שאחריה אי אפשר לדעת אם נכתב: אותו באצ', עם אותם ``_id`` — כך ניסיון חוזר לא כותב פעמיים.

    הדמה **אינה** מוסיפה ``_id`` בעצמה, ולכן ה-``_id`` חייב להגיע מהכותב, כבר בניסיון
    הראשון. בלעדיו הבטיחות של הניסיון החוזר תלויה בכך ש-pymongo משנה את המילון
    שהוא קיבל — וכל עותק בדרך היה כותב כל מדד פעמיים, בלי שום שגיאה.
    """
    server = _FakeServer([("raise", outage), "write"], driver_assigns_ids=False)
    ms, events, clock = _writer(monkeypatch, server)
    _enqueue(ms)

    ms.flush()
    assert _pending(ms) == len(_PATHS)
    first_ids = server.calls[0]
    assert all(doc_id is not None for doc_id in first_ids), "כל מסמך יוצא לניסיון הראשון עם _id"

    failed = _named(events, "metrics_db_batch_insert_error")
    assert len(failed) == 1
    _, severity, fields = failed[0]
    assert severity == "warn"
    assert fields["error_type"] == type(outage).__name__
    assert fields["count"] == len(_PATHS)

    clock.advance(_INTERVAL)
    ms.flush()
    assert server.calls[1] == first_ids
    assert _pending(ms) == 0
    assert len(server.stored) == len(_PATHS)


def test_after_a_failure_the_next_attempt_waits_for_the_interval(monkeypatch):
    """אחרי כשל — ניסיון אחד למרווח, ולא ניסיון לכל בקשה שמעירה את הכותב."""
    no_primary = pymongo_errors.ServerSelectionTimeoutError(
        "No primary available for writes, Timeout: 2.0s"
    )
    server = _FakeServer([("raise", no_primary), ("raise", no_primary), "write"])
    ms, _events, clock = _writer(monkeypatch, server)
    _enqueue(ms)

    ms.flush()
    assert len(server.calls) == 1

    # בקשה שמגיעה שנייה אחר כך מעירה את הכותב (``enqueue_request_metric`` ← ``_worker_event``).
    for _ in range(3):
        clock.advance(1)
        _enqueue(ms, paths=("/api/me",))
        ms.flush()
    assert len(server.calls) == 1, "אין ניסיון חוזר לפני שעבר המרווח"

    clock.advance(_INTERVAL)
    ms.flush()
    assert len(server.calls) == 2


def test_a_clean_write_needs_no_event_and_the_next_one_waits_for_the_interval(monkeypatch):
    """בקרה — המצב התקין, שהתיקון לא שינה: כתיבה מצליחה, בלי אירוע, ומרווח אחריה.

    הבדיקה הזו עוברת גם על הקוד שלפני התיקון, וזו הכוונה: היא מוודאת שהמרווח
    אחרי **הצלחה** נשאר כמו שהיה.
    """
    server = _FakeServer(["write", "write"])
    ms, events, clock = _writer(monkeypatch, server)
    _enqueue(ms)

    ms.flush()
    assert len(server.stored) == len(_PATHS)
    assert _pending(ms) == 0
    assert events == []

    clock.advance(1)
    _enqueue(ms, paths=("/api/me",))
    ms.flush()
    assert len(server.calls) == 1

    clock.advance(_INTERVAL)
    ms.flush()
    assert len(server.calls) == 2


def test_after_the_server_answers_a_batch_the_flush_moves_on_to_the_next(monkeypatch):
    """באצ' שהשרת ענה עליו — גם בכפילויות — הוא באצ' שהסתיים, וה-``flush`` ממשיך לבא אחריו.

    זה מה שמשחרר את התור אחרי תקלה: הבאצ' התקוע בראש התור כבר לא חוסם את מה
    שמאחוריו.
    """
    lost = pymongo_errors.AutoReconnect("connection closed")
    server = _FakeServer([("lost_reply", lost), "write", "write"])
    ms, _events, clock = _writer(monkeypatch, server)
    monkeypatch.setenv("METRICS_BATCH_SIZE", "2")
    _enqueue(ms, paths=_PATHS[:4])

    ms.flush()
    assert len(server.calls) == 1
    assert _pending(ms) == 4

    clock.advance(_INTERVAL)
    ms.flush()
    assert _pending(ms) == 0, "הבאצ' שנענה בכפילויות לא עצר את הבא אחריו"
    assert len(server.stored) == 4
    assert len(server.calls) == 3


def _outcome(inserted, already_stored, dropped_codes, write_concern_codes=()):
    """מה ``_bulk_write_outcome`` צריך להחזיר. ``dropped`` הוא סכום הקודים שנכתבו כאן ביד."""
    return {
        "inserted": inserted,
        "already_stored": already_stored,
        "dropped": sum(dropped_codes.values()),
        "dropped_codes": dropped_codes,
        "write_concern_codes": list(write_concern_codes),
    }


_UNREADABLE_REPLIES = [
    pytest.param(None, _outcome(0, 0, {"unknown": 3}), id="not-a-document"),
    pytest.param({"nInserted": "3"}, _outcome(0, 0, {"unknown": 3}), id="count-is-not-a-number"),
    pytest.param(
        {"nInserted": 1, "writeErrors": ["not-a-document", {"code": "E11000"}]},
        _outcome(1, 0, {"unknown": 2}),
        id="errors-without-a-usable-code",
    ),
    pytest.param(
        {"nInserted": 1, "writeErrors": [{"code": 11000, "keyPattern": {"_id": 1}}]},
        _outcome(1, 1, {"unknown": 1}),
        id="a-document-the-reply-skips",
    ),
    pytest.param(
        {"nInserted": 3, "writeErrors": [], "writeConcernErrors": [{"code": 64}, "not-a-document"]},
        _outcome(3, 0, {}, ["64", "unknown"]),
        id="concern-errors",
    ),
]


@pytest.mark.parametrize("details, expected", _UNREADABLE_REPLIES)
def test_a_reply_the_writer_cannot_read_counts_its_documents_as_dropped(details, expected):
    """תשובה שאי אפשר לקרוא — או שלא מזכירה מסמך — נספרת כ-``unknown`` שנזרק, ולא כ"נכתב".

    ‏``_bulk_write_outcome`` היא פונקציה טהורה, ולכן הקריאה הישירה היא הממשק שלה.
    באצ' של שלושה מסמכים בכל המקרים.
    """
    from monitoring.metrics_storage import _bulk_write_outcome

    assert _bulk_write_outcome(details, 3) == expected


def test_a_write_error_that_is_not_a_duplicate_drops_only_its_document(monkeypatch):
    """שגיאה קבועה על מסמך אחד: הוא נזרק ונספר לפי הקוד, והשאר נכתבים. שום דבר לא חוזר לתור."""
    server = _FakeServer(["write"], reject={"/api/me": (121, None)})
    ms, events, _clock = _writer(monkeypatch, server)
    _enqueue(ms)

    ms.flush()
    assert _pending(ms) == 0
    assert len(server.stored) == len(_PATHS) - 1

    resolved = _named(events, "metrics_db_batch_resolved")
    assert len(resolved) == 1
    _, severity, fields = resolved[0]
    assert severity == "warn"
    assert fields["inserted"] == len(_PATHS) - 1
    assert fields["already_stored"] == 0
    assert fields["dropped"] == 1
    assert fields["dropped_codes"] == {"121": 1}


def test_a_duplicate_on_another_unique_index_is_dropped_and_not_counted_as_stored(monkeypatch):
    """11000 הוא "כבר שמור" רק כשהכפילות על ``_id``. על אינדקס ייחודי אחר המסמך שלנו לא נכתב."""
    server = _FakeServer(["write"], reject={"/api/me": (11000, {"path": 1})})
    ms, events, _clock = _writer(monkeypatch, server)
    _enqueue(ms)

    ms.flush()
    assert _pending(ms) == 0

    _, severity, fields = _named(events, "metrics_db_batch_resolved")[0]
    assert severity == "warn"
    assert fields["already_stored"] == 0
    assert fields["dropped"] == 1
    assert fields["dropped_codes"] == {"11000": 1}


def test_a_write_concern_error_counts_the_batch_as_written_and_reports_the_code(monkeypatch):
    """הכול נכתב ל-primary והאישור על השכפול לא הגיע: לא חוזר לתור, והקוד בלוג."""
    server = _FakeServer([("write_concern_error", 64)])
    ms, events, _clock = _writer(monkeypatch, server)
    _enqueue(ms)

    ms.flush()
    assert _pending(ms) == 0
    assert len(server.stored) == len(_PATHS)

    _, severity, fields = _named(events, "metrics_db_batch_resolved")[0]
    assert severity == "warn"
    assert fields["inserted"] == len(_PATHS)
    assert fields["dropped"] == 0
    assert fields["write_concern_codes"] == ["64"]


@pytest.mark.parametrize(
    "error",
    [
        TypeError("documents must be a non-empty list"),
        pymongo_errors.OperationFailure("not authorized on code_keeper_bot to execute command", 13),
        InvalidDocument("cannot encode object"),
    ],
    ids=["bug", "library-error-that-is-not-an-outage", "bson-error"],
)
def test_an_error_that_is_not_an_outage_drops_the_batch_loudly(monkeypatch, caplog, error):
    """חריגה מחוץ לתת-העץ של התקלה — גם מתוך pymongo — אינה מקבלת את המצב של התקלה.

    ניסיון חוזר עליה הוא הלולאה עצמה: היא לא תשתנה בניסיון הבא. הבאצ' נזרק, עם
    אירוע משלו ברמת error ועם traceback, כי זה באג או תצורה ולא רשת.
    """
    server = _FakeServer([("raise", error)])
    ms, events, _clock = _writer(monkeypatch, server)
    _enqueue(ms)

    with caplog.at_level(logging.ERROR, logger="monitoring.metrics_storage"):
        ms.flush()

    assert _pending(ms) == 0, "לא חוזר לתור"
    assert _named(events, "metrics_db_batch_insert_error") == []
    dropped = _named(events, "metrics_db_batch_dropped")
    assert len(dropped) == 1
    _, severity, fields = dropped[0]
    assert severity == "error"
    assert fields["count"] == len(_PATHS)
    assert fields["error_type"] == type(error).__name__
    assert any(record.exc_info for record in caplog.records), "ה-traceback נרשם"


def test_a_failure_while_preparing_the_batch_drops_it_loudly_and_waits_for_the_interval(
    monkeypatch, caplog
):
    """כשל אחרי שהבאצ' נשלף מהתור ולפני הכתיבה — כאן ``ObjectId`` שלא נוצר — מסווג כמו כל חריגה שאינה תקלה.

    הבאצ' כבר מחוץ לתור, ולכן חריגה שעוקפת את הסיווג הייתה מאבדת אותו בלי אירוע,
    ובלי לקדם את חותמת הניסיון: כל בקשה הייתה מעירה את הכותב לשלוף ולאבד באצ' נוסף.
    """
    server = _FakeServer(["write"], driver_assigns_ids=False)
    ms, events, clock = _writer(monkeypatch, server)
    _enqueue(ms)

    def _unavailable():
        raise RuntimeError("ObjectId unavailable")

    monkeypatch.setattr("bson.ObjectId", _unavailable)
    with caplog.at_level(logging.ERROR, logger="monitoring.metrics_storage"):
        ms.flush()

    assert server.calls == [], "שום דבר לא נשלח"
    assert _pending(ms) == 0, "לא חוזר לתור"
    dropped = _named(events, "metrics_db_batch_dropped")
    assert [(severity, fields) for _, severity, fields in dropped] == [
        ("error", {"error_type": "RuntimeError", "count": len(_PATHS)})
    ]
    assert any(record.exc_info for record in caplog.records), "ה-traceback נרשם"

    # גם ניסיון שנכשל בהכנה הוא ניסיון: הבא אחריו ממתין למרווח.
    monkeypatch.setattr("bson.ObjectId", ObjectId)
    clock.advance(1)
    _enqueue(ms, paths=("/api/me",))
    ms.flush()
    assert server.calls == []

    clock.advance(_INTERVAL)
    ms.flush()
    assert len(server.calls) == 1
    assert _pending(ms) == 0


def test_the_log_carries_counts_and_codes_never_the_documents(monkeypatch):
    """pymongo מצרף לכל שגיאה את המסמך (``op``), ובו הנתיב — כולל טוקן של קישור שיתוף.

    השורה הישנה הדפיסה ``str(e)``, כלומר את כל המסמכים, בכל ניסיון. בשורה החדשה
    יש רק מספרים וקודים.
    """
    token = f"share-token-{uuid.uuid4().hex}"
    shared_path = f"/shared/{token}"
    server = _FakeServer(["write"], reject={shared_path: (121, None)})
    ms, events, _clock = _writer(monkeypatch, server)
    _enqueue(ms, paths=(shared_path, "/api/me"))

    ms.flush()

    assert events, "השגיאה דווחה"
    assert token not in repr(events)

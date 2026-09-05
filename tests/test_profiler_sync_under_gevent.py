"""בדיקות לשירות הפרופיילר אחרי הסרת שכבת ה-asyncio.

רקע: ה-WebApp רץ כ-Flask על WSGI עם ``worker_class=gevent`` ו-worker יחיד. gevent
מריץ את כל הבקשות של worker כגרינלטים **באותו OS thread**, אבל asyncio שומר את
מצב "הלולאה הרצה" ברמת ה-thread. לכן כשבקשה אחת הייתה בתוך ``run_until_complete``,
כל בקשה חופפת ראתה את הלולאה שלה כרצה ונפלה ב-500.

התיקון: השירות סינכרוני לגמרי, ואין יותר מעטפת שמריצה לולאה מתוך קוד סינכרוני.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys

import pytest

from services.query_profiler_service import (
    PersistentQueryProfilerService,
    QueryProfilerService,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(REPO_ROOT, "tests", "helpers", "gevent_profiler_probe.py")


class _StubCollection:
    """דמה של אוסף מונגו שסופרת מה נכתב אליה."""

    def __init__(self) -> None:
        self.documents: list[dict] = []

    def insert_one(self, document):
        self.documents.append(document)
        return None

    def find(self, query, sort=None, limit=None):
        return list(self.documents)


class _StubDB:
    def __init__(self) -> None:
        self.collection = _StubCollection()

    def __getitem__(self, name):
        return self.collection


class _StubManager:
    def __init__(self) -> None:
        self.db = _StubDB()


class TestProfilerServiceIsSynchronous:
    """גדר רגרסיה: שהשירות לא יחזור להיות אסינכרוני."""

    @pytest.mark.parametrize(
        "service_class", [QueryProfilerService, PersistentQueryProfilerService]
    )
    def test_no_coroutine_methods_remain(self, service_class):
        coroutine_methods = [
            name
            for name in dir(service_class)
            if not name.startswith("__")
            and inspect.iscoroutinefunction(getattr(service_class, name, None))
        ]
        assert coroutine_methods == [], (
            "השירות נצרך מראוטים סינכרוניים של Flask תחת gevent. מתודה אסינכרונית "
            f"מחזירה את הבאג: {coroutine_methods}"
        )

    def test_get_summary_async_is_gone(self):
        """``get_summary_async`` אוחדה לתוך ``get_summary``."""
        assert not hasattr(PersistentQueryProfilerService, "get_summary_async")
        assert not hasattr(QueryProfilerService, "get_summary_async")


class TestRecordSlowQueryPersists:
    def test_the_record_actually_reaches_the_collection(self):
        """אימות בקריאה חוזרת של המצב, לא בערך ההחזרה.

        המסלול הקודם תיזמן קורוטינה (``loop.create_task``); כשהלולאה שנראתה רצה
        הגיעה מגרינלט אחר ונסגרה מיד, הרשומה אבדה בלי חריגה ובלי לוג.
        """
        manager = _StubManager()
        service = PersistentQueryProfilerService(manager, slow_threshold_ms=100)

        service.record_slow_query_sync(
            collection="code_snippets",
            operation="find",
            query={"user_id": "u1"},
            execution_time_ms=1234.5,
        )

        stored = manager.db.collection.documents
        assert len(stored) == 1, "הרשומה לא נכתבה לאוסף"
        assert stored[0]["collection"] == "code_snippets"
        assert stored[0]["execution_time_ms"] == 1234.5
        # שם שדה הזמן הוא מה שאינדקס ה-TTL מסתמך עליו — ראה _create_profiler_indexes
        assert "timestamp" in stored[0]


@pytest.mark.timeout(180)
class TestConcurrentRequestsUnderGevent:
    """הבדיקה שמשחזרת את הבאג עצמו.

    חייבת לרוץ בתת-תהליך: ``conftest.py`` מכבה את ה-monkey patching של gevent
    בכל הסוויטה, ובלעדיו הבאג לא ניתן לשחזור בכלל.

    על הקוד שלפני התיקון אותה מדידה החזירה ``[200, 500, 500, 500, 500]`` עם
    ``RuntimeError: Cannot run the event loop while another loop is running``
    שלוש פעמים לכל נפילה — אחת לכל שכבת fallback.
    """

    def test_five_overlapping_requests_all_succeed(self):
        pytest.importorskip("gevent")
        pytest.importorskip("flask")

        completed = subprocess.run(
            [sys.executable, PROBE, "5"],
            capture_output=True,
            text=True,
            timeout=150,
            cwd=REPO_ROOT,
        )

        assert completed.returncode == 0, (
            f"הפרוב נכשל.\nstdout: {completed.stdout}\nstderr: {completed.stderr[-2000:]}"
        )
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        statuses = payload["statuses"]

        # הפרוב בונה את הסטאב לפי החוזה של השירות בעץ שהוא רץ עליו. אם מישהו
        # יחזיר ``async def`` לשירות, הסטאב יהפוך לאסינכרוני והראוט ייפול שוב —
        # אבל עדיף שהטסט יגיד את זה במפורש מאשר דרך 500 מבלבל.
        assert payload["service_is_async"] is False, (
            "השירות חזר להיות אסינכרוני — זה בדיוק הדפוס שהוסר."
        )

        assert statuses == [200] * 5, (
            "בקשות חופפות באותו worker של gevent חייבות כולן להצליח. "
            f"התקבל: {statuses}\nstderr: {completed.stderr[-2000:]}"
        )

"""``IsolatedJobQueue`` ו-``IsolatedUpdateApplication`` בלי ``observability``: הג'וב והעדכון רצים, רק בלי הקשר מבודד.

``main.py`` ממשיך לעבוד כש-``observability`` לא נטען (``_observability = None`` ופונקציות ריקות), ו"מערכת observability
לעולם לא מפילה את היישום" (``docs/observability/guidelines.md``). עד התיקון, שני העוטפים ייבאו את ``observability`` בכל
קריאה, בלי חלופה — ייבוא שנכשל היה מפיל כל עדכון וכל ג'וב לפני שה-handler שלהם רץ.

ייבוא שנכשל מדומה ב-``sys.modules["observability"] = None``: כך פייתון עצמו מסמן מודול שאסור לייבא, ו-``import`` זורק
``ImportError``. ``telegram`` כאן הוא ה-stubs של ``tests/_telegram_stubs.py``: ``JobQueue.job_callback`` מריץ את
``job.run``, ו-``process_update`` של מחלקת הבסיס מוחלף ברושם.
"""

from __future__ import annotations

import sys
import types

import pytest
import structlog

from services import telegram_observability_scope as scope


class _Job:
    """מה ש-``JobQueue.job_callback`` ו-``bind_job_context`` נוגעים בו בג'וב של PTB."""

    def __init__(self, ran: list) -> None:
        self.user_id = None
        self.chat_id = None
        self._ran = ran

        async def probe_job(_context) -> None:  # רק השם נקרא, ב-``_job_callback_name``
            return None

        self.callback = probe_job

    async def run(self, _application) -> None:
        self._ran.append(dict(structlog.contextvars.get_contextvars()))


@pytest.fixture
def observability_unavailable(monkeypatch):
    # ``_observability`` קורא את ``sys.modules`` לפני ההפניה מזמן הייבוא, ולכן ``None`` כאן הוא "הייבוא נכשל".
    monkeypatch.setitem(sys.modules, "observability", None)


@pytest.fixture
def recorded_base_process_update(monkeypatch):
    seen: list = []

    async def process_update(self, update) -> None:
        seen.append(dict(structlog.contextvars.get_contextvars()))

    base = scope.IsolatedUpdateApplication.__mro__[1]
    monkeypatch.setattr(base, "process_update", process_update, raising=False)
    return seen


@pytest.mark.asyncio
async def test_a_job_still_runs_without_observability(observability_unavailable):
    ran: list = []
    await scope.IsolatedJobQueue.job_callback(types.SimpleNamespace(application=object()), _Job(ran))
    assert len(ran) == 1, ran


@pytest.mark.asyncio
async def test_an_update_is_still_processed_without_observability(observability_unavailable, recorded_base_process_update):
    await scope.IsolatedUpdateApplication().process_update(object())
    assert len(recorded_base_process_update) == 1, recorded_base_process_update


@pytest.mark.asyncio
async def test_with_observability_the_job_and_the_update_run_in_their_own_context(recorded_base_process_update):
    """המצב התקין, באותה דרך: עם ``observability`` שני העוטפים כורכים הקשר משלהם — ומחזירים אחריהם את מה שהיה.

    ההשוואה היא ל-``before`` ולא להקשר ריק: ההקשר שהטסט מתחיל בו אינו בהכרח ריק. ``_correlation_bind`` ב-
    ``webapp/app.py`` כורך ``request_id``, ``user_id`` ו-``queue_delay`` בכל בקשה בלי לנקות — בפרודקשן כל בקשה היא גרינלט
    שמתחיל בהקשר ריק, אבל ה-test client של Flask רץ בהקשר הראשי, ומה שנכרך שם נשאר לטסטים שאחריו באותו worker.
    """
    ran: list = []
    structlog.contextvars.bind_contextvars(command="bot:previous_update")
    before = dict(structlog.contextvars.get_contextvars())
    try:
        await scope.IsolatedJobQueue.job_callback(types.SimpleNamespace(application=object()), _Job(ran))
        await scope.IsolatedUpdateApplication().process_update(object())
        after = dict(structlog.contextvars.get_contextvars())
    finally:
        structlog.contextvars.clear_contextvars()

    (job_context,) = ran
    assert job_context.get("command") == "job:probe_job" and job_context.get("request_id"), job_context
    (update_context,) = recorded_base_process_update
    assert "command" not in update_context and update_context.get("request_id"), update_context
    assert update_context["request_id"] != job_context["request_id"]
    # היחידות לא השאירו דבר מעצמן, ולא מחקו דבר ממה שהיה לפניהן.
    assert after == before, (before, after)
    # ומה שהיה לפניהן לא דלף פנימה — לא ה-command של "העדכון הקודם", ולא מה שטסטים קודמים השאירו.
    leaked = {key: value for key, value in before.items() if job_context.get(key) == value or update_context.get(key) == value}
    assert leaked == {}, leaked

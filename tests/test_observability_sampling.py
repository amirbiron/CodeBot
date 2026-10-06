import json
import logging
import os
import threading
import time

import structlog
import pytest

import observability as obs


def _call_maybe_sample(level: str, event: str, **extra):
    d = {"level": level, "event": event}
    d.update(extra)
    return obs._maybe_sample_info(None, None, d)


def _kept(event: str, **extra) -> bool:
    """האם ``_maybe_sample_info`` משאיר אירוע info, או זורק אותו ב-``DropEvent``."""
    try:
        _call_maybe_sample("info", event, **extra)
        return True
    except structlog.DropEvent:
        return False


@pytest.fixture(autouse=True)
def _fresh_window_memory(monkeypatch):
    """כל טסט מתחיל בלי זיכרון של שורות שכבר נשמרו.

    ``observability._INFO_SAMPLE_LAST_KEPT`` חי ברמת המודול. בלי איפוס, טסט אחד היה
    משתמש בהופעה הראשונה של שם אירוע, והטסט שאחריו היה מקבל את אותו שם כחזרה.
    """
    monkeypatch.setattr(obs, "_INFO_SAMPLE_LAST_KEPT", {})


@pytest.fixture
def clock(monkeypatch):
    """שעון שהטסט מזיז: חלון הדגימה נמדד ב-``time.monotonic``."""
    state = {"now": 1_000.0}
    monkeypatch.setattr(obs.time, "monotonic", lambda: state["now"])
    return state


def test_sampling_drops_info_when_rate_zero_and_not_allowlisted(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    with pytest.raises(structlog.DropEvent):
        _call_maybe_sample("info", "some_event", request_id="abcd1234")


def test_sampling_keeps_info_when_allowlisted_even_with_rate_zero(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    monkeypatch.setenv("LOG_INFO_SAMPLE_ALLOWLIST", "business_metric")
    out = _call_maybe_sample("info", "business_metric", request_id="abcd1234")
    assert out["event"] == "business_metric"


def test_sampling_keeps_non_info_levels(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    out = _call_maybe_sample("error", "err_evt")
    assert out["event"] == "err_evt"


def test_sampling_is_stable_per_request_id(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.5")
    # ההופעה הראשונה של "evt" נשמרת בלי הגרלה; היציבות לפי request_id היא של החזרות
    _call_maybe_sample("info", "evt", request_id="other-request")

    # With a fixed request_id, the decision should repeat deterministically
    for req_id in ("abcd1234", "rq-first-1"):

        def _decision():
            try:
                _call_maybe_sample("info", "evt", request_id=req_id)
                return "keep"
            except structlog.DropEvent:
                return "drop"

        first = _decision()
        second = _decision()
        assert first == second


def test_sampling_keeps_when_rate_high(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "1.0")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    out = _call_maybe_sample("info", "evt_any", request_id="z9y8x7w6")
    assert out["event"] == "evt_any"


def test_sampling_without_request_id_uses_random(monkeypatch):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.5")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    monkeypatch.setattr(obs.random, "random", lambda: 0.9)
    # ההופעה הראשונה נשמרת בלי הגרלה; ההגרלה חלה על החזרות שבתוך החלון
    _call_maybe_sample("info", "evt_no_req")

    # Case 1: random returns high value -> drop when rate=0.5
    with pytest.raises(structlog.DropEvent):
        _call_maybe_sample("info", "evt_no_req")

    # Case 2: random returns low value -> keep
    monkeypatch.setattr(obs.random, "random", lambda: 0.1)
    out = _call_maybe_sample("info", "evt_no_req")
    assert out["event"] == "evt_no_req"


def test_default_allowlist_includes_business_metric(monkeypatch):
    # No explicit allowlist; rate=0 should still keep business_metric
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    out = _call_maybe_sample("info", "business_metric", request_id="abcd1234")
    assert out["event"] == "business_metric"


def test_first_occurrence_is_kept_even_when_the_draw_would_drop_it(monkeypatch):
    """אירוע שקורה פעם אחת בחיי התהליך מגיע ללוג גם כשההגרלה הייתה זורקת אותו.

    עד 6.10.2026 כל הופעה הוגרלה בנפרד: עם ``LOG_INFO_SAMPLE_RATE=0.3`` השורה
    ``db_connected`` נעדרה מרוב העליות של הוובאפ באותו יום, והיעדר
    ``metrics_db_initialized`` הוביל למסקנה, בלי ראיה, שכותב המדדים לא עולה.
    """
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.3")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    monkeypatch.setattr(obs.random, "random", lambda: 0.99)

    # בלי request_id — ההגרלה הייתה 0.99, מעל 0.3
    assert _kept("metrics_db_initialized")
    # עם request_id — ה-hash של "rq-first-1" הוא כ-0.585, מעל 0.3
    assert _kept("db_connected", request_id="rq-first-1")


def test_repeats_inside_the_window_are_sampled(monkeypatch, clock):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.3")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    monkeypatch.setattr(obs.random, "random", lambda: 0.99)
    assert _kept("chatty")

    clock["now"] += obs.INFO_SAMPLE_WINDOW_SECONDS - 1
    assert not _kept("chatty")

    monkeypatch.setattr(obs.random, "random", lambda: 0.01)
    assert _kept("chatty")


def test_the_next_line_comes_out_a_window_after_the_last_kept_one_despite_drops(monkeypatch, clock):
    """מתי השורה הבאה כן יוצאת: חלון אחרי השורה האחרונה שנשמרה — שורות שנזרקו לא מזיזות אותו.

    זה הדפוס של ``first_ts`` ב-``LogEventAggregator`` (PR #1193): מצב דיכוי שנכתב גם
    על אירועים שדוכאו דוחה את הבאים בלי סוף.
    """
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.3")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    monkeypatch.setattr(obs.random, "random", lambda: 0.99)
    start = clock["now"]
    assert _kept("evt")

    for _ in range(5):
        clock["now"] += obs.INFO_SAMPLE_WINDOW_SECONDS / 10
        assert not _kept("evt")

    clock["now"] = start + obs.INFO_SAMPLE_WINDOW_SECONDS
    assert _kept("evt")


def test_a_repeat_kept_by_the_draw_starts_a_new_window(monkeypatch, clock):
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.3")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    start = clock["now"]
    monkeypatch.setattr(obs.random, "random", lambda: 0.99)
    assert _kept("evt")

    window = obs.INFO_SAMPLE_WINDOW_SECONDS
    clock["now"] = start + window / 2
    monkeypatch.setattr(obs.random, "random", lambda: 0.01)
    assert _kept("evt")

    monkeypatch.setattr(obs.random, "random", lambda: 0.99)
    # חלון שלם אחרי הראשונה, אבל רק חצי חלון אחרי זו שנשמרה בהגרלה
    clock["now"] = start + window
    assert not _kept("evt")
    clock["now"] = start + window / 2 + window
    assert _kept("evt")


def test_the_env_allowlist_adds_to_the_builtin_list(monkeypatch):
    """``LOG_INFO_SAMPLE_ALLOWLIST`` מוסיף על ``INFO_SAMPLE_BUILTIN_ALLOWLIST`` ואינו מחליף אותה.

    בייצור הוגדר במשתנה בדיוק מה שהתיעוד הציג כברירת מחדל — בלי ``access_logs`` —
    ובלי שאיש התכוון לזה, שורות הגישה נדגמו.
    """
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.0")
    monkeypatch.setenv("LOG_INFO_SAMPLE_ALLOWLIST", "business_metric,performance,github_sync,custom_evt")

    assert _kept("access_logs")
    for name in sorted(obs.INFO_SAMPLE_BUILTIN_ALLOWLIST):
        assert _kept(name), name
    assert _kept("custom_evt")
    assert not _kept("other_evt")


@pytest.mark.parametrize("raw", ["nan", "NaN", "not-a-number", ""])
def test_a_rate_that_is_not_a_number_keeps_everything(monkeypatch, raw):
    """NaN נכשל בכל השוואה, ובלי בדיקה הוא היה זורק כל אירוע info; כמו ערך שאינו מספר — 1.0."""
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", raw)
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    monkeypatch.setattr(obs.random, "random", lambda: 0.0)
    for _ in range(3):
        assert _kept("evt", request_id="rq-first-1")


@pytest.mark.parametrize(
    "raw, kept", [("0.999", True), ("2", True), ("inf", True), ("-0.5", False), ("-inf", False)]
)
def test_from_the_top_threshold_everything_is_kept_and_below_zero_nothing(monkeypatch, raw, kept):
    """מ-0.999 ומעלה הכול נשמר, וערך שלילי — כולל ``-inf`` — זורק כמו 0: אינסוף אינו NaN."""
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", raw)
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    assert _kept("evt") is kept


def test_forgetting_event_names_at_the_cap_only_adds_lines(monkeypatch, caplog):
    """התקרה על מספר השמות מרוקנת את הזיכרון — ושם שנשכח מקבל שוב שורה ראשונה, לא מאבד אותה."""
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.3")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    monkeypatch.setattr(obs.random, "random", lambda: 0.99)
    monkeypatch.setattr(obs, "_INFO_SAMPLE_MAX_TRACKED_EVENTS", 3)

    for name in ("a", "b", "c"):
        assert _kept(name)
    assert not _kept("a")

    with caplog.at_level(logging.WARNING, logger=obs.LOGGER.name):
        assert _kept("d")
    assert len(obs._INFO_SAMPLE_LAST_KEPT) <= 3
    ours = [r for r in caplog.records if r.name == obs.LOGGER.name]
    assert [r.levelno for r in ours] == [logging.WARNING]

    assert _kept("a")


def test_concurrent_first_occurrences_keep_a_single_line(monkeypatch):
    """הבדיקה מול החלון והרישום בו הם פעולה אחת: חוטים שמגיעים יחד עם שם חדש שומרים שורה אחת."""
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.3")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    monkeypatch.setattr(obs.random, "random", lambda: 0.99)

    class _SlowGetDict(dict):
        """מרחיב את הזמן בין הבדיקה לרישום — בלי נעילה כל החוטים היו רואים "אין שורה"."""

        def get(self, key, default=None):
            value = super().get(key, default)
            time.sleep(0.02)
            return value

    monkeypatch.setattr(obs, "_INFO_SAMPLE_LAST_KEPT", _SlowGetDict())
    workers = 8
    # ‏timeout משלו: אם אחד החוטים לא עולה, האחרים נשברים ב-BrokenBarrierError ויוצאים,
    # במקום לחכות לו לנצח ולהשאיר את תהליך הטסטים תלוי בסוף הריצה.
    barrier = threading.Barrier(workers, timeout=10)
    results = []

    def _worker():
        barrier.wait()
        results.append(_kept("racy_evt"))

    threads = [threading.Thread(target=_worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == workers
    assert results.count(True) == 1


@pytest.fixture
def structlog_pipeline(monkeypatch):
    """מגדיר את שרשרת ה-processors האמיתית (``setup_structlog_logging``) ומחזיר את הקודמת בסוף.

    גם ההקשר של structlog (contextvars) מתחיל ריק ומשוחזר בסוף. ``merge_contextvars``
    מוסיף לכל שורה את מה שמוצמד בהקשר, וה-``before_request`` של הוובאפ מצמיד
    ``request_id`` ולא מנקה אותו — כך שטסט קודם באותו worker שעבר דרך ה-test client
    השאיר ``request_id``, וההגרלה של כל החזרות כאן הפכה ליציבה לפי ה-hash שלו.
    """
    previous = structlog.get_config()
    previous_context = structlog.contextvars.get_contextvars()
    root_level = logging.getLogger().level
    structlog.contextvars.clear_contextvars()
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("LOG_AGGREGATOR_ENABLED", raising=False)
    obs.setup_structlog_logging("INFO")
    yield
    structlog.configure(**previous)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(**previous_context)
    logging.getLogger().setLevel(root_level)


def test_through_emit_event_the_first_line_of_each_event_reaches_the_output(monkeypatch, capsys, structlog_pipeline):
    """הצרכן הוא שרשרת ה-processors של structlog: האירוע יוצא מ-``emit_event`` ומגיע ל-stdout."""
    monkeypatch.setenv("LOG_INFO_SAMPLE_RATE", "0.3")
    monkeypatch.delenv("LOG_INFO_SAMPLE_ALLOWLIST", raising=False)
    monkeypatch.setattr(obs.random, "random", lambda: 0.99)
    capsys.readouterr()

    obs.emit_event("metrics_db_initialized", severity="info", collection="service_metrics")
    for _ in range(5):
        obs.emit_event("chatty_evt", severity="info")
    obs.emit_event("warn_evt", severity="warn")

    out = capsys.readouterr().out
    events = [json.loads(line).get("event") for line in out.splitlines() if line.startswith("{")]
    assert events.count("metrics_db_initialized") == 1
    assert events.count("chatty_evt") == 1
    assert events.count("warn_evt") == 1

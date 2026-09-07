"""בדיקות ללוגיקה של דוח הבוקר היומי.

כל בדיקה כאן נכתבה עם המוטציה שאמורה להפיל אותה, כי בדיקה שעוברת גם על הקוד
הקודם אינה ראיה לכיסוי. ביום שקט רוב הטענות מתקיימות טריוויאלית ("אין דפוס
חדש" נכון גם כשהקוד לא מסוגל לזהות דפוס חדש בכלל), ולכן כמעט לכל מקרה יש כאן
צד שני שמוודא שהבדיקה יודעת גם לומר "כן".

הדמויות (סטאבים) הן מחלקות קטנות שכתובות ביד, כמוסכמת הריפו — אין mongomock.
זמן מוזרק כפרמטר ולא מוקפא, כי כל הפונקציות כאן מקבלות את החלון במפורש.
"""

import copy
from datetime import datetime, timedelta, timezone

import pytest

import services.daily_report_service as drs

UTC = timezone.utc
DAY_END = datetime(2026, 9, 7, 8, 0, tzinfo=UTC)
DAY_START = DAY_END - timedelta(days=1)
WINDOW = timedelta(minutes=5)


# --------------------------------------------------------------------------
# דמויות
# --------------------------------------------------------------------------


class FakeCollection:
    """דמה של אוסף מונגו: מחזיקה רשימת מסמכים ומסננת אותה בפייתון.

    ``raises`` הופך אותה לאוסף שנופל — כך נבדק ההבדל בין "אין נתונים" לבין
    "הקריאה נכשלה", שהוא כל העניין של :class:`~services.daily_report_service.SourceRead`.
    """

    def __init__(self, docs=None, raises=False):
        self.docs = list(docs or [])
        self.raises = raises
        self.calls = {"find": 0, "aggregate": 0, "update_one": 0, "find_one": 0}

    # --- קריאה ---
    def find(self, query, projection=None):  # noqa: ARG002
        self.calls["find"] += 1
        if self.raises:
            raise RuntimeError("boom")
        return [d for d in self.docs if _matches(d, query)]

    def aggregate(self, pipeline):
        self.calls["aggregate"] += 1
        if self.raises:
            raise RuntimeError("boom")
        match = next((s["$match"] for s in pipeline if "$match" in s), {})
        rows = [d for d in self.docs if _matches(d, match)]
        # מספיק לדמות את הפייפליין של ה-endpoint האיטי: קיבוץ ובחירת המקסימום.
        grouped = {}
        for doc in rows:
            key = (doc.get("path", "unknown"), doc.get("method", "UNKNOWN"))
            entry = grouped.setdefault(key, {"count": 0, "max_duration": 0.0})
            entry["count"] += int(doc.get("count", 1) or 0)
            entry["max_duration"] = max(
                entry["max_duration"], float(doc.get("max_duration", 0.0) or 0.0)
            )
        out = [
            {"_id": {"path": k[0], "method": k[1]}, "count": v["count"], "max_duration": v["max_duration"]}
            for k, v in grouped.items()
        ]
        out.sort(key=lambda r: r["max_duration"], reverse=True)
        return out[:1]

    def find_one(self, query):
        self.calls["find_one"] += 1
        return next((copy.deepcopy(d) for d in self.docs if _matches(d, query)), None)

    # --- כתיבה ---
    def update_one(self, query, update, upsert=False):
        self.calls["update_one"] += 1
        existing = next((d for d in self.docs if _matches(d, query)), None)
        if existing is not None:
            existing.update(update.get("$set", {}))
            return _Result(modified=1)
        if upsert:
            doc = {k: v for k, v in query.items() if not isinstance(v, dict)}
            doc.update(update.get("$set", {}))
            doc.update(update.get("$setOnInsert", {}))
            self.docs.append(doc)
            return _Result(upserted=doc.get("_id"))
        return _Result()


class _Result:
    def __init__(self, modified=0, upserted=None):
        self.modified_count = modified
        self.upserted_id = upserted


def _norm(value):
    """מנרמל datetime כמו שמונגו עושה בפועל.

    ‏BSON שומר תאריכים כמילישניות UTC בלי אזור זמן, ולכן השרת האמיתי משווה
    חותמת נאיבית לחותמת מודעת בלי למצמץ. דמה שמשווה ב-Python הייתה זורקת
    ``TypeError`` — כשל של הדמה שנראה בדיוק כמו כשל של הקוד.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _matches(doc, query):
    for key, cond in (query or {}).items():
        value = _norm(_dig(doc, key))
        if isinstance(cond, dict):
            for op, operand in cond.items():
                operand = _norm(operand)
                if op == "$gte" and not (value is not None and value >= operand):
                    return False
                if op == "$lt" and not (value is not None and value < operand):
                    return False
                if op == "$ne" and value == operand:
                    return False
                if op == "$in" and value not in operand:
                    return False
        elif value != cond:
            return False
    return True


def _dig(doc, dotted):
    current = doc
    for part in str(dotted).split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


class FakeDB:
    def __init__(self, mapping=None, stats=None):
        self._mapping = mapping or {}
        self._stats = stats or {}

    def __getitem__(self, name):
        return self._mapping.setdefault(name, FakeCollection())

    def command(self, _cmd, name):
        if name not in self._stats:
            raise RuntimeError("no such collection")
        return self._stats[name]


class FakeCacheStats:
    def __init__(self, hits=0, misses=0, uptime=1000, enabled=True, error=""):
        self.keyspace_hits = hits
        self.keyspace_misses = misses
        self.uptime_seconds = uptime
        self.enabled = enabled
        self.error = error


class FakeEndpointResult:
    def __init__(self, rows=None, error_code="", has_more=False, last_refresh=""):
        self.rows = list(rows or [])
        self.error_code = error_code
        self.has_more = has_more
        self.last_refresh = last_refresh


def _alert(ts, *, severity="critical", name="High Error Rate", endpoint="", drill=False):
    return {
        "ts_dt": ts,
        "name": name,
        "severity": severity,
        "endpoint": endpoint,
        "details": {"is_drill": True} if drill else {},
    }


def _slow(ts, *, query_id="q1", collection="code_snippets", operation="find", withheld=None):
    doc = {
        "timestamp": ts,
        "query_id": query_id,
        "collection": collection,
        "operation": operation,
        "execution_time_ms": 1500.0,
    }
    if withheld:
        doc["raw_withheld_reason"] = withheld
    return doc


def _snapshot(day_key, **sources):
    base = {
        "_id": day_key,
        "day_start_utc": DAY_START,
        "day_end_utc": DAY_END,
        "created_at": DAY_END,
        "sources": {},
    }
    base["sources"].update(sources)
    return base


def _ok(**payload):
    return dict({"ok": True, "error": ""}, **payload)


# --------------------------------------------------------------------------
# 3 — ספירה, בלי חזרה על תוכן ההתראה
# --------------------------------------------------------------------------


@pytest.mark.parametrize("count", [2, 3])
def test_alert_counts_are_exact(count):
    """הספירה היא הספירה. שני מקרים, כדי שהמספר לא יוכל להיות קבוע מקרי."""
    docs = [_alert(DAY_START + timedelta(hours=i + 1)) for i in range(count)]
    coll = FakeCollection(docs)
    read = drs.read_alerts(coll, start=DAY_START, end=DAY_END)
    assert read.ok
    assert read.value["critical"] == count

    diff = drs.compare(_snapshot("2026-09-06", alerts=read.to_doc()), None)
    assert f"{count} CRITICAL" in drs.render_report(diff)


def test_alert_content_is_counted_not_repeated():
    """מה שכבר צעק בזמן אמת נספר, ולא נאמר שוב.

    חזרה על תוכן ההתראה היא הרעש שהורג דוחות כאלה, ולכן זו טענה שנאכפת
    בבדיקה ולא רק בכוונה.
    """
    coll = FakeCollection([_alert(DAY_START + timedelta(hours=2), endpoint="/api/secret-path")])
    read = drs.read_alerts(coll, start=DAY_START, end=DAY_END)
    text = drs.render_report(drs.compare(_snapshot("2026-09-06", alerts=read.to_doc()), None))
    assert "1 CRITICAL" in text
    assert "/api/secret-path" not in text
    assert "High Error Rate" not in text


def test_drill_alerts_are_excluded():
    """התראת תרגול אינה אירוע — כמו בכל אגרגציה קיימת על האוסף הזה."""
    coll = FakeCollection([_alert(DAY_START + timedelta(hours=1), drill=True)])
    read = drs.read_alerts(coll, start=DAY_START, end=DAY_END)
    assert read.value["critical"] == 0


def test_report_itself_never_opens_a_correlation_window():
    """הדוח נרשם ל-alerts_log, ואסור לו להצליב מול עצמו."""
    coll = FakeCollection(
        [_alert(DAY_START + timedelta(hours=1), severity="warn", name=drs.REPORT_ALERT_NAME)]
    )
    read = drs.read_alerts(coll, start=DAY_START, end=DAY_END)
    assert read.value["alert_windows"] == []


# --------------------------------------------------------------------------
# 4 — דפוס חדש, ושני הכיוונים
# --------------------------------------------------------------------------


def test_new_pattern_is_flagged_and_known_pattern_is_not():
    """שני הכיוונים באותה בדיקה: 'חדש' חייב להיות מסוגל גם לומר 'לא חדש'."""
    ts = DAY_START + timedelta(hours=3)
    coll = FakeCollection([_slow(ts, query_id="brand-new")])

    fresh = drs.read_slow_queries(
        coll, start=DAY_START, end=DAY_END, alert_windows=[], correlation_window=WINDOW,
        known_query_ids=None,
    )
    assert [p["query_id"] for p in fresh.value["new_patterns"]] == ["brand-new"]

    seen_before = drs.read_slow_queries(
        coll, start=DAY_START, end=DAY_END, alert_windows=[], correlation_window=WINDOW,
        known_query_ids={"brand-new": (DAY_START - timedelta(days=3)).isoformat()},
    )
    assert seen_before.value["new_patterns"] == []


def test_analyzable_flag_follows_withheld_reason():
    """'ניתן לניתוח' אינו הבטחה גורפת — הוא נגזר מהרשומה עצמה."""
    ts = DAY_START + timedelta(hours=2)
    plain = drs.read_slow_queries(
        FakeCollection([_slow(ts, query_id="a")]), start=DAY_START, end=DAY_END,
        alert_windows=[], correlation_window=WINDOW,
    )
    withheld = drs.read_slow_queries(
        FakeCollection([_slow(ts, query_id="b", withheld="owner_missing")]),
        start=DAY_START, end=DAY_END, alert_windows=[], correlation_window=WINDOW,
    )
    assert plain.value["new_patterns"][0]["analyzable"] is True
    assert withheld.value["new_patterns"][0]["analyzable"] is False


# --------------------------------------------------------------------------
# 5 — N+1 פר-דפוס, לא ממוצע
# --------------------------------------------------------------------------


def test_pattern_spike_reported_but_spread_is_not():
    """‏40 חזרות של דפוס אחד הן ממצא; אותן 40 על שמונה דפוסים אינן.

    זה בדיוק ההבדל שיחס כולל (שאילתות חלקי דפוסים) היה ממסך.
    """
    ts = DAY_START + timedelta(hours=4)
    concentrated = FakeCollection([_slow(ts, query_id="hot") for _ in range(40)])
    spread = FakeCollection(
        [_slow(ts, query_id=f"p{i % 8}") for i in range(40)]
    )
    yesterday = _snapshot(
        "2026-09-05",
        profiler=_ok(top_pattern={"query_id": "hot", "count": 10}, known_query_ids={"hot": ts.isoformat()}),
    )

    def _diff(coll):
        read = drs.read_slow_queries(
            coll, start=DAY_START, end=DAY_END, alert_windows=[], correlation_window=WINDOW,
            known_query_ids={"hot": ts.isoformat(), **{f"p{i}": ts.isoformat() for i in range(8)}},
        )
        return drs.compare(_snapshot("2026-09-06", profiler=read.to_doc()), yesterday)

    assert "N+1" in "\n".join(_diff(concentrated).lines)
    assert "N+1" not in "\n".join(_diff(spread).lines)


# --------------------------------------------------------------------------
# 6 + 17 — הצלבת חלונות, ושני הצדדים שלה
# --------------------------------------------------------------------------


def test_correlation_links_inside_window_and_not_outside():
    """בדיקה שמסוגלת להיכשל: בלי הצד השני היא חסרת ערך."""
    alert_ts = DAY_START + timedelta(hours=5)
    windows = [{"ts": alert_ts, "name": "HighLatency", "endpoint": "/x"}]

    near = drs.read_slow_queries(
        FakeCollection([_slow(alert_ts + timedelta(minutes=2))]),
        start=DAY_START, end=DAY_END, alert_windows=windows, correlation_window=WINDOW,
    )
    far = drs.read_slow_queries(
        FakeCollection([_slow(alert_ts + timedelta(minutes=20))]),
        start=DAY_START, end=DAY_END, alert_windows=windows, correlation_window=WINDOW,
    )

    assert (near.value["slow_in_alert_windows"], near.value["slow_outside_alert_windows"]) == (1, 0)
    assert (far.value["slow_in_alert_windows"], far.value["slow_outside_alert_windows"]) == (0, 1)


def test_correlation_treats_naive_timestamps_as_utc():
    """החוזה מפורש: חותמת נאיבית היא UTC, לא שעון מקומי.

    ``slow_queries_log`` נכתב ב-``datetime.utcnow()`` ולכן ההנחה נכונה היום.
    הבדיקה קיימת כדי שהיא **תישבר ברעש** ביום שמישהו יחליף ל-``now()``
    המקומי, במקום שההצלבה תשתוק בשקט.
    """
    alert_ts = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
    windows = [{"ts": alert_ts, "name": "HighLatency", "endpoint": ""}]
    start = datetime(2026, 9, 7, 0, 0, tzinfo=UTC)
    end = datetime(2026, 9, 8, 0, 0, tzinfo=UTC)

    # 12:00 נאיבי = 12:00Z לפי החוזה, כלומר שעתיים אחרי ההתראה ← לא מקושר.
    shifted = drs.read_slow_queries(
        FakeCollection([_slow(datetime(2026, 9, 7, 12, 0))]),
        start=start, end=end, alert_windows=windows, correlation_window=WINDOW,
    )
    # 10:02 נאיבי = בתוך החלון ← כן מקושר.
    aligned = drs.read_slow_queries(
        FakeCollection([_slow(datetime(2026, 9, 7, 10, 2))]),
        start=start, end=end, alert_windows=windows, correlation_window=WINDOW,
    )
    assert shifted.value["slow_in_alert_windows"] == 0
    assert aligned.value["slow_in_alert_windows"] == 1


def test_clock_skew_never_produces_negative_delta():
    """שאילתה שנכתבה 'לפני' ההתראה עדיין בתוך החלון, ולא נזרקת החוצה."""
    alert_ts = DAY_START + timedelta(hours=6)
    read = drs.read_slow_queries(
        FakeCollection([_slow(alert_ts - timedelta(minutes=2))]),
        start=DAY_START, end=DAY_END,
        alert_windows=[{"ts": alert_ts, "name": "x", "endpoint": ""}],
        correlation_window=WINDOW,
    )
    assert read.value["slow_in_alert_windows"] == 1


# --------------------------------------------------------------------------
# 16 — הכותב של slow_queries_log הוא UTC
# --------------------------------------------------------------------------


def test_profiler_writer_uses_utc_not_local_time(monkeypatch):
    """מוודא שהחותמת שנשמרת היא UTC ולא שעון מקומי.

    ההצלבה של הדוח נשענת על כך ש-``timestamp`` הנאיבי הוא UTC. ב-CI שרץ
    ב-UTC אי אפשר להבדיל בין ``utcnow()`` ל-``now()``, ולכן הבדיקה **מזייפת
    את השעון**: ``now()`` מחזיר UTC+2 ו-``utcnow()`` מחזיר UTC. מוטציה
    שמחליפה את הקריאה בקוד הייצור מפילה את הבדיקה הזו.
    """
    from services import query_profiler_service as qps

    real = qps.datetime

    class ShiftedClock(real):
        @classmethod
        def now(cls, tz=None):
            return real(2026, 9, 7, 14, 0)  # "מקומי" — UTC+2

        @classmethod
        def utcnow(cls):
            return real(2026, 9, 7, 12, 0)  # UTC

    monkeypatch.setattr(qps, "datetime", ShiftedClock)

    service = qps.QueryProfilerService(db_manager=None)
    record = service.record_slow_query_sync(
        collection="code_snippets", operation="find", query={"user_id": "1"},
        execution_time_ms=1500.0,
    )
    assert record.timestamp == real(2026, 9, 7, 12, 0), (
        "הפרופיילר חייב לכתוב UTC; שעון מקומי היה מזיז את חלון ההצלבה בשעתיים"
    )


# --------------------------------------------------------------------------
# 7 + 8 — בסיס להשוואה
# --------------------------------------------------------------------------


def test_without_baseline_no_change_lines_and_with_baseline_there_are():
    """אין D-1 ← לא ממציאים שינוי. יש D-1 ← השינוי כן מדווח."""
    today = _snapshot(
        "2026-09-06",
        metrics=_ok(top_slow_endpoint={"endpoint": "/new", "method": "GET", "max_duration": 9.0, "count": 3}),
        alerts=_ok(critical=1, error=0, deploy_count=0, alert_windows=[]),
    )
    yesterday = _snapshot(
        "2026-09-05",
        metrics=_ok(top_slow_endpoint={"endpoint": "/old", "method": "GET", "max_duration": 4.0, "count": 2}),
    )

    without = drs.compare(today, None)
    with_base = drs.compare(today, yesterday)

    assert not any("השתנה" in line for line in without.lines)
    assert "אין בסיס להשוואה" in drs.render_report(without)
    assert any("השתנה" in line for line in with_base.lines)


def test_previous_day_key_is_explicit_so_a_gap_is_not_silently_bridged():
    """‏D-1 מפורש: יום שה-job לא רץ בו לא יגרום להשוואה מול שלשום."""
    coll = FakeCollection([_snapshot("2026-09-04")])
    assert drs.previous_day_key("2026-09-06") == "2026-09-05"
    assert drs.load_snapshot(coll, drs.previous_day_key("2026-09-06")) is None


# --------------------------------------------------------------------------
# 9 — כשל קריאה אינו אפס
# --------------------------------------------------------------------------


def test_failed_source_reports_no_data_and_never_a_change():
    """הממצא המרכזי: מקור שנפל חייב להיראות אחרת ממקור שהחזיר אפס.

    בלי זה הסנאפשוט נשמר עם אפס, ומחר הדוח מכריז על שיפור.
    """
    read = drs.read_alerts(FakeCollection(raises=True), start=DAY_START, end=DAY_END)
    assert read.ok is False and read.value is None
    doc = read.to_doc()
    assert doc["ok"] is False and "critical" not in doc

    today = _snapshot("2026-09-06", alerts=doc, jobs=_ok(failed=2, stuck=0, zero_items_jobs=[]))
    text = drs.render_report(drs.compare(today, None))
    assert "אין נתון" in text
    assert "ירד" not in text and "השתפר" not in text
    # כשל של מקור אחד אינו משתיק את השאר.
    assert "2 כשלים" in text


def test_zero_and_failure_are_distinguishable():
    """אפס אמיתי ← ``ok=True``; כשל ← ``ok=False``. זו כל ההבחנה."""
    empty = drs.read_alerts(FakeCollection([]), start=DAY_START, end=DAY_END)
    broken = drs.read_alerts(FakeCollection(raises=True), start=DAY_START, end=DAY_END)
    assert empty.ok and empty.value["critical"] == 0
    assert not broken.ok


def test_cache_error_is_a_failure_not_a_zero_hit_rate():
    """``get_cache_stats`` מחזיר ``hit_rate=0.0`` בכשל — האפס הזה אסור להישמר."""
    failing = drs.read_cache(lambda: FakeCacheStats(enabled=True, error="Connection refused"))
    disabled = drs.read_cache(lambda: FakeCacheStats(enabled=False))
    healthy = drs.read_cache(lambda: FakeCacheStats(hits=90, misses=10))
    assert not failing.ok and not disabled.ok
    assert healthy.ok and healthy.value["keyspace_hits"] == 90


# --------------------------------------------------------------------------
# 10 — אתחול של Redis
# --------------------------------------------------------------------------


def test_redis_restart_reports_no_baseline_instead_of_fake_change():
    """``uptime`` שקטן מאתמול פירושו שהמונים אופסו — ואז ההפרש חסר משמעות."""
    today = _snapshot("2026-09-06", cache=_ok(keyspace_hits=50, keyspace_misses=5, uptime_seconds=100))
    yesterday = _snapshot("2026-09-05", cache=_ok(keyspace_hits=9000, keyspace_misses=1000, uptime_seconds=90000))
    lines = "\n".join(drs.compare(today, yesterday).lines)
    assert "הופעל מחדש" in lines
    assert "Hit Rate יומי" not in lines


def test_daily_hit_rate_is_derived_from_the_delta():
    """ה-Hit Rate המדווח הוא של היממה, לא הממוצע המצטבר מאז עליית Redis."""
    today = _snapshot("2026-09-06", cache=_ok(keyspace_hits=1500, keyspace_misses=1500, uptime_seconds=200000))
    yesterday = _snapshot("2026-09-05", cache=_ok(keyspace_hits=1000, keyspace_misses=0, uptime_seconds=100000))
    lines = "\n".join(drs.compare(today, yesterday).lines)
    # ‏500 פגיעות מול 1500 החטאות ביממה = 25%, בזמן שהמצטבר הוא 50%.
    assert "25.0%" in lines


# --------------------------------------------------------------------------
# 13 + 18 — שמירת הסנאפשוט
# --------------------------------------------------------------------------


def test_first_write_wins_and_the_stored_doc_is_returned():
    """שתי ריצות באותו יום: הראשונה מנצחת, והשנייה מקבלת אותה בחזרה.

    מוטציה שמחליפה ``$setOnInsert`` ב-``$set`` מפילה את הבדיקה — וזה בדיוק
    התרחיש של טריגר ידני שרץ במקביל לריצה המתוזמנת.
    """
    coll = FakeCollection()
    first = drs.save_snapshot(coll, _snapshot("2026-09-06", alerts=_ok(critical=7)))
    second = drs.save_snapshot(coll, _snapshot("2026-09-06", alerts=_ok(critical=99)))
    assert first["sources"]["alerts"]["critical"] == 7
    assert second["sources"]["alerts"]["critical"] == 7
    assert len(coll.docs) == 1


def test_save_snapshot_raises_when_nothing_was_persisted():
    """כשל שמירה נזרק ואינו נבלע: דוח בלי סנאפשוט הופך את מחר לשקר."""

    class Silent(FakeCollection):
        def update_one(self, *a, **k):  # noqa: ARG002
            return _Result()

        def find_one(self, _query):
            return None

    with pytest.raises(RuntimeError):
        drs.save_snapshot(Silent(), _snapshot("2026-09-06"))


# --------------------------------------------------------------------------
# 2 + 14 — יום שקט ואורך ההודעה
# --------------------------------------------------------------------------


def test_quiet_day_renders_nothing_and_an_event_renders_something():
    """יום שקט אינו מייצר הודעה — אבל הרינדור כן יודע לייצר אחת."""
    quiet = drs.compare(_snapshot("2026-09-06", alerts=_ok(critical=0, error=0, deploy_count=0)), None)
    noisy = drs.compare(_snapshot("2026-09-06", alerts=_ok(critical=1, error=0, deploy_count=0)), None)
    assert drs.render_report(quiet) is None
    assert drs.render_report(noisy) is not None


def test_long_report_is_trimmed_on_a_line_boundary():
    """הודעה ארוכה נחתכת ולא נכשלת מעל מגבלת Telegram."""
    diff = drs.ReportDiff(day_label="07/09", lines=[f"שורה מספר {i} " + "x" * 80 for i in range(200)])
    text = drs.render_report(diff)
    assert len(text) <= drs.MAX_MESSAGE_CHARS
    assert text.endswith("…")


# --------------------------------------------------------------------------
# זיכרון מתגלגל
# --------------------------------------------------------------------------


def test_known_items_roll_forward_and_expire():
    """סט ה'כבר ראינו' מתגלגל, ונגזם כשהוא יוצא מהחלון.

    בלי הגזימה הרשימה תופחת בלי גבול; בלי הגלגול, דפוס שנעלם וחזר היה
    מדווח כחדש פעמים רבות.
    """
    now = DAY_END
    fresh = (now - timedelta(days=2)).isoformat()
    stale = (now - timedelta(days=drs.KNOWN_ITEMS_WINDOW_DAYS + 5)).isoformat()
    merged = drs._roll_known({"old": stale, "kept": fresh}, {"new": now.isoformat()}, now=now)
    assert set(merged) == {"kept", "new"}


def test_collstats_growth_line_needs_both_days():
    """קצב גדילה דורש שני צדדים; בלי אתמול אין שורה."""
    today = _snapshot("2026-09-06", collstats=_ok(per_collection={"job_runs": {"count": 1200, "size_bytes": 2048}}))
    yesterday = _snapshot("2026-09-05", collstats=_ok(per_collection={"job_runs": {"count": 1000, "size_bytes": 1024}}))
    assert not any("DB:" in line for line in drs.compare(today, None).lines)
    assert any("+200" in line for line in drs.compare(today, yesterday).lines)


def test_collection_sizes_skip_missing_collections_without_failing():
    """אוסף שאינו קיים אינו כשל של המקור כולו."""
    db = FakeDB(stats={"job_runs": {"count": 5, "size": 100}})
    read = drs.read_collection_sizes(db, names=("job_runs", "does_not_exist"))
    assert read.ok
    assert set(read.value["per_collection"]) == {"job_runs"}


def test_mcp_new_error_type_needs_to_be_both_new_and_recent():
    """סוג שגיאה מדווח כחדש רק אם הוא גם ביממה וגם לא מוכר."""
    inside = (DAY_START + timedelta(hours=3)).isoformat()
    outside = (DAY_START - timedelta(days=4)).isoformat()

    def runner(name, _limit=None):
        if name == "ck_mcp_tool_failures":
            return FakeEndpointResult(
                rows=[
                    {"error_type": "ValidationError", "failed_at": inside},
                    {"error_type": "OldError", "failed_at": outside},
                ],
                last_refresh="2026-09-07T07:55:00Z",
            )
        return FakeEndpointResult(rows=[])

    read = drs.read_mcp(runner, start=DAY_START, end=DAY_END, known_error_types={})
    assert read.value["new_error_types"] == ["ValidationError"]

    known = drs.read_mcp(
        runner, start=DAY_START, end=DAY_END, known_error_types={"ValidationError": outside}
    )
    assert known.value["new_error_types"] == []


def test_mcp_endpoint_error_is_a_failure_not_an_empty_result():
    """``error_code`` מלא הוא כשל, גם כשהשורות ריקות — זה החוזה של השירות."""
    read = drs.read_mcp(
        lambda *a, **k: FakeEndpointResult(error_code="unauthorized"),
        start=DAY_START, end=DAY_END,
    )
    assert not read.ok and read.error == "mcp:unauthorized"


def test_mcp_line_carries_the_posthog_refresh_stamp():
    """נתון ממטמון של PostHog לא יוצג תחת 'אתמול' בלי לומר מתי הוא נכון."""
    today = _snapshot(
        "2026-09-06",
        mcp=_ok(new_error_types=["ValidationError"], missing_capabilities_today=1, last_refresh="07:55"),
    )
    line = next(line for line in drs.compare(today, None).lines if "MCP" in line)
    assert "נכון ל-07:55" in line


def test_collect_snapshot_survives_a_failing_source():
    """כשל של מקור אחד אינו מפיל את האיסוף ואינו משתיק את השאר."""
    ts = DAY_START + timedelta(hours=2)
    deps = drs.ReportDeps(
        alerts_coll=FakeCollection(raises=True),
        metrics_coll=FakeCollection([]),
        slow_coll=FakeCollection([_slow(ts)]),
        job_runs_coll=FakeCollection([{"started_at": ts, "job_id": "x", "status": "failed"}]),
        db_for_collstats=FakeDB(stats={"job_runs": {"count": 1, "size": 10}}),
        cache_stats_fn=lambda: FakeCacheStats(hits=1, misses=1),
        mcp_run_endpoint_fn=lambda *a, **k: FakeEndpointResult(rows=[]),
    )
    snap = drs.collect_snapshot(
        day_key="2026-09-06", day_start_utc=DAY_START, day_end_utc=DAY_END,
        deps=deps, previous=None, correlation_window=WINDOW, now=DAY_END,
    )
    assert snap["sources"]["alerts"]["ok"] is False
    assert snap["sources"]["jobs"]["ok"] is True
    assert snap["sources"]["jobs"]["failed"] == 1
    assert "known_query_ids" in snap["sources"]["profiler"]


def test_jobs_zero_items_needs_two_consecutive_days():
    """ריצה אחת על אפס פריטים אינה ממצא; חזרה יומיים ברצף כן."""
    today = _snapshot("2026-09-06", jobs=_ok(failed=0, stuck=0, zero_items_jobs=["drive_reschedule"]))
    yesterday_same = _snapshot("2026-09-05", jobs=_ok(failed=0, stuck=0, zero_items_jobs=["drive_reschedule"]))
    yesterday_other = _snapshot("2026-09-05", jobs=_ok(failed=0, stuck=0, zero_items_jobs=[]))
    assert any("אפס פריטים" in line for line in drs.compare(today, yesterday_same).lines)
    assert not any("אפס פריטים" in line for line in drs.compare(today, yesterday_other).lines)

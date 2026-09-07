"""עימוד, מיון וחלון זמן בטבלת השאילתות האיטיות של הפרופיילר.

**למה cursor ולא ``skip``.** האוסף מקבל כתיבות בזמן שמסתכלים בו — זו כל
מטרתו. עם ``skip``, שאילתה איטית שנרשמת בין שתי לחיצות על "טען עוד" מזיזה
את כל החלון באחת: שורה אחת מוצגת פעמיים והבאה נדלגת. הטסטים כאן בודקים את
**התכונה** הזו ולא את צורת הקוד — כותבים רשומה חדשה בין שני העמודים.

**ולמה ``_id`` כמפתח מיון משני.** ל-``execution_time_ms`` אין אילוץ ייחודיות.
נמדד באוסף האמיתי שאין בו היום אף תיקו — אבל זה נתון ולא הבטחה, ועמודת מיון
בלי tiebreaker בעימוד מייצרת שורות כפולות וחסרות
(``bugbot-rules/pagination-tiebreaker.md``).

הטסטים לא נוגעים במונגו אמיתי: אוסף דמה בזיכרון שמיישם ``find`` עם מיון
ומגבלה, ו-``count_documents``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from services.query_profiler_service import (
    PROFILER_WINDOW_HOURS,
    PersistentQueryProfilerService,
    ProfilerPagingError,
    decode_slow_query_cursor,
    encode_slow_query_cursor,
)

NOW = datetime(2026, 9, 7, 12, 0, 0)


def _matches(doc, query):
    """התאמה מספיקה לצורות שהקוד באמת בונה: ``$gte``/``$lt``/``$gt``/``$eq``, ``$and``, ``$or``."""
    for key, cond in query.items():
        if key == "$and":
            if not all(_matches(doc, sub) for sub in cond):
                return False
        elif key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
        elif isinstance(cond, dict):
            value = doc.get(key)
            for op, operand in cond.items():
                if value is None:
                    return False
                if op == "$gte" and not value >= operand:
                    return False
                if op == "$gt" and not value > operand:
                    return False
                if op == "$lt" and not value < operand:
                    return False
                if op == "$eq" and not value == operand:
                    return False
        elif doc.get(key) != cond:
            return False
    return True


def _flip_tied_groups(rows, fields):
    """הופך את סדרן של קבוצות רצופות ששוות בכל מפתחות המיון."""
    out, i = [], 0
    while i < len(rows):
        j = i + 1
        while j < len(rows) and all(rows[j][f] == rows[i][f] for f in fields):
            j += 1
        out.extend(reversed(rows[i:j]))
        i = j
    return out


class _FakeCollection:
    """אוסף מקרטון עם ``find`` שממיין באמת — בלי זה הטסט לא בודק את המיון.

    **והוא עוין בכוונה בתוך תיקו.** מונגו אינה מבטיחה שום סדר בין מסמכים
    שווים במפתחות המיון, ובפרט לא שהסדר יהיה זהה בין שתי הרצות. דמה שממיינת
    ב-``list.sort`` היציב של פייתון נותנת סדר קבוע — כלומר היא **מסתירה**
    את הבאג שה-tiebreaker קיים כדי למנוע. אומת: בלי ההיפוך הזה, מוטציה
    שמסירה את ``_id`` מהמיון השאירה את כל הטסטים ירוקים.

    לכן קבוצות שוות במפתחות המיון מתהפכות בכל קריאה שנייה — מודל נאמן ל"אין
    הבטחה", ולא לרעה. עם ``_id`` כמפתח אחרון אין קבוצות שוות בכלל, והמיון
    יציב שוב.
    """

    def __init__(self):
        self.docs = []
        self._calls = 0

    def insert_one(self, doc):
        stored = dict(doc)
        stored.setdefault("_id", ObjectId())
        self.docs.append(stored)
        return type("R", (), {"inserted_id": stored["_id"]})()

    def count_documents(self, query):
        return sum(1 for d in self.docs if _matches(d, query))

    def find(self, query=None, sort=None, limit=None):
        rows = [d for d in self.docs if _matches(d, query or {})]
        keys = list(sort or [])
        for field, direction in reversed(keys):
            rows.sort(key=lambda d: d[field], reverse=(direction == -1))

        # היפוך קבוצות שוות בכל קריאה שנייה — ראו ה-docstring של המחלקה.
        self._calls += 1
        if keys and self._calls % 2 == 0:
            rows = _flip_tied_groups(rows, [f for f, _ in keys])

        return rows[:limit] if limit else rows

    def aggregate(self, pipeline):  # pragma: no cover - לא בשימוש בטסטים כאן
        return []


class _FakeDB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, _FakeCollection())


@pytest.fixture
def svc():
    import unittest.mock as m

    manager = m.MagicMock()
    manager.db = _FakeDB()
    return PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)


def _seed(service, n, *, minutes_apart=1, ms_step=10.0):
    """``n`` רשומות, כל אחת ישנה בדקה ואיטית ב-``ms_step`` פחות מקודמתה."""
    coll = service.db_manager.db[service.COLLECTION_NAME]
    for i in range(n):
        coll.insert_one({
            "query_id": f"q{i}",
            "collection": "code_snippets",
            "operation": "find",
            "query_shape": {"user_id": "<value>"},
            "execution_time_ms": 1000.0 + (n - i) * ms_step,
            "timestamp": NOW - timedelta(minutes=i * minutes_apart),
        })
    return coll


def _walk(service, **kwargs):
    """מדפדף עד הסוף ומחזיר את רשימת ה-``query_id`` לפי הסדר."""
    seen, cursor = [], None
    for _ in range(20):
        page = service.get_slow_queries_page(cursor=cursor, **kwargs)
        seen.extend(r.query_id for r in page["records"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    return seen


class TestTheTotalIsNotAffectedByThePage:
    def test_total_stays_the_same_across_pages(self, svc):
        """``total`` נספר על החלון בלבד — **בלי** תנאי הקורסור.

        זו הנקודה שהסעיף כולו קיים בשבילה. הפילטר של דף שני מכיל
        ``field < v``, ולכן ספירה על "אותו פילטר" הייתה מחזירה מספר שקטן בכל
        לחיצה — והכותרת "מוצגות X מתוך Y" הייתה מייצרת בדיוק את הפער שהיא
        נועדה לסגור, רק בצורה שנראית כמו התקדמות.
        """
        _seed(svc, 12)

        first = svc.get_slow_queries_page(limit=5)
        second = svc.get_slow_queries_page(limit=5, cursor=first["next_cursor"])
        third = svc.get_slow_queries_page(limit=5, cursor=second["next_cursor"])

        assert first["total"] == 12
        assert second["total"] == 12, "הסך קטן בין דפים — תנאי הקורסור נכנס לספירה"
        assert third["total"] == 12

    def test_a_record_written_mid_paging_raises_the_total(self, svc):
        """הסך נספר מחדש בכל בקשה ולא נשמר: רשומה חדשה **אמורה** להגדיל אותו."""
        _seed(svc, 6)
        first = svc.get_slow_queries_page(limit=3)
        _seed(svc, 1, ms_step=0.5)

        second = svc.get_slow_queries_page(limit=3, cursor=first["next_cursor"])

        assert second["total"] == 7


class TestThePagingIsStableUnderConcurrentWrites:
    """התכונה שבגללה נבחר cursor ולא ``skip``."""

    @pytest.mark.parametrize("direction", ["desc", "asc"])
    def test_no_row_is_duplicated_or_skipped(self, svc, direction):
        """אף שורה לא פעמיים, וכל שורה שהייתה קיימת בדף 1 מופיעה בדיוק פעם אחת.

        זו התכונה שאינה תלויה בכיוון, ולכן היא נבדקת בשניהם.
        """
        _seed(svc, 9)
        existing = {f"q{i}" for i in range(9)}

        first = svc.get_slow_queries_page(limit=4, sort_direction=direction)
        # שאילתה איטית חדשה נרשמת **בין** שני העמודים — בדיוק מה ש-``skip`` שובר.
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "newcomer",
            "collection": "code_snippets",
            "operation": "find",
            "query_shape": {},
            "execution_time_ms": 1055.0,
            "timestamp": NOW + timedelta(minutes=1),
        })

        seen = [r.query_id for r in first["records"]]
        cursor = first["next_cursor"]
        while cursor:
            page = svc.get_slow_queries_page(limit=4, sort_direction=direction, cursor=cursor)
            seen.extend(r.query_id for r in page["records"])
            cursor = page["next_cursor"]

        assert len(seen) == len(set(seen)), f"שורות כפולות בין דפים: {seen}"
        assert existing <= set(seen), f"שורה שהייתה קיימת בדף 1 נדלגה: {existing - set(seen)}"

    def test_paging_through_a_tie_group_loses_nothing(self, svc):
        """כל השורות שוות במפתח המיון — ואז ``_id`` הוא הדבר היחיד שמפריד.

        **הטסט הזה נולד ממוטציה שלא הפילה כלום.** הסרתי את ``_id`` מהמיון וכל
        34 הטסטים נשארו ירוקים — כלומר טענתי תכונה שאף בדיקה לא אכפה. הסיבה
        הייתה שנתוני הזריעה לא הכילו אף תיקו, בדיוק כמו האוסף בפרודקשן היום.

        עם ערכים שווים ובלי tiebreaker, סדר השורות בתוך הקבוצה אינו מובטח
        בין שתי שאילתות: הקורסור מצביע על שורה אחת, והשאילתה הבאה מדלגת על
        אחרת שהייתה אמורה לבוא אחריה. הדמה כאן מדמה את זה במפורש.
        """
        coll = svc.db_manager.db[svc.COLLECTION_NAME]
        for i in range(8):
            coll.insert_one({
                "query_id": f"tie{i}", "collection": "c", "operation": "find", "query_shape": {},
                "execution_time_ms": 1500.0,  # כולן שוות
                "timestamp": NOW - timedelta(minutes=i),
            })

        seen = _walk(svc, limit=3, sort_field="execution_time_ms", sort_direction="desc")

        assert len(seen) == len(set(seen)), f"שורה הוצגה פעמיים בתוך קבוצת תיקו: {seen}"
        assert set(seen) == {f"tie{i}" for i in range(8)}, f"שורה נדלגה בתוך קבוצת תיקו: {sorted(seen)}"

    def test_descending_by_time_does_not_show_a_record_written_after_page_one(self, svc):
        """במיון יורד לפי זמן, רשומה חדשה יושבת **לפני** מיקום הקורסור.

        הקורסור מבקש ``timestamp < v``, והחדשה גדולה מ-``v`` — ולכן היא לא
        תופיע, וזו התנהגות נכונה. שטח הזמן שלה כבר נסרק בדף הראשון.
        """
        _seed(svc, 6)
        first = svc.get_slow_queries_page(limit=3, sort_field="timestamp", sort_direction="desc")
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "newcomer", "collection": "c", "operation": "find", "query_shape": {},
            "execution_time_ms": 1.0, "timestamp": NOW + timedelta(hours=1),
        })

        rest = _walk(svc, limit=3, sort_field="timestamp", sort_direction="desc")
        rest_after_first = svc.get_slow_queries_page(
            limit=3, sort_field="timestamp", sort_direction="desc", cursor=first["next_cursor"]
        )

        assert "newcomer" not in [r.query_id for r in rest_after_first["records"]]
        assert "newcomer" in rest, "בדפדוף מהתחלה היא כן צריכה להופיע — היא הכי חדשה"

    def test_ascending_by_time_does_show_a_record_written_after_page_one(self, svc):
        """ובמיון עולה — היא יושבת **אחרי** הקורסור, ולכן היא כן תופיע.

        אותה כתיבה בדיוק, תוצאה הפוכה, ושתיהן נכונות. טסט אחד שהיה מנוסח
        לשני הכיוונים היה נכשל מהסיבה הלא נכונה — או מרוכך כדי לעבור בשניהם.
        """
        _seed(svc, 6)
        first = svc.get_slow_queries_page(limit=3, sort_field="timestamp", sort_direction="asc")
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "newcomer", "collection": "c", "operation": "find", "query_shape": {},
            "execution_time_ms": 1.0, "timestamp": NOW + timedelta(hours=1),
        })

        seen, cursor = [], first["next_cursor"]
        while cursor:
            page = svc.get_slow_queries_page(
                limit=3, sort_field="timestamp", sort_direction="asc", cursor=cursor
            )
            seen.extend(r.query_id for r in page["records"])
            cursor = page["next_cursor"]

        assert "newcomer" in seen


class TestSortingIsServerSideAndFromAClosedList:
    @pytest.mark.parametrize("field", ["execution_time_ms", "timestamp", "collection", "operation"])
    def test_every_allowed_field_can_be_sorted_by(self, svc, field):
        _seed(svc, 4)
        page = svc.get_slow_queries_page(limit=4, sort_field=field, sort_direction="asc")
        assert len(page["records"]) == 4

    def test_the_direction_actually_reverses_the_order(self, svc):
        _seed(svc, 5)
        down = _walk(svc, limit=5, sort_field="timestamp", sort_direction="desc")
        up = _walk(svc, limit=5, sort_field="timestamp", sort_direction="asc")
        assert down == list(reversed(up))

    @pytest.mark.parametrize("bad", ["query_raw", "_id", "", None, 5, ["timestamp"]])
    def test_a_field_outside_the_list_is_rejected_and_not_sanitized(self, svc, bad):
        """שם שדה מקלט משתמש לעולם אינו נכנס ל-``sort``. נדחה, לא מנוקה."""
        with pytest.raises(ProfilerPagingError):
            svc.get_slow_queries_page(sort_field=bad)

    @pytest.mark.parametrize("bad", ["up", "", None, 1])
    def test_an_unknown_direction_is_rejected_and_not_defaulted(self, svc, bad):
        """כיוון פסול נדחה בקול. מיון שגוי שנראה תקין גרוע ממיון שנדחה."""
        with pytest.raises(ProfilerPagingError):
            svc.get_slow_queries_page(sort_direction=bad)


class TestTheCursorIsExternalInput:
    """``CORE-PATTERNS`` U3 — כל צורת פגם היא דחייה מסודרת, לא חריגה אחרת."""

    @pytest.mark.parametrize("bad", ["!!!", "eyJ", "", None, 7, {"f": "timestamp"}])
    def test_a_malformed_cursor_is_a_paging_error(self, svc, bad):
        _seed(svc, 3)
        if bad in ("", None):
            # ``None``/``""`` פירושם "בלי קורסור" ולכן הם חוקיים — הדף הראשון.
            assert svc.get_slow_queries_page(cursor=bad)["records"]
            return
        with pytest.raises(ProfilerPagingError):
            svc.get_slow_queries_page(cursor=bad)

    def test_a_cursor_minted_for_another_sort_is_rejected(self, svc):
        """קורסור של מיון אחר הוא חסר משמעות, ו-``$lt`` על השדה החדש היה
        מחזיר תוצאות שרירותיות בשקט. נדחה מפורשות."""
        _seed(svc, 6)
        by_time = svc.get_slow_queries_page(limit=3, sort_field="timestamp")

        with pytest.raises(ProfilerPagingError):
            svc.get_slow_queries_page(limit=3, sort_field="execution_time_ms", cursor=by_time["next_cursor"])

    def test_a_cursor_minted_for_the_other_direction_is_rejected(self, svc):
        _seed(svc, 6)
        down = svc.get_slow_queries_page(limit=3, sort_direction="desc")

        with pytest.raises(ProfilerPagingError):
            svc.get_slow_queries_page(limit=3, sort_direction="asc", cursor=down["next_cursor"])

    def test_a_datetime_survives_the_cursor_round_trip_as_a_datetime(self):
        """הקורסור מקודד ב-Extended JSON, ולכן ערך העמודה חוזר כטיפוס שלו.

        ב-JSON רגיל תאריך היה חוזר מחרוזת, והשוואת מחרוזת לשדה תאריך במונגו
        אינה מתאימה לאף מסמך — כלומר דף שני ריק, בשקט. זה בדיוק המנגנון
        שנבנה עבור ``query_raw``, וכאן הוא חוזר בחינם.
        """
        oid = ObjectId()
        token = encode_slow_query_cursor({"timestamp": NOW, "_id": oid}, "timestamp", "desc")
        value, last_id = decode_slow_query_cursor(token, "timestamp", "desc")

        assert isinstance(value, datetime) and value == NOW
        assert isinstance(last_id, ObjectId) and last_id == oid


class TestTheWindowComesFromOnePlace:
    def test_records_outside_the_window_are_not_counted_or_returned(self, svc):
        _seed(svc, 3)
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "ancient", "collection": "c", "operation": "find", "query_shape": {},
            "execution_time_ms": 9999.0, "timestamp": datetime.utcnow() - timedelta(days=3),
        })

        page = svc.get_slow_queries_page(limit=50, hours=PROFILER_WINDOW_HOURS)

        assert "ancient" not in [r.query_id for r in page["records"]]
        assert page["total"] == 3, "הסך חייב לספור את אותו חלון שהטבלה מציגה"

    def test_a_wider_window_sees_what_the_default_hides(self, svc):
        _seed(svc, 2)
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "ancient", "collection": "c", "operation": "find", "query_shape": {},
            "execution_time_ms": 9999.0, "timestamp": datetime.utcnow() - timedelta(days=3),
        })

        assert svc.get_slow_queries_page(limit=50, hours=24)["total"] == 2
        assert svc.get_slow_queries_page(limit=50, hours=24 * 7)["total"] == 3

    def test_the_summary_cache_is_keyed_by_the_window(self, svc, monkeypatch):
        """קאש בלי מפתח היה מחזיר לחלון אחד תשובה שחושבה עבור אחר.

        זה באג שנולד מהשינוי עצמו: כל עוד החלון היה קשיח, ערך יחיד היה נכון.
        ברגע ש-``hours`` הוא פרמטר, מפתח הקאש חייב לכלול אותו.
        """
        seen = []

        def _calc(hours=PROFILER_WINDOW_HOURS):
            seen.append(hours)
            return {"total_slow_queries": hours}

        monkeypatch.setattr(svc, "_calculate_summary_sync", _calc)

        assert svc.get_summary(hours=24)["total_slow_queries"] == 24
        assert svc.get_summary(hours=168)["total_slow_queries"] == 168, "החזיר תשובה של חלון אחר"
        assert svc.get_summary(hours=24)["total_slow_queries"] == 24
        assert seen == [24, 168], "כל חלון מחושב פעם אחת ונשמר בנפרד"

    def test_a_new_record_clears_every_window_and_not_just_one(self, svc, monkeypatch):
        """רשומה חדשה נכנסת לכל חלון שמכיל אותה — כלומר לכולם, כי היא נכתבת עכשיו."""
        calls = {"n": 0}

        def _calc(hours=PROFILER_WINDOW_HOURS):
            calls["n"] += 1
            return {"total_slow_queries": calls["n"]}

        monkeypatch.setattr(svc, "_calculate_summary_sync", _calc)
        svc.get_summary(hours=24)
        svc.get_summary(hours=168)

        svc.record_slow_query_sync(
            collection="c", operation="find", query={}, execution_time_ms=500.0
        )

        svc.get_summary(hours=24)
        svc.get_summary(hours=168)
        assert calls["n"] == 4, "חלון שלא נוקה החזיר סיכום מלפני הרשומה החדשה"

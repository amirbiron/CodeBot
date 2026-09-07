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
from dataclasses import replace as _dc_replace

from services.query_profiler_service import (
    PROFILER_WINDOW_HOURS,
    PersistentQueryProfilerService,
    ProfilerPagingError,
    decode_slow_query_cursor,
    encode_slow_query_cursor,
)


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
def now():
    """מקור זמן אחד **לכל טסט**, לא לכל מודול.

    השירות קורא ``datetime.utcnow()`` מחדש בכל קריאה, ולכן כל חותמת בטסט
    חייבת להיגזר משעון שנקרא סמוך לה. תאריך קשיח כאן היה פצצת זמן — הטסטים
    היו עוברים עד שהתאריך יוצא מחלון 24 השעות ואז נכשלים בלי ששום שורת קוד
    השתנתה. קבוע ברמת המודול היה רק **מזיז** את הבעיה: הוא נקרא פעם אחת
    בטעינה, וכל הקובץ חולק את הרגע ההוא — מה שהופך כשל בגבול החלון לאקראי
    ותלוי בכמה זמן רצה הסוויטה שלפניו. כשל אקראי גרוע מכשל קבוע.
    """
    return datetime.utcnow()


@pytest.fixture
def svc():
    import unittest.mock as m

    manager = m.MagicMock()
    manager.db = _FakeDB()
    return PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)


def _seed(service, n, *, now, minutes_apart=1, ms_step=10.0):
    """``n`` רשומות, כל אחת ישנה בדקה ואיטית ב-``ms_step`` פחות מקודמתה."""
    coll = service.db_manager.db[service.COLLECTION_NAME]
    for i in range(n):
        coll.insert_one({
            "query_id": f"q{i}",
            "collection": "code_snippets",
            "operation": "find",
            "query_shape": {"user_id": "<value>"},
            "execution_time_ms": 1000.0 + (n - i) * ms_step,
            "timestamp": now - timedelta(minutes=i * minutes_apart),
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


def _seed_ancient_into_buffer(service, now):
    """רשומה אחת טרייה ואחת בת שלושה ימים, ישירות ב-buffer שבזיכרון.

    ``record_slow_query_sync`` חותמת "עכשיו" ואין דרך לבקש ממנה חותמת אחרת,
    ולכן הרשומה הישנה נבנית ממנה ב-``_dc_replace``. החותמת נגזרת מ-``now``
    ולא מקריאת שעון נפרדת — מקור זמן אחד לכל הקובץ.

    שלושת טסטי הפולבאק חלקו את הזנב הזה מילה במילה. חוזה ה-buffer וביטול
    הקאש הם בדיוק הדברים שסוחפים בין עותקים.
    """
    service.record_slow_query_sync(
        collection="code_snippets", operation="find", query={"a": 1}, execution_time_ms=500.0
    )
    service._slow_queries.append(_dc_replace(
        service._slow_queries[0], query_id="ancient", timestamp=now - timedelta(days=3)
    ))
    service._invalidate_summary_cache()


class TestTheTotalIsNotAffectedByThePage:
    def test_total_stays_the_same_across_pages(self, svc, now):
        """``total`` נספר על החלון בלבד — **בלי** תנאי הקורסור.

        זו הנקודה שהסעיף כולו קיים בשבילה. הפילטר של דף שני מכיל
        ``field < v``, ולכן ספירה על "אותו פילטר" הייתה מחזירה מספר שקטן בכל
        לחיצה — והכותרת "מוצגות X מתוך Y" הייתה מייצרת בדיוק את הפער שהיא
        נועדה לסגור, רק בצורה שנראית כמו התקדמות.
        """
        _seed(svc, 12, now=now)

        first = svc.get_slow_queries_page(limit=5)
        second = svc.get_slow_queries_page(limit=5, cursor=first["next_cursor"])
        third = svc.get_slow_queries_page(limit=5, cursor=second["next_cursor"])

        assert first["total"] == 12
        assert second["total"] == 12, "הסך קטן בין דפים — תנאי הקורסור נכנס לספירה"
        assert third["total"] == 12

    def test_a_record_written_mid_paging_raises_the_total(self, svc, now):
        """הסך נספר מחדש בכל בקשה ולא נשמר: רשומה חדשה **אמורה** להגדיל אותו."""
        _seed(svc, 6, now=now)
        first = svc.get_slow_queries_page(limit=3)
        _seed(svc, 1, now=now, ms_step=0.5)

        second = svc.get_slow_queries_page(limit=3, cursor=first["next_cursor"])

        assert second["total"] == 7


class TestTheMinimumTimeFilterNarrowsThePopulation:
    """‏``min_time`` — מסנן מתועד שהמעבר ל-``get_slow_queries_page`` הפיל בשקט.

    הראוט המשיך לקבל אותו ולהחזיר 200 עם שורות לא מסוננות. הפרסור והדחייה
    נבדקים ב-``test_profiler_min_time_filter.py``; כאן נבדקת ההשפעה, כי הדמה
    בקובץ הזה היא זו שמבינה את תנאי הקורסור.
    """

    @staticmethod
    def _seed_mixed(service, now):
        """שתי שאילתות מעל 1200ms ושתיים מתחת."""
        coll = service.db_manager.db[service.COLLECTION_NAME]
        for i, ms in enumerate([2000.0, 1500.0, 1100.0, 900.0]):
            coll.insert_one({
                "query_id": f"m{i}", "collection": "code_snippets", "operation": "find",
                "query_shape": {}, "execution_time_ms": ms, "timestamp": now - timedelta(minutes=i),
            })

    def test_rows_below_the_threshold_are_not_returned(self, svc, now):
        self._seed_mixed(svc, now)

        page = svc.get_slow_queries_page(limit=50, min_execution_time_ms=1200.0)

        assert [r.query_id for r in page["records"]] == ["m0", "m1"]

    def test_and_they_are_not_counted_either(self, svc, now):
        """**זו הבדיקה שמבדילה בין הפילטר הנכון לפילטר הלא נכון.**

        אילו ``min_execution_time_ms`` היה נכנס לפילטר הדף במקום לפילטר
        החלון, השורות היו נכונות ו-``total`` היה 4 — כלומר "מוצגות 2 מתוך 4"
        על אוכלוסייה שכולה 2. בדיקה שמאמתת רק שהפרמטר "הועבר" הייתה עוברת
        בשתי הגרסאות.
        """
        self._seed_mixed(svc, now)

        page = svc.get_slow_queries_page(limit=50, min_execution_time_ms=1200.0)

        assert page["total"] == 2, "הסך סופר שורות שהמשתמש ביקש לסנן החוצה"

    def test_without_it_nothing_is_filtered(self, svc, now):
        self._seed_mixed(svc, now)

        page = svc.get_slow_queries_page(limit=50)

        assert page["total"] == 4 and len(page["records"]) == 4

    def test_it_holds_across_pages(self, svc, now):
        """הפילטר חל על כל דף, והסך נשאר יציב — בדיוק כמו ``collection_filter``."""
        self._seed_mixed(svc, now)

        first = svc.get_slow_queries_page(limit=1, min_execution_time_ms=1200.0)
        second = svc.get_slow_queries_page(
            limit=1, min_execution_time_ms=1200.0, cursor=first["next_cursor"]
        )

        assert [r.query_id for r in first["records"]] == ["m0"]
        assert [r.query_id for r in second["records"]] == ["m1"]
        assert first["total"] == second["total"] == 2
        assert second["next_cursor"] is None, "אין דף שלישי — הדף השני הוא האחרון"


class TestTheCursorBelongsToOnePopulation:
    """קורסור אומר "אחרי הנקודה הזו" — וזו טענה על **אוסף שורות מסוים**.

    זה לא תרחיש תיאורטי: ל-``<select id="collection-filter">`` בדשבורד לא היה
    שום מאזין שינוי (אומת גם ב-``main``), ולכן בחירת collection ואז לחיצה על
    "טען עוד" שלחה את המסנן החדש עם הקורסור הישן.
    """

    @staticmethod
    def _seed_two_collections(service, now):
        """‏``other`` חדש יותר מכל שורות ``code_snippets``.

        זה מה שהופך את הבדיקה למשמעותית: במיון יורד לפי זמן הוא יושב **לפני**
        נקודת הקורסור שנטבעה בלעדיו, כלומר בדיוק במקום שממנו שורות נעלמות.
        """
        coll = service.db_manager.db[service.COLLECTION_NAME]
        for i in range(4):
            coll.insert_one({
                "query_id": f"c{i}", "collection": "code_snippets", "operation": "find",
                "query_shape": {}, "execution_time_ms": 1000.0 + i,
                "timestamp": now - timedelta(minutes=10 + i),
            })
        coll.insert_one({
            "query_id": "newest_other", "collection": "other", "operation": "find",
            "query_shape": {}, "execution_time_ms": 1500.0, "timestamp": now,
        })

    def test_a_cursor_from_a_different_collection_filter_is_rejected(self, svc, now):
        """**קודם מה שנשבר, ואחר כך הדחייה.**

        הטסט מראה תחילה שהשורה שהייתה נעלמת קיימת ונגישה כשמדפדפים נכון,
        ורק אז שהקורסור הזר נדחה. בדיקה שמאמתת רק "נזרקה חריגה" הייתה עוברת
        גם על מימוש שדוחה יותר מדי.
        """
        self._seed_two_collections(svc, now)

        # דף ראשון בלי מסנן, מיון יורד לפי זמן: ``newest_other`` הוא הראשון.
        first = svc.get_slow_queries_page(
            limit=1, sort_field="timestamp", sort_direction="desc"
        )
        assert [r.query_id for r in first["records"]] == ["newest_other"]

        # ובדפדוף תקין עם המסנן, השורה הזו היא כל האוכלוסייה.
        filtered = svc.get_slow_queries_page(
            limit=5, sort_field="timestamp", sort_direction="desc", collection_filter="other"
        )
        assert [r.query_id for r in filtered["records"]] == ["newest_other"]

        # אבל הקורסור של הדף הראשון נטבע לאוכלוסייה אחרת. בלי הקשירה הוא היה
        # מבקש "זמן < הזמן של newest_other" בתוך ``other`` — כלומר אפס שורות,
        # וטבלה ריקה בלי שום סימן שמשהו לא בסדר.
        with pytest.raises(ProfilerPagingError) as exc:
            svc.get_slow_queries_page(
                limit=5, sort_field="timestamp", sort_direction="desc",
                collection_filter="other", cursor=first["next_cursor"],
            )
        assert "filter" in str(exc.value)

    def test_a_cursor_from_a_different_min_time_is_rejected(self, svc, now):
        self._seed_two_collections(svc, now)
        first = svc.get_slow_queries_page(limit=2)

        with pytest.raises(ProfilerPagingError):
            svc.get_slow_queries_page(
                limit=2, min_execution_time_ms=1200.0, cursor=first["next_cursor"]
            )

    def test_a_cursor_from_a_different_time_window_is_rejected(self, svc, now):
        self._seed_two_collections(svc, now)
        first = svc.get_slow_queries_page(limit=2, hours=24)

        with pytest.raises(ProfilerPagingError, match="^cursor_filter_mismatch$"):
            svc.get_slow_queries_page(limit=2, hours=48, cursor=first["next_cursor"])

    def test_equivalent_normalized_time_windows_accept_the_same_cursor(self, svc, now):
        self._seed_two_collections(svc, now)
        first = svc.get_slow_queries_page(limit=2, hours=0)

        second = svc.get_slow_queries_page(limit=2, hours=1, cursor=first["next_cursor"])

        assert len(second["records"]) == 2

    def test_the_same_filters_are_accepted(self, svc, now):
        """**מה שהקשירה לא אמורה לדחות.**

        בלי הטסט הזה, מימוש שמחזיר "תמיד 400" היה עובר את כל האחרים.
        """
        self._seed_two_collections(svc, now)

        first = svc.get_slow_queries_page(limit=2, collection_filter="code_snippets")
        second = svc.get_slow_queries_page(
            limit=2, collection_filter="code_snippets", cursor=first["next_cursor"]
        )

        assert [r.query_id for r in second["records"]] == ["c1", "c0"]

    def test_paging_without_any_filter_still_works(self, svc, now):
        """המסלול הנפוץ — בלי מסננים בכלל — אינו נפגע מהקשירה."""
        _seed(svc, 6, now=now)

        assert len(_walk(svc, limit=2)) == 6


class TestTheNextPageIsSeenAndNotGuessed:
    """‏"יש דף נוסף" נגזר מרשומה עודפת שנראתה, ולא מ"הדף מלא ולכן כנראה יש עוד"."""

    def test_a_last_page_that_fills_exactly_offers_no_cursor(self, svc, now):
        """שישה פריטים בדפים של שלושה: הדף השני הוא האחרון, ואין אחריו כלום.

        עם התנאי הישן (``len(docs) == limit_n``) הדף השני היה מחזיר קורסור,
        "טען עוד" היה נשאר גלוי לצד כותרת שאומרת "מוצגות 6 מתוך 6", והלחיצה
        הייתה מחזירה אפס שורות.
        """
        _seed(svc, 6, now=now)

        first = svc.get_slow_queries_page(limit=3)
        second = svc.get_slow_queries_page(limit=3, cursor=first["next_cursor"])

        assert len(second["records"]) == 3
        assert second["next_cursor"] is None, "קורסור לדף שאין בו כלום"

    def test_a_page_that_is_not_full_offers_no_cursor(self, svc, now):
        _seed(svc, 2, now=now)

        assert svc.get_slow_queries_page(limit=5)["next_cursor"] is None

    def test_the_extra_record_is_not_returned_to_the_caller(self, svc, now):
        """מושכים ``limit + 1``, אבל מחזירים ``limit``. הרשומה העודפת היא סימן, לא תוכן."""
        _seed(svc, 10, now=now)

        page = svc.get_slow_queries_page(limit=4)

        assert len(page["records"]) == 4
        assert page["next_cursor"] is not None


class TestThePagingIsStableUnderConcurrentWrites:
    """התכונה שבגללה נבחר cursor ולא ``skip``."""

    @pytest.mark.parametrize("direction", ["desc", "asc"])
    def test_no_row_is_duplicated_or_skipped(self, svc, now, direction):
        """אף שורה לא פעמיים, וכל שורה שהייתה קיימת בדף 1 מופיעה בדיוק פעם אחת.

        זו התכונה שאינה תלויה בכיוון, ולכן היא נבדקת בשניהם.
        """
        _seed(svc, 9, now=now)
        existing = {f"q{i}" for i in range(9)}

        first = svc.get_slow_queries_page(limit=4, sort_direction=direction)
        # שאילתה איטית חדשה נרשמת **בין** שני העמודים — בדיוק מה ש-``skip`` שובר.
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "newcomer",
            "collection": "code_snippets",
            "operation": "find",
            "query_shape": {},
            "execution_time_ms": 1055.0,
            "timestamp": now + timedelta(minutes=1),
        })

        seen = [r.query_id for r in first["records"]]
        cursor = first["next_cursor"]
        while cursor:
            page = svc.get_slow_queries_page(limit=4, sort_direction=direction, cursor=cursor)
            seen.extend(r.query_id for r in page["records"])
            cursor = page["next_cursor"]

        assert len(seen) == len(set(seen)), f"שורות כפולות בין דפים: {seen}"
        assert existing <= set(seen), f"שורה שהייתה קיימת בדף 1 נדלגה: {existing - set(seen)}"

    def test_paging_through_a_tie_group_loses_nothing(self, svc, now):
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
                "timestamp": now - timedelta(minutes=i),
            })

        seen = _walk(svc, limit=3, sort_field="execution_time_ms", sort_direction="desc")

        assert len(seen) == len(set(seen)), f"שורה הוצגה פעמיים בתוך קבוצת תיקו: {seen}"
        assert set(seen) == {f"tie{i}" for i in range(8)}, f"שורה נדלגה בתוך קבוצת תיקו: {sorted(seen)}"

    def test_descending_by_time_does_not_show_a_record_written_after_page_one(self, svc, now):
        """במיון יורד לפי זמן, רשומה חדשה יושבת **לפני** מיקום הקורסור.

        הקורסור מבקש ``timestamp < v``, והחדשה גדולה מ-``v`` — ולכן היא לא
        תופיע, וזו התנהגות נכונה. שטח הזמן שלה כבר נסרק בדף הראשון.
        """
        _seed(svc, 6, now=now)
        first = svc.get_slow_queries_page(limit=3, sort_field="timestamp", sort_direction="desc")
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "newcomer", "collection": "c", "operation": "find", "query_shape": {},
            "execution_time_ms": 1.0, "timestamp": now + timedelta(hours=1),
        })

        rest = _walk(svc, limit=3, sort_field="timestamp", sort_direction="desc")
        rest_after_first = svc.get_slow_queries_page(
            limit=3, sort_field="timestamp", sort_direction="desc", cursor=first["next_cursor"]
        )

        assert "newcomer" not in [r.query_id for r in rest_after_first["records"]]
        assert "newcomer" in rest, "בדפדוף מהתחלה היא כן צריכה להופיע — היא הכי חדשה"

    def test_ascending_by_time_does_show_a_record_written_after_page_one(self, svc, now):
        """ובמיון עולה — היא יושבת **אחרי** הקורסור, ולכן היא כן תופיע.

        אותה כתיבה בדיוק, תוצאה הפוכה, ושתיהן נכונות. טסט אחד שהיה מנוסח
        לשני הכיוונים היה נכשל מהסיבה הלא נכונה — או מרוכך כדי לעבור בשניהם.
        """
        _seed(svc, 6, now=now)
        first = svc.get_slow_queries_page(limit=3, sort_field="timestamp", sort_direction="asc")
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "newcomer", "collection": "c", "operation": "find", "query_shape": {},
            "execution_time_ms": 1.0, "timestamp": now + timedelta(hours=1),
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
    def test_every_allowed_field_can_be_sorted_by(self, svc, now, field):
        _seed(svc, 4, now=now)
        page = svc.get_slow_queries_page(limit=4, sort_field=field, sort_direction="asc")
        assert len(page["records"]) == 4

    def test_the_direction_actually_reverses_the_order(self, svc, now):
        _seed(svc, 5, now=now)
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
    def test_a_malformed_cursor_is_a_paging_error(self, svc, now, bad):
        _seed(svc, 3, now=now)
        if bad in ("", None):
            # ``None``/``""`` פירושם "בלי קורסור" ולכן הם חוקיים — הדף הראשון.
            assert svc.get_slow_queries_page(cursor=bad)["records"]
            return
        with pytest.raises(ProfilerPagingError):
            svc.get_slow_queries_page(cursor=bad)

    def test_a_cursor_minted_for_another_sort_is_rejected(self, svc, now):
        """קורסור של מיון אחר הוא חסר משמעות, ו-``$lt`` על השדה החדש היה
        מחזיר תוצאות שרירותיות בשקט. נדחה מפורשות."""
        _seed(svc, 6, now=now)
        by_time = svc.get_slow_queries_page(limit=3, sort_field="timestamp")

        with pytest.raises(ProfilerPagingError):
            svc.get_slow_queries_page(limit=3, sort_field="execution_time_ms", cursor=by_time["next_cursor"])

    def test_a_cursor_minted_for_the_other_direction_is_rejected(self, svc, now):
        _seed(svc, 6, now=now)
        down = svc.get_slow_queries_page(limit=3, sort_direction="desc")

        with pytest.raises(ProfilerPagingError):
            svc.get_slow_queries_page(limit=3, sort_direction="asc", cursor=down["next_cursor"])

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("execution_time_ms", "1000.0"),
            ("execution_time_ms", True),
            ("timestamp", "2026-09-07T12:00:00"),
            ("collection", 7),
            ("operation", None),
        ],
    )
    def test_a_cursor_sort_value_must_have_the_fields_type(self, field, bad_value):
        token = encode_slow_query_cursor(
            {field: bad_value, "_id": ObjectId()}, field, "desc"
        )

        with pytest.raises(ProfilerPagingError, match="^malformed_cursor$"):
            decode_slow_query_cursor(token, field, "desc")

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("execution_time_ms", 1000),
            ("execution_time_ms", 1000.5),
            ("timestamp", datetime(2026, 9, 7, 12, 0, 0)),
            ("collection", "code_snippets"),
            ("operation", "find"),
        ],
    )
    def test_a_cursor_sort_value_with_the_fields_type_is_accepted(self, field, value):
        oid = ObjectId()
        token = encode_slow_query_cursor({field: value, "_id": oid}, field, "desc")

        decoded_value, decoded_id = decode_slow_query_cursor(token, field, "desc")

        assert decoded_value == value
        assert decoded_id == oid

    def test_a_datetime_survives_the_cursor_round_trip_as_a_datetime(self):
        """הקורסור מקודד ב-Extended JSON, ולכן ערך העמודה חוזר כטיפוס שלו.

        ב-JSON רגיל תאריך היה חוזר מחרוזת, והשוואת מחרוזת לשדה תאריך במונגו
        אינה מתאימה לאף מסמך — כלומר דף שני ריק, בשקט. זה בדיוק המנגנון
        שנבנה עבור ``query_raw``, וכאן הוא חוזר בחינם.

        **החריג היחיד לפיקסצ'ר ``now``, במכוון** — וזו טענה שנבדקה: אין בקובץ
        הזה שום קריאה אחרת ל-``datetime.utcnow()`` מלבד הפיקסצ'ר עצמו.
        (בגרסה קודמת הטענה **לא** הייתה נכונה: שלושת טסטי הפולבאק קראו לשעון
        ישירות. הם עברו לעוזר ``_seed_ancient_into_buffer`` שגוזר מ-``now``.)

        הטסט הזה אינו נוגע בשום חלון ובשום שעון — התאריך כאן הוא **ערך**
        שמקודדים ומפענחים, לא רגע שמשווים אליו. תאריך קבוע הוא דווקא הבחירה
        הנכונה: הוא הופך את הבדיקה לדטרמיניסטית לחלוטין.
        """
        when = datetime(2026, 9, 7, 12, 0, 0)
        oid = ObjectId()
        token = encode_slow_query_cursor({"timestamp": when, "_id": oid}, "timestamp", "desc")
        value, last_id = decode_slow_query_cursor(token, "timestamp", "desc")

        assert isinstance(value, datetime) and value == when
        assert isinstance(last_id, ObjectId) and last_id == oid


class TestTheWindowComesFromOnePlace:
    def test_records_outside_the_window_are_not_counted_or_returned(self, svc, now):
        _seed(svc, 3, now=now)
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "ancient", "collection": "c", "operation": "find", "query_shape": {},
            "execution_time_ms": 9999.0, "timestamp": now - timedelta(days=3),
        })

        page = svc.get_slow_queries_page(limit=50, hours=PROFILER_WINDOW_HOURS)

        assert "ancient" not in [r.query_id for r in page["records"]]
        assert page["total"] == 3, "הסך חייב לספור את אותו חלון שהטבלה מציגה"

    def test_a_wider_window_sees_what_the_default_hides(self, svc, now):
        _seed(svc, 2, now=now)
        svc.db_manager.db[svc.COLLECTION_NAME].insert_one({
            "query_id": "ancient", "collection": "c", "operation": "find", "query_shape": {},
            "execution_time_ms": 9999.0, "timestamp": now - timedelta(days=3),
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

    def test_the_in_memory_fallback_respects_the_window_when_there_is_no_db(self, now):
        """כשאין DB, הסיכום נבנה מהזיכרון — **וגם הוא חייב לכבד את החלון**.

        קודם המסלול הזה קרא ל-``super().get_summary()``, שסופר את כל ה-buffer
        בלי חלון. כלומר בדיוק הפער שכל הסעיף בא לסגור, רק ברגע שבו קשה לשים
        לב אליו: הכרטיס מציג מספר על אוכלוסייה אחת, הטבלה על אחרת, וה-DB נפל.
        """
        import unittest.mock as m

        manager = m.MagicMock()
        manager.db = None  # מסלול הפולבאק לזיכרון
        service = PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)

        _seed_ancient_into_buffer(service, now)

        assert service.get_summary(hours=24)["total_slow_queries"] == 1
        assert service.get_summary(hours=24 * 7)["total_slow_queries"] == 2

    def test_the_fallback_after_a_db_failure_also_respects_the_window(self, svc, now, monkeypatch):
        """אתר הפולבאק השני — חריגת DB — הוא מסלול נפרד בקוד, ולכן נבדק בנפרד.

        תיקון של אחד מהם אינו נוגע בשני, ובדיקה של אחד אינה ראיה על השני.
        """
        def _boom(hours=PROFILER_WINDOW_HOURS):
            raise RuntimeError("mongo down")

        monkeypatch.setattr(svc, "_calculate_summary_sync", _boom)

        _seed_ancient_into_buffer(svc, now)

        assert svc.get_summary(hours=24)["total_slow_queries"] == 1
        assert svc.get_summary(hours=24 * 7)["total_slow_queries"] == 2

    def test_both_empty_paths_return_the_same_contract(self, svc, monkeypatch):
        """מסלול ה-DB ומסלול הזיכרון מחזירים את **אותם שדות** כשאין מה לסכם.

        זו התכונה שהחילוץ ל-``_empty_summary`` קונה, וכאן היא נאכפת. בלי
        הטסט הזה החילוץ היה שיפור מבני בלי ראיה: הרצתי מוטציה שמשנה את החוזה
        ולא נפל שום טסט — כי שני המסלולים השתנו יחד. מה שצריך להיאכף הוא
        שהם **מסכימים**, ולכן המוטציה הנכונה כאן היא להחזיר עותק inline
        לאחד מהם.

        למה זה חשוב דווקא כאן: מסלול הזיכרון רץ כשה-DB נפל. שדה חסר שם הוא
        שדה חסר בדיוק ברגע שבו אף אחד לא מסתכל.
        """
        from_db = svc.get_summary(hours=24)  # אוסף ריק — הענף של ``total <= 0``

        monkeypatch.setattr(
            svc, "_calculate_summary_sync",
            lambda hours=PROFILER_WINDOW_HOURS: (_ for _ in ()).throw(RuntimeError("down")),
        )
        svc._invalidate_summary_cache()
        from_buffer = svc.get_summary(hours=24)

        assert set(from_db) == set(from_buffer), (
            f"חוזה שונה בין המסלולים: {set(from_db) ^ set(from_buffer)}"
        )
        assert from_db == from_buffer, "אותם שדות אבל ערכים שונים כששניהם ריקים"

    def test_the_fallback_counts_unique_patterns_within_the_window_only(self, svc, now, monkeypatch):
        """‏``unique_patterns`` נספר על הרשומות שבחלון, כמו ``$addToSet`` במסלול ה-DB.

        קודם הוא היה ``len(self._query_patterns)`` — כל הדפוסים מאז עליית
        התהליך, בלי שום קשר לחלון שהתבקש.
        """
        monkeypatch.setattr(
            svc, "_calculate_summary_sync",
            lambda hours=PROFILER_WINDOW_HOURS: (_ for _ in ()).throw(RuntimeError("down")),
        )

        svc.record_slow_query_sync(
            collection="b", operation="find", query={"x": 1}, execution_time_ms=500.0
        )
        _seed_ancient_into_buffer(svc, now)

        assert svc.get_summary(hours=24)["unique_patterns"] == 2
        assert svc.get_summary(hours=24 * 7)["unique_patterns"] == 3

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

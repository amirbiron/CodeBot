"""החוזה של עוזרי שאילתת הטיימליין — בלי מונגו, ברמת היחידה.

הבדיקות כאן משלימות את ``test_dashboard_activity_files_endpoint``: שם
נבדקת ההתנהגות מקצה לקצה מול מסד אמיתי, וכאן נבדקים החוזה של ערך
ההחזרה והפרמטרים שנשלחים בפועל לשאילתה.
"""

import pytest

from pymongo.errors import OperationFailure

import webapp.app as wa


class _RaisingColl:
    """אוסף שכל ``aggregate`` עליו נכשל, כמו מסד שאינו זמין."""

    def aggregate(self, pipeline, **kwargs):
        raise OperationFailure("boom")


class _SpyColl:
    """אוסף שמתעד את ה-kwargs שנשלחו, כדי לבדוק פרמטרים ולא מחרוזות."""

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.calls = []

    def aggregate(self, pipeline, **kwargs):
        self.calls.append({"pipeline": pipeline, "kwargs": kwargs})
        return list(self.rows)


class _DB:
    def __init__(self, coll):
        self.code_snippets = coll


def test_a_failed_count_returns_none_and_not_zero():
    """‏``None`` = לא הצלחנו לספור. ``0`` = באמת אין קבצים.

    ההבחנה אינה קוסמטית: אפס מסיר את כפתור "טען עוד" אצל הלקוח, ולכן
    כשל שנבלע לאפס היה מסתיר קבצים קיימים.
    """
    assert wa._timeline_recent_files_count(_DB(_RaisingColl()), {}) is None


def test_an_empty_result_still_counts_as_zero():
    """אפס אמיתי נשאר אפס — אחרת ההבחנה חסרת ערך."""
    assert wa._timeline_recent_files_count(_DB(_SpyColl(rows=[])), {}) == 0
    assert wa._timeline_recent_files_count(_DB(_SpyColl(rows=[{"n": 4}])), {}) == 4


def test_both_aggregations_pass_allow_disk_use():
    """הפרמטר נבדק על הקריאה בפועל, לא על נוכחות מחרוזת בקוד."""
    coll = _SpyColl(rows=[{"n": 1}])
    wa._timeline_recent_files_count(_DB(coll), {})
    assert coll.calls[-1]["kwargs"].get("allowDiskUse") is True, coll.calls[-1]["kwargs"]

    coll2 = _SpyColl(rows=[])
    wa._timeline_latest_files(_DB(coll2), {}, limit=5)
    assert coll2.calls[-1]["kwargs"].get("allowDiskUse") is True, coll2.calls[-1]["kwargs"]


def test_the_sort_has_a_fallback_and_a_tiebreaker():
    """הצינור ממיין לפי מפתח עם נפילה ל-``created_at``, ושובר שוויון ב-``_id``.

    ``$sort`` אינו יציב, ושדה חסר מושווה כ-``null`` שנמוך מ-``Date``.
    שתי התכונות נבדקות על הצינור שנבנה, כי הן קובעות את הסדר לפני
    ה-``$skip``.
    """
    coll = _SpyColl(rows=[])
    wa._timeline_latest_files(_DB(coll), {}, skip=3, limit=5)
    pipeline = coll.calls[-1]["pipeline"]

    add_fields = [s for s in pipeline if "$addFields" in s]
    assert add_fields, pipeline
    assert add_fields[0]["$addFields"]["_sort_at"] == {"$ifNull": ["$updated_at", "$created_at"]}

    # שלב המיון האחרון הוא זה שקובע את סדר הדפדוף
    sorts = [s["$sort"] for s in pipeline if "$sort" in s]
    final_sort = sorts[-1]
    assert list(final_sort.items()) == [("_sort_at", -1), ("_id", -1)], final_sort

    # והדילוג בא אחרי המיון, אחרת הוא מדלג על סדר שרירותי
    stage_names = [next(iter(s)) for s in pipeline]
    assert stage_names.index("$skip") > stage_names.index("$sort"), stage_names


@pytest.mark.parametrize(
    "counted,shown_total,page_len,page_size,expected",
    [
        (10, 4, 4, 12, 6),      # ספירה ידועה — חשבון פשוט
        (4, 4, 4, 12, 0),       # הכול הוצג
        (2, 5, 5, 12, 0),       # לא יורד מתחת לאפס
        (None, 12, 12, 12, 1),  # לא ידוע + עמוד מלא ⇒ כנראה יש עוד
        (None, 15, 3, 12, 0),   # לא ידוע + עמוד חלקי ⇒ סיימנו
    ],
)
def test_more_files_rule(counted, shown_total, page_len, page_size, expected):
    """‏``shown_total`` ו-``page_len`` אינם אותו דבר, ובכוונה.

    כשהספירה ידועה קובע הסך הכול; כשאינה ידועה קובע רק האם העמוד הנוכחי
    התמלא. בעמוד הראשון הם מתלכדים, ובדפדוף נפרדים — ולכן שתי השורות
    האחרונות כאן הן המקרה שמבחין ביניהם.
    """
    assert wa._timeline_more_files(
        counted, shown_total=shown_total, page_len=page_len, page_size=page_size
    ) == expected

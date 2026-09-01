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
    "counted,shown_total,has_more,expected",
    [
        (10, 4, True, 6),      # ספירה ידועה — חשבון פשוט
        (4, 4, False, 0),      # הכול הוצג
        (2, 5, False, 0),      # לא יורד מתחת לאפס
        (None, 12, True, 1),   # לא ידוע + יש שורה נוספת ⇒ יש עוד
        (None, 12, False, 0),  # לא ידוע + אין שורה נוספת ⇒ סיימנו
        # מרוץ: הספירה אומרת "אין עוד" אבל ה-look-ahead מצא שורה נוספת.
        # עדיף כפתור מיותר על הסתרת קבצים.
        (4, 4, True, 1),
    ],
)
def test_more_files_rule(counted, shown_total, has_more, expected):
    """‏``has_more`` הוא עובדה מה-look-ahead, ולא אומדן מגודל העמוד.

    לפני כן הוסק "יש עוד" מכך שהעמוד התמלא, ולכן מספר קבצים שהוא כפולה
    מדויקת של גודל העמוד ייצר לחיצה נוספת שחוזרת ריקה.
    """
    assert wa._timeline_more_files(
        counted, shown_total=shown_total, has_more=has_more
    ) == expected


def test_the_page_helper_fetches_one_row_beyond_the_page():
    """‏look-ahead: שולפים ``limit + 1`` ומחזירים ``limit``.

    השורה העודפת אינה מוצגת — היא רק התשובה לשאלה "יש עוד?", וכך
    ההחלטה מבוססת על עובדה במקום על ניחוש מגודל העמוד.
    """
    rows = [{"_id": i, "file_name": f"f{i}"} for i in range(6)]
    coll = _SpyColl(rows=rows)
    page, has_more = wa._timeline_latest_files_page(_DB(coll), {}, limit=5)

    assert len(page) == 5, "הוחזרו יותר שורות מגודל העמוד"
    assert has_more is True
    limits = [s["$limit"] for s in coll.calls[-1]["pipeline"] if "$limit" in s]
    assert limits == [6], f"לא נשלפה שורה מעבר לעמוד: {limits}"


def test_the_page_helper_reports_no_more_on_an_exact_multiple():
    """המקרה שנשבר: בדיוק ``limit`` שורות ⇒ **אין** עוד.

    עמוד שהתמלא בדיוק אינו מעיד שיש המשך, וזו הייתה ההנחה השגויה שגרמה
    לכפולה מדויקת של קבצים להציג לחיצה שחוזרת ריקה.
    """
    rows = [{"_id": i, "file_name": f"f{i}"} for i in range(5)]
    coll = _SpyColl(rows=rows)
    page, has_more = wa._timeline_latest_files_page(_DB(coll), {}, limit=5)

    assert len(page) == 5
    assert has_more is False, "עמוד מלא בדיוק דווח כאילו יש אחריו עוד"


class _NoKwargsColl:
    """אוסף ש-``aggregate`` שלו אינו מקבל ``allowDiskUse``.

    זו בדיוק הצורה של סטאבים ומוקים בריפו, ולכן הפולבק על ``TypeError``
    קיים כאן כמו ב-``_aggregate_code_snippets``.
    """

    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.calls = 0

    def aggregate(self, pipeline):
        self.calls += 1
        return list(self.rows)


def test_a_stub_without_allow_disk_use_still_works():
    """סטאב שאינו מקבל את הפרמטר אינו מפיל את השאילתה.

    בלי הפולבק ה-``TypeError`` היה עולה מ-``_timeline_recent_files_count``
    (שתופס ``PyMongoError`` בלבד) ומגיע עד לראוט כ-500.
    """
    coll = _NoKwargsColl(rows=[{"n": 3}])
    assert wa._timeline_recent_files_count(_DB(coll), {}) == 3
    assert coll.calls == 1

    coll2 = _NoKwargsColl(rows=[{"_id": 1, "file_name": "a"}])
    page, has_more = wa._timeline_latest_files_page(_DB(coll2), {}, limit=5)
    assert len(page) == 1 and has_more is False

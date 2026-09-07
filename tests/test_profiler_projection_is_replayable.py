"""‏``$project`` שנשמר ב-``query_raw`` — האם הוא עדיין אותה שאילתה.

**הבאג שהקובץ הזה נולד ממנו.** בפרודקשן נשמרו 15 שאילתות עם ערכים
אמיתיים, וכל 15 הכילו ``$project``. השלד החליף את דגלי ההיטלה
ב-``"<value>"``, ו-``_raw_pipeline`` לא שחזר אותם — כי ``$project`` לא
סווג כשלב מבנה. התוצאה לא הייתה "היטלה מוסתרת" אלא **פעולה אחרת**:

.. code-block:: text

    {"$project": {"file_name": "<value>"}}
        ← מונגו קוראת ←
    {"$project": {"file_name": {"$const": "<value>"}}}

כלומר "החזר את הקבוע ``<value>``" במקום "החזר את השדה ``file_name``".
ובניגוד ל-``$limit``, מחרוזת בהיטלה **אינה** גורמת למונגו לזרוק, ולכן גם
``_fix_pipeline_for_explain`` — שמתקנת רק את השלבים שזורקים — לא נגעה בה.
הכשל היה שקט לחלוטין.

**למה הבדיקות כאן ולא ``assert "$project" in ...``.** הצרכן של
``query_raw`` הוא ``explain`` של מונגו, לא מילון בפייתון. בדיקה שמאשרת
שהמילון נראה נכון היא בדיוק ``TESTING-PATTERNS.md`` T1(a) — היא מוכיחה
שהפונקציה לא קרסה, לא שהפיצ'ר עובד. לכן שכבת הבדיקות כאן כפולה: לוגיקה
בפייתון טהור, ובנוסף ``tests/test_profiler_projection_mongo.py`` שמריץ
את התוצאה דרך ``explain`` האמיתי ומשווה ``queryShapeHash``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.query_profiler_service import PersistentQueryProfilerService

ME = 6865105071

#: הפייפליין שנשמר בפועל 15 פעמים ב-``slow_queries_log``. ה-``$project``
#: כאן הוא הצורה המדויקת שהגיעה מ-``get_user_files``.
PRODUCTION_FILE_LIST = [
    {"$match": {"user_id": ME, "is_active": True}},
    {"$sort": {"file_name": 1, "version": -1}},
    {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
    {"$replaceRoot": {"newRoot": "$latest"}},
    {"$sort": {"updated_at": -1}},
    {"$project": {"file_name": 1, "programming_language": 1, "tags": 1, "code": 1}},
    {"$skip": 200},
    {"$limit": 200},
]


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("PROFILER_UNREDACTED_USER_IDS", str(ME))
    manager = MagicMock()
    manager.db = None  # ההחלטה על הערכים אינה נוגעת ב-DB
    return PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)


def _project_of(service, pipeline):
    """שלב ה-``$project`` כפי שהוא **נשמר**, או ``None`` אם השאילתה נדחתה."""
    raw, _owner, reason = service._decide_raw_query("aggregate", {"pipeline": pipeline})
    if raw is None:
        return None, reason
    for stage in raw["pipeline"]:
        if "$project" in stage:
            return stage["$project"], reason
    return None, reason


class TestTheProductionShape:
    def test_the_saved_projection_is_the_real_one(self, svc):
        """הבדיקה שנולדה מ-15 הרשומות. בלי התיקון כל הערכים כאן ``"<value>"``."""
        saved, reason = _project_of(svc, PRODUCTION_FILE_LIST)

        assert reason is None, f"השאילתה נדחתה: {reason}"
        assert saved == {"file_name": 1, "programming_language": 1, "tags": 1, "code": 1}

    def test_no_placeholder_survives_anywhere_in_the_pipeline(self, svc):
        """‏``<value>`` במקום כלשהו פירושו שלב שיתפרש אחרת ממה שרץ."""
        raw, _owner, _reason = svc._decide_raw_query("aggregate", {"pipeline": PRODUCTION_FILE_LIST})

        assert "<value>" not in repr(raw), f"נשאר placeholder: {raw}"


class TestAllOrNothing:
    """‏שלב מעורב חוזר כשלד **שלם**, ולא כתערובת.

    זו הדרישה המרכזית: תיקון חלקי שמשאיר חלק מהמפתחות אמיתיים וחלק
    ``<value>`` הוא בדיוק המצב שלפני התיקון, בקנה מידה קטן יותר — שלב
    שנראה שלם ומתפרש אחרת ממה שרץ.
    """

    def test_a_mixed_projection_is_skeletonised_entirely(self, svc):
        """דגלים **וגם** ביטוי באותו שלב ← כל השלב שלד."""
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {
            "file_name": 1,
            "snippet": {"$substrCP": ["$code", 0, 200]},
        }}

        saved, reason = _project_of(svc, pipeline)

        assert reason is None, f"השאילתה נדחתה במקום ליפול לשלד: {reason}"
        assert saved["file_name"] == "<value>", (
            f"דגל אמיתי דלף משלב מעורב: {saved}"
        )

    def test_a_mixed_projection_does_not_reject_the_whole_query(self, svc):
        """‏``$project`` שאינו דגלים הוא לגיטימי — הוא ביטוי.

        ההבדל מ-``$limit``: שם ערך פגום פוסל את כל הרשומה
        (``malformed_stage:``), כי ``$limit`` שגוי הוא שאילתה שאי אפשר
        לתאר. כאן זריקה הייתה מוחקת מהדוח שאילתות תקינות לגמרי.
        """
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {"total": {"$sum": "$file_size"}}}

        raw, _owner, reason = svc._decide_raw_query("aggregate", {"pipeline": pipeline})

        assert reason is None
        assert raw is not None, "שאילתה תקינה נפסלה בגלל ביטוי בהיטלה"
        assert raw["pipeline"][0]["$match"]["user_id"] == ME, "ה-$match נפגע"


class TestAUserIdCannotHideInAProjection:
    """‏התיעוד: *"Non-zero integers are also treated as true"*.

    כלומר ``{"$project": {"file_name": 6865105071}}`` הוא היטלת הכללה
    **חוקית לגמרי**. סריקת הבעלות עוברת על גופי ``$match`` בלבד ולעולם לא
    תראה אותו, ולכן הדבר היחיד שמונע אותו הוא צרוּת הוולידציה.

    מקור: https://www.mongodb.com/docs/manual/reference/operator/aggregation/project/
    """

    @pytest.mark.parametrize("disguised", [ME, 42, -7, 999999999999])
    def test_an_integer_that_is_not_zero_or_one_is_not_kept(self, svc, disguised):
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {"file_name": disguised}}

        saved, _reason = _project_of(svc, pipeline)

        assert saved == {"file_name": "<value>"}, (
            f"מספר שאינו 0/1 נשמר אמיתי ויכול לשאת מזהה: {saved}"
        )

    def test_a_float_flag_is_not_kept_either(self, svc):
        """‏``1.0`` חוקי במונגו, ולא כאן. צר יותר מהמנוע — וזה המצב הרצוי."""
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {"file_name": 1.0}}

        saved, _reason = _project_of(svc, pipeline)

        assert saved == {"file_name": "<value>"}


class TestTheFormsThatAreStructure:
    def test_exclusion_flags_are_kept(self, svc):
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {"_id": 0, "code": 0}}

        saved, _reason = _project_of(svc, pipeline)

        assert saved == {"_id": 0, "code": 0}

    def test_booleans_are_kept_as_booleans(self, svc):
        """‏``True`` אינו ``1``. ב-Python ``isinstance(True, int)`` אמת, ולכן
        סדר הבדיקות בקוד חייב לשים ``bool`` ראשון — אחרת הוא היה נשמר כמספר.
        """
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {"file_name": True, "code": False}}

        saved, _reason = _project_of(svc, pipeline)

        assert saved == {"file_name": True, "code": False}
        assert saved["file_name"] is True, "בוליאני הומר למספר"

    def test_a_field_path_value_is_kept(self, svc):
        """נתיב שדה נושא **שם** של שדה, לא ערך שלו."""
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {"name": "$file_name", "root": "$$ROOT"}}

        saved, _reason = _project_of(svc, pipeline)

        assert saved == {"name": "$file_name", "root": "$$ROOT"}

    def test_a_nested_inclusion_is_kept(self, svc):
        """‏``contact: {address: {country: 1}}`` — צורה שהתיעוד מאשר במפורש."""
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {"contact": {"address": {"country": 1}}}}

        saved, _reason = _project_of(svc, pipeline)

        assert saved == {"contact": {"address": {"country": 1}}}

    def test_a_nested_expression_is_not_kept(self, svc):
        """מפתח שמתחיל ב-``$`` הוא אופרטור, כלומר ביטוי — ולא מבנה.

        ⚠️ **הביטוי כאן נושא ליטרל בכוונה.** ביטוי שבנוי כולו מנתיבי שדה,
        למשל ``{"$strLenBytes": "$code"}``, כבר עובר את המנרמל **שלם** —
        הוא משאיר מחרוזות שמתחילות ב-``$`` כפי שהן. במקרה כזה "מבנה" ו-
        "שלד" מפיקים בדיוק אותו פלט, והבדיקה לא הייתה מסוגלת להבחין
        ביניהם. ה-``100`` הוא מה שהופך את ההבדל לנראה.
        """
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {"size": {"$add": ["$file_size", 100]}}}

        saved, _reason = _project_of(svc, pipeline)

        assert saved == {"size": {"$add": ["$file_size", "<value>"]}}

    def test_an_expression_nested_two_levels_down_is_caught(self, svc):
        """הרקורסיה חייבת לרדת עד הסוף, לא רק רמה אחת.

        ``{"a": {"b": …}}`` נראה כמו היטלה מקוננת עד הרמה השלישית, ורק שם
        מתגלה ה-``$literal``. בדיקה ברמה אחת בלבד הייתה מסווגת את זה כמבנה
        ושומרת את המזהה אמיתי.
        """
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$project": {"a": {"b": {"$literal": ME}}}}

        saved, _reason = _project_of(svc, pipeline)

        assert saved == {"a": {"b": {"$literal": "<value>"}}}, (
            f"מזהה דלף דרך ביטוי עמוק: {saved}"
        )


class TestNothingElseWasOpened:
    """ההיקף שנבחר במפורש — ומה שנשאר בחוץ, נשאר בחוץ."""

    def test_add_fields_is_still_skeletonised(self, svc):
        """‏``$addFields`` הושאר בחוץ בכוונה: אין לו היום מופע שנחסם,
        והסיכון לקבוע חופשי בתוכו גבוה בהרבה מאשר בהיטלה.
        """
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$addFields": {"flag": 1}}

        raw, _owner, _reason = svc._decide_raw_query("aggregate", {"pipeline": pipeline})

        assert raw["pipeline"][5] == {"$addFields": {"flag": "<value>"}}

    def test_the_aggregation_unset_is_still_skeletonised(self, svc):
        """‏``$unset`` של אגרגציה אינו בשימוש בריפו — תשעת המופעים הם
        אופרטור ה-update ``{"$unset": {...}}``, דבר אחר לגמרי. בלי מופע
        אמיתי לאמת מולו הוא נשאר בחוץ.
        """
        pipeline = list(PRODUCTION_FILE_LIST)
        pipeline[5] = {"$unset": "code"}

        raw, _owner, _reason = svc._decide_raw_query("aggregate", {"pipeline": pipeline})

        assert raw["pipeline"][5] == {"$unset": "<value>"}

    def test_an_unknown_field_in_match_is_still_withheld(self, svc):
        """התיקון נגע בהיטלה בלבד. גדר הסינון לא זזה."""
        pipeline = [{"$match": {"user_id": ME, "shared_with": 42}}]

        _raw, _owner, reason = svc._decide_raw_query("aggregate", {"pipeline": pipeline})

        assert reason == "unknown_field:shared_with"

    def test_a_vector_query_is_still_withheld(self, svc):
        pipeline = [{"$vectorSearch": {"index": "vector_index", "path": "snippetEmbedding"}}]

        _raw, _owner, reason = svc._decide_raw_query("aggregate", {"pipeline": pipeline})

        assert reason == "vector_query"

"""‏``_decide_raw_query`` מול **הצורות שהריפו באמת בונה**.

**למה לא טסט על תוכן הרשימה.** ``assert "code" in RAW_QUERY_ALLOWED_FIELDS``
מאשר את עצמו: הוא מעתיק את ההחלטה במקום לבדוק אותה, והוא ימשיך לעבור גם אם
שאילתה אמיתית תפסיק לעבור. הטסטים כאן מריצים את ההחלטה על הפייפליינים שהקוד
מייצר, ולכן הם נשברים ברגע שמישהו מוסיף סינון על שדה חדש — וזה בדיוק מה
שרוצים לתפוס.

**הצורות מגיעות ממקום מוגדר בקוד ולא מהזיכרון:**

=========================================  ==============================================
הצורה                                       מי בונה אותה
=========================================  ==============================================
חיפוש עם ``$regex`` על ``code``             ``webapp/app.py`` — הפולבאק של החיפוש
חיפוש עם ``$text``                          אותו מקום, המסלול המהיר
רשימת הקבצים / חיפוש תוכן                   ``search_engine._content_search`` ← ``get_user_files``
העמוד השני של ``/files``                    שאילתת הקורסור
=========================================  ==============================================

הצורה הראשונה **נדחתה בפרודקשן** ב-``unknown_field:code``, והיא הסיבה
לקובץ הזה.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from bson import ObjectId

from services.query_profiler_service import PersistentQueryProfilerService

ME = 6865105071
WHEN = datetime(2026, 9, 7, 12, 0, 0)
OID = ObjectId("6a8e6c04cfb3849504b6e210")

#: הפייפליין של החיפוש כשהמסלול המהיר נכשל. ``$match`` הראשון הוא מה שנבדק;
#: שאר השלבים כאן כדי שהצורה תהיה אמיתית ולא מקוצצת.
SEARCH_REGEX_PIPELINE = [
    {"$match": {"user_id": ME, "is_active": True, "code": {"$regex": "סטיקי", "$options": "i"}}},
    {"$sort": {"file_name": 1, "version": -1}},
    {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
    {"$replaceRoot": {"newRoot": "$latest"}},
    {"$addFields": {"_m": {"$regexFind": {"input": "$code", "regex": "סטיקי", "options": "i"}}}},
    {"$project": {"code": 0, "_m": 0}},
    {"$sort": {"updated_at": -1}},
    {"$limit": 50},
]

SEARCH_TEXT_PIPELINE = [
    {"$match": {"user_id": ME, "is_active": True, "$text": {"$search": "סטיקי"}}},
    {"$sort": {"file_name": 1, "version": -1}},
    {"$limit": 50},
]

#: ``_content_search`` ורשימת הקבצים — ``get_user_files``.
USER_FILES_PIPELINE = [
    {"$match": {"is_active": True, "user_id": ME}},
    {"$sort": {"file_name": 1, "version": -1}},
    {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
    {"$replaceRoot": {"newRoot": "$latest"}},
    {"$sort": {"updated_at": -1}},
    {"$project": {"code": 1, "file_name": 1, "programming_language": 1, "tags": 1, "updated_at": 1}},
    {"$skip": 200},
    {"$limit": 200},
]

#: העמוד השני של ``/files`` — שאילתת הקורסור, זו שכל הפיצ'ר נבנה בשבילה.
FILES_CURSOR_QUERY = {
    "user_id": ME,
    "$and": [
        {"is_active": True},
        {"$or": [
            {"created_at": {"$lt": WHEN}},
            {"$and": [{"created_at": {"$eq": WHEN}}, {"_id": {"$lt": OID}}]},
        ]},
    ],
}


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("PROFILER_UNREDACTED_USER_IDS", str(ME))
    manager = MagicMock()
    manager.db = None  # ההחלטה על הערכים אינה נוגעת ב-DB
    return PersistentQueryProfilerService(db_manager=manager, slow_threshold_ms=100)


def _decide(service, operation, query):
    raw, owner, reason = service._decide_raw_query(operation, query)
    return raw, owner, reason


class TestTheQueryFamiliesTheRepoBuilds:
    def test_the_search_that_was_rejected_in_production_is_accepted(self, svc):
        """‏**הטסט שנולד מהדחייה.**

        השאילתה הזו נדחתה ב-``unknown_field:code``, והיא הייתה האיטית ביותר
        שנרשמה. ניתוח שלה על השלד מריץ ``explain`` על ``{"code": {"$regex":
        "<value>"}}`` — regex שלא מתאים כמעט לכלום — ולכן הדוח מדווח "מהיר,
        אפס מסמכים נסרקו" **על השאילתה האיטית ביותר במערכת**.
        """
        raw, owner, reason = _decide(svc, "aggregate", {"pipeline": SEARCH_REGEX_PIPELINE})

        assert reason is None, f"נדחתה: {reason}"
        assert owner == str(ME)
        assert raw is not None

    def test_and_the_search_pattern_survives_as_the_real_pattern(self, svc):
        """לא מספיק ש"התקבלה" — הערך שנשמר חייב להיות הדפוס האמיתי.

        ``json_util`` ממיר ``{"$regex": …, "$options": …}`` ל-``Regex`` — זו
        גם צורת הייצוג של regex ב-Extended JSON, ולכן הדפוס והדגלים עוברים
        באותו מנגנון בלי לאבד דבר.
        """
        raw, _owner, _reason = _decide(svc, "aggregate", {"pipeline": SEARCH_REGEX_PIPELINE})

        saved = raw["pipeline"][0]["$match"]["code"]
        assert getattr(saved, "pattern", None) == "סטיקי", f"הדפוס לא שרד: {saved!r}"

    def test_the_fast_path_with_text_is_accepted_too(self, svc):
        """המסלול המהיר של אותה פונקציה. כאן כדי שהוספת ``code`` לא תשבור אותו."""
        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": SEARCH_TEXT_PIPELINE})

        assert reason is None, f"נדחתה: {reason}"

    def test_the_content_search_and_file_list_query_is_accepted(self, svc):
        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": USER_FILES_PIPELINE})

        assert reason is None, f"נדחתה: {reason}"

    def test_the_files_cursor_query_is_accepted(self, svc):
        raw, _owner, reason = _decide(svc, "find", FILES_CURSOR_QUERY)

        assert reason is None, f"נדחתה: {reason}"
        assert raw["$and"][1]["$or"][0]["created_at"]["$lt"] == WHEN


class TestNothingWasOpenedUp:
    """‏``code`` נוסף לרשימה — ולא נפתח שום דבר אחר."""

    def test_a_worker_query_without_an_owner_is_still_withheld(self, svc):
        """שאילתת ה-worker אינה מצהירה על בעלים, ולכן היא נדחית לפני בדיקת השדות.

        זו גם ההוכחה לכלל שכתוב בהערה מעל הרשימה: שדות ה-worker לעולם אינם
        מגיעים אליה, ולכן אין שום סיבה להוסיף אותם.
        """
        pipeline = [{"$match": {"needs_embedding": True, "chunkerVersion": {"$lt": 3}}}]

        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": pipeline})

        assert reason == "owner_missing"

    def test_an_unknown_field_is_still_withheld(self, svc):
        pipeline = [{"$match": {"user_id": ME, "shared_with": 42}}]

        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": pipeline})

        assert reason == "unknown_field:shared_with"

    def test_another_users_id_is_still_withheld(self, svc):
        pipeline = [{"$match": {"user_id": ME}}, {"$match": {"user_id": 999}}]

        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": pipeline})

        assert reason == "owner_mismatch"

    def test_a_vector_search_is_still_withheld(self, svc):
        """החיפוש הסמנטי נדחה בכוונה, ולא בגלל שדה."""
        pipeline = [{"$vectorSearch": {"index": "vector_index", "path": "snippetEmbedding"}}]

        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": pipeline})

        assert reason == "vector_query"


class TestCodeIsAllowedOnlyAsASearchPattern:
    """‏``code`` נכנס לרשימה כדפוס חיפוש — ורק ככזה.

    זה נתפס בריוויו: רשימת האופרטורים הכללית מתירה לכל שדה גם ``$eq``,
    ``$in`` ו-``$all``. ההערה שכתבתי טענה ש-``code`` "תמיד בצד השמאלי של
    ``$regex``", אבל זו הייתה טענה על הקוראים של **היום** ולא אילוץ. תנאי
    שוויון על ``code`` הוא דבר אחר לגמרי — הוא נושא את **תוכן הקובץ**.
    """

    def test_an_equality_on_code_is_withheld(self, svc):
        """‏``{"code": "<תוכן הקובץ>"}`` — הצורה שהייתה שומרת קוד מקור.

        בלי ההגבלה, עד ``PROFILER_UNREDACTED_MAX_BYTES`` של קוד היו נשמרים
        ב-``slow_queries_log`` לשבוע, מוצגים בדשבורד, ונכנסים לטקסט
        "העתק דוח ל-AI".
        """
        pipeline = [{"$match": {"user_id": ME, "code": "def secret():\n    return 1"}}]

        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": pipeline})

        assert reason == "unsupported_field_value:code"

    @pytest.mark.parametrize("operator", ["$eq", "$in", "$all", "$ne"])
    def test_other_operators_on_code_are_withheld(self, svc, operator):
        pipeline = [{"$match": {"user_id": ME, "code": {operator: "def secret(): ..."}}}]

        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": pipeline})

        assert reason == f"unsupported_field_operator:code{operator}"

    def test_the_search_pattern_itself_still_passes(self, svc):
        """ההגבלה לא סוגרת את מה שהיא נועדה לאפשר."""
        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": SEARCH_REGEX_PIPELINE})

        assert reason is None

    def test_the_restriction_applies_only_to_code(self, svc):
        """שדה אחר ממשיך לקבל את מלוא רשימת האופרטורים."""
        pipeline = [{"$match": {"user_id": ME, "file_name": {"$in": ["app.py", "main.py"]}}}]

        _raw, _owner, reason = _decide(svc, "aggregate", {"pipeline": pipeline})

        assert reason is None

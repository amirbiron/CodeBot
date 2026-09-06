"""הצינור ההיברידי: רף על ציון הווקטור, ו-numCandidates שגדל עם הקורפוס.

הרקע (אישו #3332):

1. חיפוש וקטורי תמיד ממלא את ה-``limit``. בלי רף, שאילתה עם שלוש תוצאות
   טובות מחזירה עוד שבע שנכנסו רק כי היה מקום. דוגמה מאומתת מהפרודקשן:
   חיפוש "open" החזיר את ``snippet_chunks.json``, שהמילה אינה מופיעה בו
   אפילו פעם אחת.
2. ``numCandidates = limit * 20`` הוא מספר קבוע שאינו תלוי בגודל הקורפוס.
   עם ``limit=10`` הוא 200 מועמדים — 5.7% מ-3,483 צ'אנקים, ורק 1.2%
   מ-17,000 אחרי הקטנת הצ'אנקים. אותו מספר בדיוק פוגע ברקול ככל שהקורפוס
   גדל, וזה היה נראה כאילו הצ'אנקים הקטנים הרעו את החיפוש.
"""

import pytest

import search_engine
from config import config


def _pipeline(**kwargs):
    params = dict(
        user_id=1,
        query="open",
        query_embedding=[0.1] * 768,
        limit=10,
    )
    params.update(kwargs)
    return search_engine._build_hybrid_search_pipeline(**params)


def _vector_stage(pipeline):
    return pipeline[0]["$vectorSearch"]


def _score_matches(pipeline):
    return [
        stage for stage in pipeline
        if "$match" in stage and "vectorScore" in stage["$match"]
    ]


class TestVectorScoreFloor:
    def test_floor_is_applied_when_configured(self, monkeypatch):
        monkeypatch.setattr(config, "SEMANTIC_MIN_VECTOR_SCORE", 0.62, raising=False)
        pipeline = _pipeline()

        matches = _score_matches(pipeline)
        assert len(matches) == 1, "vector score floor is missing from the pipeline"
        assert matches[0]["$match"]["vectorScore"] == {"$gte": 0.62}

    def test_floor_comes_after_the_score_is_computed(self, monkeypatch):
        """``$vectorSearch`` חייב להישאר ה-stage הראשון, וה-``$match`` אחרי
        ה-``$addFields`` שמחשב את ``vectorScore``."""
        monkeypatch.setattr(config, "SEMANTIC_MIN_VECTOR_SCORE", 0.5, raising=False)
        pipeline = _pipeline()

        assert "$vectorSearch" in pipeline[0]
        add_fields_index = next(
            i for i, s in enumerate(pipeline)
            if "$addFields" in s and "vectorScore" in s["$addFields"]
        )
        match_index = next(
            i for i, s in enumerate(pipeline)
            if "$match" in s and "vectorScore" in s["$match"]
        )
        assert match_index > add_fields_index

    def test_floor_does_not_touch_the_text_branch(self, monkeypatch):
        """התאמה לקסיקלית היא כבר ראיה בפני עצמה — הרף לא חל עליה."""
        monkeypatch.setattr(config, "SEMANTIC_MIN_VECTOR_SCORE", 0.5, raising=False)
        pipeline = _pipeline()

        union = next(s for s in pipeline if "$unionWith" in s)
        sub_pipeline = union["$unionWith"]["pipeline"]
        assert not _score_matches(sub_pipeline)

    def test_floor_is_omitted_when_disabled(self, monkeypatch):
        """0 = כבוי. ברירת המחדל, עד שהערך יכויל על נתונים אמיתיים."""
        monkeypatch.setattr(config, "SEMANTIC_MIN_VECTOR_SCORE", 0.0, raising=False)
        assert _score_matches(_pipeline()) == []

    def test_rrf_floor_is_unchanged(self):
        """הרף החדש הוא על סקאלה אחרת. ``MIN_RRF_SCORE`` נשאר כפי שהוא —
        סף שנבחר בטעות על הסקאלה הלא נכונה כבר סינן פעם אחת את כל התוצאות."""
        assert search_engine.MIN_RRF_SCORE == 0.005

    @pytest.mark.parametrize("configured,expected", [(-1.0, 0.0), (5.0, 1.0), ("x", 0.0)])
    def test_floor_is_clamped_to_a_valid_score_range(self, monkeypatch, configured, expected):
        monkeypatch.setattr(config, "SEMANTIC_MIN_VECTOR_SCORE", configured, raising=False)
        assert search_engine._semantic_min_vector_score() == expected


class TestNumCandidates:
    def test_uses_the_configured_floor(self, monkeypatch):
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES", 1000, raising=False)
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES_MAX", 10000, raising=False)

        assert _vector_stage(_pipeline(limit=10))["numCandidates"] == 1000

    def test_the_documented_20x_ratio_still_wins_for_large_limits(self, monkeypatch):
        """מקור: תיעוד ``$vectorSearch`` — "at least 20 times higher than limit"."""
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES", 1000, raising=False)
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES_MAX", 10000, raising=False)

        assert _vector_stage(_pipeline(limit=100))["numCandidates"] == 2000

    def test_is_capped(self, monkeypatch):
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES", 1000, raising=False)
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES_MAX", 1500, raising=False)

        assert _vector_stage(_pipeline(limit=100))["numCandidates"] == 1500

    def test_bad_config_does_not_break_search(self, monkeypatch):
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES", "nonsense", raising=False)
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES_MAX", None, raising=False)

        assert _vector_stage(_pipeline(limit=10))["numCandidates"] >= 200

    @pytest.mark.parametrize("ceiling", [10001, 50000, 10**9])
    def test_ceiling_never_exceeds_the_atlas_hard_limit(self, monkeypatch, ceiling):
        """נמדד מול ``ClusterFrankfurt``: ``numCandidates: 10001`` מוחזר עם
        ``"numCandidates" must be within bounds [1..10000]``, ו-10000 עובר.

        זה לא כשל תמים. השגיאה היא ``PlanExecutor error``, וה-``except`` של
        ``semantic_search`` היה בולע אותה ונופל בשקט לחיפוש טקסט בלבד — כלומר
        משתנה סביבה שהוגדר גבוה מדי היה מכבה את החיפוש הסמנטי בלי שאף אחד
        יידע.
        """
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES", 1000, raising=False)
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES_MAX", ceiling, raising=False)

        # ``limit=1000`` נותן ``limit * 20 = 20,000`` — מעל התקרה משני הכיוונים,
        # ולכן זה הערך היחיד שבאמת בוחן את הכליאה ולא את ה-20:1.
        assert _vector_stage(_pipeline(limit=1000))["numCandidates"] == 10000
        # וגם הרצפה של ``limit * 2`` (2,000) אינה גוברת על מגבלת Atlas.
        assert _vector_stage(_pipeline(limit=9000))["numCandidates"] == 10000

    def test_floor_above_the_ceiling_cannot_break_the_query(self, monkeypatch):
        """קונפיג הפוך (רצפה מעל תקרה) הוא שגיאת הפעלה, לא חיפוש מושבת."""
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES", 99999, raising=False)
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES_MAX", 50, raising=False)

        value = _vector_stage(_pipeline(limit=10))["numCandidates"]
        assert 1 <= value <= 10000

    @pytest.mark.parametrize("limit", [10, 50, 400])
    def test_candidates_are_never_fewer_than_the_results_requested(
        self, monkeypatch, limit
    ):
        """``$vectorSearch`` מבקש ``limit * 2`` תוצאות.

        פחות מועמדים ממספר התוצאות המבוקש היא בקשה חסרת משמעות: ``MAX=20``
        עם ``limit=50`` היה מבקש 20 מועמדים ו-100 תוצאות.
        """
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES", 20, raising=False)
        monkeypatch.setattr(config, "SEMANTIC_NUM_CANDIDATES_MAX", 20, raising=False)

        stage = _vector_stage(_pipeline(limit=limit))
        assert stage["numCandidates"] >= stage["limit"]

    def test_the_hard_limit_matches_what_atlas_actually_accepts(self):
        """הקבוע אינו מספר מהזיכרון — הוא נמדד מול הקלאסטר."""
        assert search_engine.SEMANTIC_NUM_CANDIDATES_HARD_MAX == 10000


def test_pipeline_still_filters_to_the_latest_active_version():
    """הגנה על ההתנהגות הקיימת: צ'אנקים של גרסה ישנה או של קובץ מחוק
    אינם עולים בתוצאות, גם לפני שג'וב הניקוי הגיע אליהם."""
    pipeline = _pipeline()
    text = repr(pipeline)
    assert "latestSnippetId" in text
    assert "is_active" in text


# --- בידוד בין משתמשים ב-``$lookup`` --------------------------------------
#
# הצינור לא נבדק כאן במחרוזות אלא **מורץ**: מנוע זעיר מעריך את ה-``$expr``
# שהקוד באמת בנה, מול מסמכים לדוגמה. אם התנאי על ``user_id`` יוסר, אם ``$and``
# יתחלף, או אם שם משתנה ה-``let`` ישתנה — התוצאה תשתנה והטסטים ייפלו. בדיקת
# מחרוזות לא הייתה תופסת אף אחד מהשלושה.


def _eval_expr(expr, doc, let_vars):
    """מעריך את תת-הקבוצה של שפת ה-``$expr`` שהצינור הזה משתמש בה."""
    if isinstance(expr, dict):
        if len(expr) != 1:
            raise AssertionError(f"unexpected expr shape: {expr}")
        op, args = next(iter(expr.items()))
        if op == "$and":
            return all(_eval_expr(a, doc, let_vars) for a in args)
        if op == "$or":
            return any(_eval_expr(a, doc, let_vars) for a in args)
        if op == "$eq":
            left, right = (_eval_expr(a, doc, let_vars) for a in args)
            return left == right
        raise AssertionError(f"unsupported operator {op}")
    if isinstance(expr, str) and expr.startswith("$$"):
        name = expr[2:]
        assert name in let_vars, f"expr uses undeclared let var {name}; let={let_vars}"
        return let_vars[name]
    if isinstance(expr, str) and expr.startswith("$"):
        cur = doc
        for part in expr[1:].split("."):
            cur = (cur or {}).get(part) if isinstance(cur, dict) else None
        return cur
    return expr


def _snippet_lookup(pipeline):
    """שלב ה-``$lookup`` הראשון: מהצ'אנק אל מסמך הסניפט שלו."""
    stages = [s["$lookup"] for s in pipeline if "$lookup" in s]
    assert stages, "the pipeline no longer joins the snippet document"
    return stages[0]


def _joins(lookup, chunk, snippet_doc):
    """האם ``snippet_doc`` היה מצטרף ל-``chunk``, לפי הצינור כפי שנבנה."""
    let_vars = {
        name: _eval_expr(expr, chunk, {})
        for name, expr in lookup["let"].items()
    }
    match = lookup["pipeline"][0]["$match"]
    for key, cond in match.items():
        if key == "$expr":
            if not _eval_expr(cond, snippet_doc, let_vars):
                return False
        elif snippet_doc.get(key) != cond:
            return False
    return True


class TestTenantIsolationInTheLookup:
    """הפילטר של ``$vectorSearch`` הוא על ה-``userId`` של **הצ'אנק**.

    הצטרפות לפי ``_id`` בלבד הייתה מחזירה את מסמך הסניפט של בעליו האמיתי —
    כלומר צ'אנק עם שיוך שגוי היה מציג למשתמש אחד שם קובץ, תיאור ותגיות של
    משתמש אחר. ``CRITICAL-PATTERNS.md`` K12.
    """

    CHUNK = {"snippetId": "snip-1", "userId": 7}

    def _lookup(self):
        return _snippet_lookup(_pipeline(user_id=7))

    def test_the_owners_own_snippet_joins(self):
        """המסלול התקין חייב להמשיך לעבוד — ``$expr`` שגוי היה מוחק תוצאות."""
        doc = {"_id": "snip-1", "user_id": 7, "is_active": True, "file_name": "a.py"}
        assert _joins(self._lookup(), self.CHUNK, doc) is True

    def test_another_users_snippet_never_joins(self):
        """אותו ``_id``, בעלים אחר. זו הדליפה."""
        doc = {"_id": "snip-1", "user_id": 9, "is_active": True, "file_name": "secret.py"}
        assert _joins(self._lookup(), self.CHUNK, doc) is False

    def test_a_different_snippet_of_the_same_user_never_joins(self):
        doc = {"_id": "snip-2", "user_id": 7, "is_active": True, "file_name": "b.py"}
        assert _joins(self._lookup(), self.CHUNK, doc) is False

    def test_a_trashed_snippet_never_joins(self):
        doc = {"_id": "snip-1", "user_id": 7, "is_active": False, "file_name": "a.py"}
        assert _joins(self._lookup(), self.CHUNK, doc) is False

    @pytest.mark.parametrize("owner", [9, "7", None, 0, -7])
    def test_no_owner_value_sneaks_through(self, owner):
        """כולל המקרים הדקים: מזהה כמחרוזת, ``None``, אפס, שלילי."""
        doc = {"_id": "snip-1", "user_id": owner, "is_active": True}
        assert _joins(self._lookup(), self.CHUNK, doc) is False

    def test_the_join_reads_the_chunks_own_owner_not_the_query_argument(self):
        """``$$owner_id`` נגזר מ-``$userId`` של הצ'אנק.

        אם היה נגזר מהארגומנט של השאילתה, צ'אנק עם שיוך שגוי היה עובר —
        בדיוק המקרה שהתנאי נועד לחסום.
        """
        lookup = self._lookup()
        assert lookup["let"]["owner_id"] == "$userId"
        foreign_chunk = {"snippetId": "snip-1", "userId": 9}
        doc = {"_id": "snip-1", "user_id": 7, "is_active": True}
        assert _joins(lookup, foreign_chunk, doc) is False

    def test_the_evaluator_can_actually_fail(self):
        """בקרה: מנוע שמחזיר תמיד ``False`` היה מפיל את הטסט הראשון.

        כאן מוכיחים את ההפך — הסרת התנאי על ``user_id`` מהצינור **כן** פותחת
        את הדליפה, כלומר הטסטים למעלה בודקים משהו.
        """
        lookup = self._lookup()
        stripped = {
            **lookup,
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$_id", "$$snippet_id"]}, "is_active": True}},
                *lookup["pipeline"][1:],
            ],
        }
        foreign = {"_id": "snip-1", "user_id": 9, "is_active": True}
        assert _joins(stripped, self.CHUNK, foreign) is True, "the evaluator is inert"
        assert _joins(lookup, self.CHUNK, foreign) is False

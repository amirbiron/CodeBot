"""ה-verbosity של explain חייב להגיע למונגו.

הרקע: הדשבורד ``/admin/profiler`` מציע תפריט "Explain Verbosity" עם ברירת מחדל
``queryPlanner`` שמסומנת "בטוחה". בפועל הערך נזרק, והשירות קרא
``cursor.explain(verbosity=...)`` — קריאה שנכשלת תמיד, כי ל-``Cursor.explain``
אין ומעולם לא היה פרמטר כזה (pymongo 4.15.3: ``def explain(self)``). ה-fallback
שרץ במקומה הוא ``allPlansExecution``, כלומר **המצב הכי אגרסיבי**, שמריץ את כל
תוכניות המועמדות — על שאילתות שכבר ידוע שהן איטיות.

הבדיקות כאן מקבעות שהערך שנבחר הוא הערך שנשלח.

הערה על היקף הטענות: הדמה מיירטת את ``Database.command``, ולכן נבדק **מה שאנחנו
מעבירים** — הארגומנטים לקריאה. מבנה מסמך הפקודה הסופי וסדר המפתחות בו נבנים
בתוך pymongo, וזה לא קוד שלנו ולא מה שהבדיקות האלה אמורות לאמת.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def service(monkeypatch):
    monkeypatch.delenv("PROFILER_EXPLAIN_MAX_TIME_MS", raising=False)
    from services.query_profiler_service import QueryProfilerService

    return QueryProfilerService(db_manager=_ManagerStub(), slow_threshold_ms=100)


class _DBStub:
    """דמה של ``Database`` שרושמת את הקריאות ל-``command``."""

    def __init__(self, result=None):
        self.calls: list[tuple] = []
        self._result = result if result is not None else {"queryPlanner": {"winningPlan": {"stage": "COLLSCAN"}}}

    def command(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._result


class _ManagerStub:
    def __init__(self, result=None):
        self.db = _DBStub(result)


class TestVerbosityReachesMongo:
    def test_the_chosen_verbosity_is_sent(self, service):
        service.get_explain_plan(collection="code_snippets", query={"user_id": 1}, verbosity="executionStats")

        (args, kwargs) = service.db_manager.db.calls[0]
        assert args[0] == "explain", "הפועל של הפקודה חייב להיות explain"
        assert args[1] == {"find": "code_snippets", "filter": {"user_id": 1}}
        assert kwargs["verbosity"] == "executionStats"

    def test_the_chosen_verbosity_is_sent_for_aggregations(self, service):
        pipeline = [{"$match": {"user_id": 1}}]
        service.get_aggregation_explain(
            collection="code_snippets", pipeline=pipeline, verbosity="allPlansExecution"
        )

        (args, kwargs) = service.db_manager.db.calls[0]
        assert args[0] == "explain"
        assert args[1]["aggregate"] == "code_snippets"
        assert args[1]["pipeline"] == pipeline
        assert args[1]["cursor"] == {}
        assert kwargs["verbosity"] == "allPlansExecution", (
            "הפרמטר התקבל ונזרק: aggregate עם explain:true אינה מקבלת verbosity כלל"
        )

    def test_the_default_is_the_safe_one(self, service):
        """ברירת המחדל של פקודת explain במונגו היא allPlansExecution.

        כלומר אם לא נשלח verbosity מפורש, מונגו מריצה את השאילתה — ולכן
        ברירת המחדל שלנו חייבת להישלח, לא להישמט.
        """
        service.get_explain_plan(collection="code_snippets", query={})

        (_, kwargs) = service.db_manager.db.calls[0]
        assert kwargs["verbosity"] == "queryPlanner"

    def test_an_unknown_verbosity_never_reaches_the_db(self, service):
        """הערך מגיע מגוף בקשת HTTP, ולכן נבדק לפני שהוא נשלח למסד."""
        with pytest.raises(ValueError, match="Unsupported explain verbosity"):
            service.get_explain_plan(collection="code_snippets", query={}, verbosity="'; drop")

        assert service.db_manager.db.calls == [], "ערך לא חוקי הגיע למסד"

    def test_the_allowed_values_are_the_ones_mongodb_documents(self):
        """מקור: https://www.mongodb.com/docs/manual/reference/command/explain/"""
        from services.query_profiler_service import QueryProfilerService

        assert QueryProfilerService.EXPLAIN_VERBOSITIES == {
            "queryPlanner",
            "executionStats",
            "allPlansExecution",
        }


class TestExplainTimeout:
    """explain ב-executionStats מריץ שאילתה איטית אמיתית על worker של הווב.

    בלי תקרה זו אותה בעיה שהתיקון בא לפתור, רק מוזזת ממקום למקום.
    """

    def test_a_deadline_is_applied(self, service, monkeypatch):
        seen: list = []

        import services.query_profiler_service as qps

        real_timeout = qps.pymongo.timeout

        def _spy(seconds):
            seen.append(seconds)
            return real_timeout(seconds)

        monkeypatch.setattr(qps.pymongo, "timeout", _spy)
        service.get_explain_plan(collection="code_snippets", query={})

        assert seen == [5.0], "ברירת המחדל היא 5000ms"

    def test_the_deadline_is_configurable(self, monkeypatch):
        monkeypatch.setenv("PROFILER_EXPLAIN_MAX_TIME_MS", "1200")
        import services.query_profiler_service as qps

        svc = qps.QueryProfilerService(db_manager=_ManagerStub(), slow_threshold_ms=100)
        seen: list = []
        real_timeout = qps.pymongo.timeout
        monkeypatch.setattr(qps.pymongo, "timeout", lambda s: (seen.append(s), real_timeout(s))[1])

        svc.get_explain_plan(collection="code_snippets", query={})
        assert seen == [1.2]


class TestParsersSurviveEveryShape:
    """מה שחוזר ממונגו משתנה לפי ה-verbosity ולפי הפייפליין."""

    def test_find_without_execution_stats_yields_no_stats(self, service):
        plan = service._parse_explain_result(
            "code_snippets", {}, {"queryPlanner": {"winningPlan": {"stage": "COLLSCAN"}}}
        )
        assert plan.stats is None

    def test_find_with_execution_stats_fills_them(self, service):
        plan = service._parse_explain_result(
            "code_snippets",
            {},
            {
                "queryPlanner": {"winningPlan": {"stage": "COLLSCAN"}},
                "executionStats": {"executionTimeMillis": 42, "totalDocsExamined": 100, "nReturned": 3},
            },
        )
        assert plan.stats is not None
        assert plan.stats.docs_examined == 100
        assert plan.stats.docs_returned == 3

    @pytest.mark.parametrize(
        "explain_result",
        [
            {"stages": [{"$cursor": {"queryPlanner": {"winningPlan": {"stage": "COLLSCAN"}}}}]},
            {"queryPlanner": {"winningPlan": {"stage": "IXSCAN"}}},
            {},
        ],
        ids=["stages", "pushed-down-to-find", "empty"],
    )
    def test_aggregation_parser_never_raises(self, service, explain_result):
        """המעבר לעטיפת explain יכול לשנות את צורת התשובה.

        השלישי הוא המקרה הגרוע: פאנל ריק בדשבורד, לא קריסה.
        """
        plan = service._parse_aggregation_explain("code_snippets", [], explain_result)
        assert isinstance(plan.stages, list)


class TestRecommendationsSurviveTheSafeDefault:
    def test_collscan_is_still_reported_without_execution_stats(self, service):
        """ההחלטה המוצרית, מקובעת בקוד.

        ברירת המחדל החדשה מוותרת על שתי המלצות שדורשות להריץ את השאילתה (יחס
        יעילות ו-covered query). ההמלצה הקריטית — COLLSCAN, זו שמייצרת את הצעת
        האינדקס — נגזרת מ-``winningPlan`` ולכן שורדת. אם היא תיעלם, ברירת
        המחדל הבטוחה תשאיר מסך ריק וזה כבר לא תיקון אלא רגרסיה.
        """
        plan = service._parse_explain_result(
            "code_snippets", {"user_id": 1}, {"queryPlanner": {"winningPlan": {"stage": "COLLSCAN"}}}
        )
        assert plan.stats is None

        recommendations = service.generate_recommendations(plan)
        assert any("COLLSCAN" in r.title for r in recommendations), (
            f"המלצת ה-COLLSCAN נעלמה בלי executionStats. התקבל: {[r.title for r in recommendations]}"
        )

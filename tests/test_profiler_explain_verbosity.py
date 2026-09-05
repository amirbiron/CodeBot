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

        import pymongo

        real_timeout = pymongo.timeout

        def _spy(seconds):
            seen.append(seconds)
            return real_timeout(seconds)

        monkeypatch.setattr(pymongo, "timeout", _spy)
        service.get_explain_plan(collection="code_snippets", query={})

        assert seen == [5.0], "ברירת המחדל היא 5000ms"

    def test_the_deadline_is_configurable(self, monkeypatch):
        monkeypatch.setenv("PROFILER_EXPLAIN_MAX_TIME_MS", "1200")
        import services.query_profiler_service as qps

        svc = qps.QueryProfilerService(db_manager=_ManagerStub(), slow_threshold_ms=100)
        seen: list = []
        import pymongo

        real_timeout = pymongo.timeout
        monkeypatch.setattr(pymongo, "timeout", lambda s: (seen.append(s), real_timeout(s))[1])

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


class TestTheRoutesTellTheUserWhatHappened:
    """הענפים האלה חייבים להיבדק דרך הראוט, לא דרך השירות.

    שם מחלקה ב-``except`` מוערך רק כשחריגה מגיעה אליו. גרסה מוקדמת של הקוד הזה
    הזכירה שם שלא היה מיובא — הטסטים ברמת השירות עברו, והכשל היה מתגלה רק
    בפרודקשן, כ-NameError בתוך handler של שגיאה.
    """

    TOKEN = "test-profiler-admin"

    def _client(self, monkeypatch, raising):
        import webapp.app as webapp_app

        monkeypatch.setattr(webapp_app, "_profiler_is_authorized", lambda: True, raising=True)
        monkeypatch.setattr(webapp_app, "_profiler_rate_limit_ok", lambda: True, raising=True)

        class _Svc:
            def get_explain_plan(self, **kwargs):
                raise raising

            def get_aggregation_explain(self, **kwargs):
                raise raising

        monkeypatch.setattr(webapp_app, "_get_webapp_profiler_service", lambda: _Svc(), raising=True)
        return webapp_app

    def test_a_timeout_is_not_reported_as_a_crash(self, monkeypatch):
        from services.query_profiler_service import ExplainTimeoutError

        webapp_app = self._client(monkeypatch, ExplainTimeoutError("explain exceeded 5000ms"))

        with webapp_app.app.test_client() as client:
            resp = client.post(
                "/api/profiler/recommendations",
                json={"collection": "code_snippets", "verbosity": "executionStats"},
            )

        assert resp.status_code == 504, resp.get_data(as_text=True)[:300]
        payload = resp.get_json()
        assert payload["error_code"] == "EXPLAIN_TIMEOUT"
        assert "queryPlanner" in payload["message"], "ההודעה חייבת לומר למשתמש מה לעשות"

    def test_an_unsupported_verbosity_is_a_400_and_not_a_500(self, monkeypatch):
        from services.query_profiler_service import ExplainVerbosityError

        webapp_app = self._client(monkeypatch, ExplainVerbosityError("Unsupported explain verbosity 'nope'"))

        with webapp_app.app.test_client() as client:
            resp = client.post(
                "/api/profiler/explain",
                json={"collection": "code_snippets", "verbosity": "nope"},
            )

        assert resp.status_code == 400, resp.get_data(as_text=True)[:300]
        assert resp.get_json()["error_code"] == "INVALID_VERBOSITY"

    def test_a_broken_query_shape_still_reports_as_before(self, monkeypatch):
        """המקרה הוותיק שומר על אותה תשובה בדיוק — 400 עם BROKEN_QUERY_SHAPE.

        שתי שגיאות הקלט יורשות מאותו בסיס, ולכן ענף אחד מטפל בשתיהן ומבדיל
        ביניהן ב-``error_code``. אם המיפוי היה מתבלבל, המקרה הוותיק היה מקבל
        פתאום קוד אחר.
        """
        from services.query_profiler_service import BrokenQueryShapeError

        webapp_app = self._client(
            monkeypatch,
            BrokenQueryShapeError("Query shape contains broken array normalization from old version."),
        )

        with webapp_app.app.test_client() as client:
            resp = client.post("/api/profiler/explain", json={"collection": "code_snippets"})

        assert resp.status_code == 400
        assert resp.get_json()["error_code"] == "BROKEN_QUERY_SHAPE"


class TestInputErrorsAreTypedNotStringMatched:
    """זיהוי סוג שגיאה לפי טקסט ההודעה הוא מלכודת שחוזרת.

    ארבעה קוראים (שני ראוטים ב-``webapp/app.py`` ושניים ב-``handlers/profiler_handler.py``)
    זיהו שגיאת קלט ב-``"broken array normalization" in str(e)``. המשמעות: כל
    ולידציה **חדשה** נופלת אוטומטית ל-``else`` ומדווחת כ-500 עם stack trace,
    כאילו השרת קרס. בדיוק זה קרה לוולידציה של ה-verbosity.
    """

    def test_every_input_error_carries_a_code(self):
        from services.query_profiler_service import (
            BrokenQueryShapeError,
            ExplainVerbosityError,
            ProfilerInputError,
        )

        assert issubclass(BrokenQueryShapeError, ProfilerInputError)
        assert issubclass(ExplainVerbosityError, ProfilerInputError)
        assert issubclass(ProfilerInputError, ValueError), "צרכנים קיימים תופסים ValueError"
        assert BrokenQueryShapeError.error_code == "BROKEN_QUERY_SHAPE"
        assert ExplainVerbosityError.error_code == "INVALID_VERBOSITY"

    def test_a_broken_shape_raises_the_typed_error(self, service):
        from services.query_profiler_service import BrokenQueryShapeError

        with pytest.raises(BrokenQueryShapeError):
            service.get_explain_plan(collection="c", query={"$expr": {"$eq": ["<2 items>"]}})

        with pytest.raises(BrokenQueryShapeError):
            service.get_aggregation_explain(collection="c", pipeline=[{"$match": {"a": {"$in": ["<3 items>"]}}}])

    def test_no_caller_identifies_the_error_by_its_message(self):
        """הגדר בסגנון lint שמונעת חזרה של הדפוס.

        זו בדיקה על טקסט הקוד ולא על התנהגות, ולכן היא מכוונת לדפוס עצמו
        (``... in str(e)``) ולא לביטוי — ניסוח ראשון שחיפש רק את הביטוי הפיל
        את הטסט על ההערות שמסבירות את התיקון.
        """
        import pathlib
        import re

        pattern = re.compile(r'"broken array normalization"\s+in\s+str\(')
        for path in ("webapp/app.py", "handlers/profiler_handler.py"):
            source = pathlib.Path(path).read_text(encoding="utf-8")
            assert not pattern.search(source), (
                f"{path} מזהה שגיאת קלט לפי טקסט ההודעה במקום לפי טיפוס"
            )


class TestVerbosityTypeIsCheckedFirst:
    @pytest.mark.parametrize("bad", [[], {}, None, 5, True], ids=["list", "dict", "none", "int", "bool"])
    def test_a_non_string_verbosity_is_a_clean_input_error(self, service, bad):
        """רשימה ואובייקט אינם hashable.

        ``bad not in frozenset`` היה זורק ``TypeError: unhashable type`` לפני
        שהוולידציה מספיקה לרוץ — כלומר 500 במקום 400, על קלט שהמשתמש שלח.
        """
        from services.query_profiler_service import ExplainVerbosityError

        with pytest.raises(ExplainVerbosityError):
            service.get_explain_plan(collection="c", query={}, verbosity=bad)

        assert service.db_manager.db.calls == []


class TestTheModuleLoadsWithoutPymongo:
    def test_pymongo_is_not_a_module_level_import(self):
        """``requirements/minimal.txt`` אינו כולל pymongo.

        שאר שכבת השירותים עוברת דרך ``db_manager`` ולא נוגעת בדרייבר, וגם
        הייבוא היחיד שאינו stdlib בראש הקובץ (``observability``) עטוף fail-open.
        ``pymongo.timeout`` באמת נחוץ, ולכן התלות יורדת לרמת הקריאה במקום
        להפיל את טעינת המודול.
        """
        import pathlib

        source = pathlib.Path("services/query_profiler_service.py").read_text(encoding="utf-8")
        header = source.split("class ProfilerInputError")[0]
        assert "\nimport pymongo" not in header, "pymongo חזר לרמת המודול"


# ---------------------------------------------------------------------------
# מדיניות השגיאות: אותה תגובה בשתי המסגרות
#
# ``webapp/app.py`` (Flask) ו-``handlers/profiler_handler.py`` (aiohttp) מממשים
# את אותה מדיניות פעמיים. הבדיקות כאן **מריצות את שני ה-handlers ומשוות תגובות
# בפועל** — סטטוס וגוף — ולא משוות קבועים: קבועים זהים אינם מוכיחים שהתגובה
# משתמשת בהם, ואפשר להשאיר קבוע במקומו ולכתוב מחרוזת קשיחה בענף.
#
# על הרלוונטיות של ה-handler: הוא אינו רץ בפרודקשן היום, אבל לא בגלל שנזנח —
# התנאי ב-``main.py:6066`` הוא ``enable_internal_web and PUBLIC_BASE_URL``,
# ו-``ENABLE_INTERNAL_SHARE_WEB=true`` כבר מוגדר. חסר רק ``PUBLIC_BASE_URL``,
# כלומר הוא משתנה סביבה אחד מלהתעורר — ולכן הסטייה כן מסוכנת.
# ---------------------------------------------------------------------------


class _RaisingProfilerService:
    """שירות דמה שמרים חריגה נתונה מכל מסלול explain."""

    def __init__(self, exc):
        self._exc = exc

    def get_explain_plan(self, **kwargs):
        raise self._exc

    def get_aggregation_explain(self, **kwargs):
        raise self._exc


def _flask_explain_response(monkeypatch, exc):
    """מריץ את ``POST /api/profiler/explain`` של ה-WebApp ומחזיר (status, json)."""
    import webapp.app as webapp_app

    monkeypatch.setattr(webapp_app, "_get_webapp_profiler_service", lambda: _RaisingProfilerService(exc))
    monkeypatch.setattr(webapp_app, "_profiler_is_authorized", lambda: True)
    monkeypatch.setattr(webapp_app, "_profiler_rate_limit_ok", lambda: True)

    with webapp_app.app.test_client() as client:
        resp = client.post("/api/profiler/explain", json={"collection": "c", "query": {}})
        return resp.status_code, resp.get_json()


async def _aiohttp_explain_response(monkeypatch, exc):
    """מריץ את אותו ראוט ב-aiohttp ומחזיר (status, json)."""
    import aiohttp
    from aiohttp import web

    from handlers.profiler_handler import setup_profiler_routes

    # בלי טוקן מוגדר, ``require_profiler_auth`` מדלג על בדיקת ה-token.
    monkeypatch.delenv("PROFILER_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PROFILER_ALLOWED_IPS", raising=False)

    app = web.Application()
    setup_profiler_routes(app, _RaisingProfilerService(exc))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=0)
    await site.start()
    try:
        port = list(site._server.sockets)[0].getsockname()[1]
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{port}/api/profiler/explain",
                json={"collection": "c", "query": {}},
            ) as resp:
                return resp.status, await resp.json()
    finally:
        await runner.cleanup()


class TestBothFrameworksAnswerTheSame:
    @pytest.mark.asyncio
    async def test_a_timeout_gets_the_same_response_everywhere(self, monkeypatch):
        """זה מה שסוגר את הממצא על מדיניות ה-504 שמועתקת."""
        from services.query_profiler_service import ExplainTimeoutError

        flask_status, flask_body = _flask_explain_response(monkeypatch, ExplainTimeoutError("explain exceeded"))
        aio_status, aio_body = await _aiohttp_explain_response(monkeypatch, ExplainTimeoutError("explain exceeded"))

        assert flask_status == aio_status == 504
        assert flask_body == aio_body
        assert flask_body["error_code"] == "EXPLAIN_TIMEOUT"

    @pytest.mark.asyncio
    async def test_an_input_error_gets_the_same_response_everywhere(self, monkeypatch):
        from services.query_profiler_service import BrokenQueryShapeError

        exc_text = "Query shape contains broken array normalization from old version."
        flask_status, flask_body = _flask_explain_response(monkeypatch, BrokenQueryShapeError(exc_text))
        aio_status, aio_body = await _aiohttp_explain_response(monkeypatch, BrokenQueryShapeError(exc_text))

        assert flask_status == aio_status == 400
        assert flask_body == aio_body
        assert flask_body["error_code"] == "BROKEN_QUERY_SHAPE"
        # ההודעה הוותיקה נשמרת מילה במילה
        assert flask_body["message"] == (
            "השאילתה מכילה נרמול שבור מגרסה ישנה. יש להשתמש בשאילתה המקורית או להקליט מחדש."
        )

    @pytest.mark.asyncio
    async def test_an_unmapped_code_never_leaks_the_exception_text(self, monkeypatch):
        """``or str(exc)`` הפך את מפת ההודעות לרשות.

        קוד בלי ערך במפה קיבל בשקט את טקסט החריגה — אנגלית, בפופאפ עברי — ושום
        דבר לא נכשל. עכשיו חוזרת הודעה גנרית, ה-``error_code`` כן חוזר כדי
        שאפשר יהיה לפעול לפיו, והטקסט המקורי נרשם ללוג בלבד.
        """
        from services.query_profiler_service import ProfilerInputError

        class _UnmappedError(ProfilerInputError):
            error_code = "SOME_FUTURE_CODE"

        secret = "internal detail that must not reach the client"
        flask_status, flask_body = _flask_explain_response(monkeypatch, _UnmappedError(secret))
        aio_status, aio_body = await _aiohttp_explain_response(monkeypatch, _UnmappedError(secret))

        assert flask_status == aio_status == 400
        assert flask_body == aio_body
        assert secret not in flask_body["message"]
        assert flask_body["error_code"] == "SOME_FUTURE_CODE"


def _all_profiler_input_error_codes() -> dict:
    """כל ה-``error_code`` שמוגדרים בקוד הייצור, בשתי שיטות משלימות.

    ⚠️ ``ProfilerInputError.__subclasses__()`` לבדו **אינו** מספיק: הוא מחזיר רק
    תת-מחלקות **ישירות**, ורק כאלה שכבר יובאו. מחלקה בעומק שני, או כזו שהוגדרה
    במודול אחר, לא הייתה מופיעה — והטסט היה עובר בשקט. לכן:

    1. **סריקת מרחב השמות** של המודול שמגדיר את החריגות — דטרמיניסטית ובלתי
       תלויה בעומק, ומצהירה איפה החריגות אמורות לגור.
    2. **מעבר רקורסיבי** על ``__subclasses__`` — תופס מחלקות מחוץ למודול שכן יובאו.

    **מגבלה שנשארת:** מחלקה במודול שאיש אינו מייבא אינה ניתנת לגילוי בזמן ריצה
    בשום שיטה. זה גבול אמיתי, לא פער במימוש.
    """
    import inspect
    import pathlib

    import services.query_profiler_service as qps

    found: dict = {}
    tests_dir = pathlib.Path(__file__).resolve().parent

    def _defined_in_tests(cls) -> bool:
        """האם המחלקה הוגדרה בתוך קובץ טסט.

        סינון לפי **נתיב** ולא לפי ``__module__``: ל-``tests/`` אין ``__init__.py``,
        ולכן pytest מייבא את הקבצים בשם ``test_x`` בלי הקידומת ``tests.`` — אותה
        תכונת אריזה שכבר שברה כאן ייבוא בעבר. הנתיב חסין לזה.
        """
        try:
            return tests_dir in pathlib.Path(inspect.getfile(cls)).resolve().parents
        except (TypeError, OSError):
            # מחלקה שנוצרה דינמית ואין לה קובץ — לא ניתן לשייך, לא נספרת.
            return True

    def _record(cls) -> None:
        # מחלקות שהוגדרו בתוך טסטים דולפות לרישום הגלובלי של ``__subclasses__``.
        # האכיפה היא על קודים שהקוד הייצורי מגדיר, לא על דמויות חד-פעמיות.
        if _defined_in_tests(cls):
            return
        code = getattr(cls, "error_code", None)
        if code:
            found[str(code)] = cls.__name__

    for _, obj in inspect.getmembers(qps, inspect.isclass):
        if issubclass(obj, qps.ProfilerInputError):
            _record(obj)

    def _walk(cls) -> None:
        for sub in cls.__subclasses__():
            _record(sub)
            _walk(sub)

    _walk(qps.ProfilerInputError)
    return found


class TestEveryErrorCodeHasAMessage:
    def test_both_maps_cover_every_defined_code(self):
        """קוד בלי הודעה = הודעה גנרית למשתמש. הפער נאכף כאן ולא בפרודקשן."""
        import handlers.profiler_handler as handler_mod
        import webapp.app as webapp_app

        codes = set(_all_profiler_input_error_codes())
        assert codes, "לא נמצא אף error_code — הסריקה שבורה"

        for name, mapping in (
            ("webapp/app.py", webapp_app._PROFILER_INPUT_MESSAGES),
            ("handlers/profiler_handler.py", handler_mod._PROFILER_INPUT_MESSAGES),
        ):
            missing = codes - set(mapping)
            assert not missing, f"{name} חסרות הודעות ל: {sorted(missing)}"

    def test_the_two_maps_are_identical(self):
        """אותה שגיאה חייבת להיקרא אותו דבר בדשבורד ובבוט."""
        import handlers.profiler_handler as handler_mod
        import webapp.app as webapp_app

        assert webapp_app._PROFILER_INPUT_MESSAGES == handler_mod._PROFILER_INPUT_MESSAGES

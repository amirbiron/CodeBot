"""תיקוני הריוויו בשכבת הסקריפטים ונקודות הכניסה (אישו #3332, PR #3342).

שלושה דברים שאין להם דמות DB ולכן הם נבדקים כאן ביחד:

1. **``scripts/migrate_semantic_search.py``** — יצירת האינדקס דרך
   ``safe_create_index`` ולא ``create_index`` גולמי. ההרצה הראשונה של
   הסקריפט (לפני האישו) יצרה את אותם מפתחות בשם ברירת המחדל
   ``userId_1_snippetId_1``; יצירה חוזרת בשם החדש הייתה נופלת על
   ``IndexOptionsConflict`` ועוצרת את המיגרציה.
2. **``scripts/probe_embedding_limits.py``** — נרמול המודל וגרסת ה-API, וקוד
   יציאה שאינו 0 כשהתוצאה אינה כמצופה.
3. **``main._env_flag``** — אותו דגל סביבה נקרא בשלושה מקומות עם קבוצות ערכים
   שונות, ולכן ``DISABLE_BACKGROUND_CLEANUP=on`` השבית חלק מהג'ובים בלבד.
"""

import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(path, name):
    """טוען סקריפט כמודול. הסקריפטים אינם חבילה, אז אין להם import רגיל."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --- 1. המיגרציה ----------------------------------------------------------


class TestMigrationIndex:
    def test_index_is_created_through_the_safe_helper(self, monkeypatch):
        """``safe_create_index`` הוא מה שמזהה אינדקס זהה בשם אחר ומדלג.

        בלעדיו, כל מסד שכבר עבר את המיגרציה הישנה היה עוצר את המיגרציה
        החדשה ב-``IndexOptionsConflict`` — כלומר האינדקסים החדשים לא היו
        נוצרים בכלל.
        """
        import pymongo

        migrate = _load("scripts/migrate_semantic_search.py", "_migrate_under_test")

        closed = {"n": 0}

        class _Client:
            def __getitem__(self, _name):
                return object()

            def close(self):
                closed["n"] += 1

        recorded = []

        def _safe_create_index(_self, collection_name, keys, **kwargs):
            recorded.append({"collection": collection_name, "keys": keys, **kwargs})

        monkeypatch.setattr(pymongo, "MongoClient", lambda *_a, **_k: _Client())
        monkeypatch.setattr(
            migrate.config, "MONGODB_URL", "mongodb://localhost:27017", raising=False
        )
        from database.manager import DatabaseManager

        monkeypatch.setattr(DatabaseManager, "safe_create_index", _safe_create_index)

        migrate._create_chunk_index()

        assert recorded == [{
            "collection": "snippet_chunks",
            "keys": [("userId", pymongo.ASCENDING), ("snippetId", pymongo.ASCENDING)],
            "name": "snippet_chunks_user_snippet_idx",
        }]
        assert closed["n"] == 1, "the short-lived sync client was left open"

    def test_the_script_never_calls_create_index_directly(self):
        """הגנה על השורש: ``create_index`` גולמי הוא בדיוק מה שנשבר."""
        source = open(
            os.path.join(ROOT, "scripts/migrate_semantic_search.py"), encoding="utf-8"
        ).read()
        assert "snippet_chunks.create_index" not in source
        assert "safe_create_index" in source


# --- 2. הפרוב -------------------------------------------------------------


class TestProbeNormalisation:
    @staticmethod
    def _resolve(monkeypatch, **env):
        for key in (
            "GEMINI_EMBEDDING_MODEL",
            "GEMINI_API_VERSION",
            "EMBEDDING_DIMENSIONS",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)

        # ``get_embedding_settings_cached`` מחזיק קאש של 30 שניות ברמת המודול.
        # בפרוב עצמו זה לא רלוונטי — הוא תהליך חדש עם קאש קר — אבל בסוויטה
        # ערך מטסט קודם היה דולף לכאן והטסט היה בודק את הקאש ולא את הנרמול.
        import services.semantic_embedding_settings as settings_mod

        monkeypatch.setattr(settings_mod, "_cached_value", None, raising=False)
        monkeypatch.setattr(settings_mod, "_cached_at_monotonic", 0.0, raising=False)

        probe = _load("scripts/probe_embedding_limits.py", "_probe_under_test")
        return probe.DEFAULT_MODEL, probe.DEFAULT_API_VERSION, probe.DEFAULT_DIMENSIONS

    @pytest.mark.parametrize(
        "configured",
        ["gemini-embedding-001", "models/gemini-embedding-001"],
    )
    def test_the_models_prefix_is_stripped(self, monkeypatch, configured):
        """``models/x`` היה בונה ``.../models/models/x:embedContent``.

        התוצאה: שלושת הפרובים נכשלים ב-404, והמפעיל היה מסיק מזה משהו על
        מגבלת הקלט במקום על הכתובת.
        """
        model, _api, _dims = self._resolve(monkeypatch, GEMINI_EMBEDDING_MODEL=configured)
        assert model == "gemini-embedding-001"

    @pytest.mark.parametrize(
        "configured,expected",
        [("/v1", "v1"), ("v1beta/", "v1beta"), ("/v1beta/", "v1beta"),
         ("", "v1beta"), ("  v1  ", "v1"), ("nonsense", "v1beta")],
    )
    def test_the_api_version_is_normalised(self, monkeypatch, configured, expected):
        _model, api, _dims = self._resolve(monkeypatch, GEMINI_API_VERSION=configured)
        assert api == expected

    def test_missing_key_exits_non_zero(self, monkeypatch, capsys):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        probe = _load("scripts/probe_embedding_limits.py", "_probe_under_test")

        assert probe.main() == 2

    def test_the_target_comes_from_the_same_source_as_the_worker(self, monkeypatch):
        """פרוב שבודק מודל אחר מזה שה-worker שולח אליו יכול לעבור בזמן
        שהמסלול האמיתי נכשל."""
        source = open(
            os.path.join(ROOT, "scripts/probe_embedding_limits.py"), encoding="utf-8"
        ).read()
        assert "get_embedding_settings_cached" in source
        assert "normalize_model_name" in source


class TestProbeVerdict:
    """הפרוב חייב להסיק מסקנה, לא רק להדפיס שלושה סטטוסים.

    ``main()`` שמחזיר תמיד 0 היה מדווח 429, 5xx או כשל אימות כ"פרוב שעבר",
    והמפעיל היה מדליק ``EMBEDDING_AUTO_TRUNCATE=false`` על סמך ריצה שלא
    בדקה כלום.
    """

    @staticmethod
    def _run_with(monkeypatch, statuses):
        probe = _load("scripts/probe_embedding_limits.py", "_probe_under_test")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(probe.httpx, "Client", lambda *_a, **_k: _Client())
        queue = list(statuses)
        monkeypatch.setattr(probe, "_probe", lambda *_a, **_k: queue.pop(0))
        return probe.main()

    def test_a_rejected_flag_is_reported_as_failure(self, monkeypatch, capsys):
        assert self._run_with(monkeypatch, [400, 400, 200]) == 1
        assert "Do NOT set EMBEDDING_AUTO_TRUNCATE=false" in capsys.readouterr().out

    def test_still_silently_truncating_is_reported_as_failure(self, monkeypatch, capsys):
        assert self._run_with(monkeypatch, [200, 200, 200]) == 1
        assert "did NOT stop the silent truncation" in capsys.readouterr().out

    def test_the_expected_outcome_exits_zero(self, monkeypatch, capsys):
        assert self._run_with(monkeypatch, [200, 400, 200]) == 0
        assert "safe to enable" in capsys.readouterr().out

    def test_a_transport_error_is_not_a_passing_probe(self, monkeypatch, capsys):
        """``0`` = לא הגיע לשרת בכלל."""
        assert self._run_with(monkeypatch, [0, 0, 0]) == 1


# --- 3. דגל הסביבה --------------------------------------------------------


class TestEnvFlag:
    """``DISABLE_BACKGROUND_CLEANUP=on`` השבית את ניקוי הגיבויים אבל לא את
    ג'ובי הניקוי — אותו דגל, שתי התנהגויות, כי כל אתר קריאה החזיק קבוצת
    ערכים משלו."""

    @pytest.fixture(autouse=True)
    def _main(self):
        import main

        self.main = main

    @pytest.mark.parametrize(
        "raw", ["1", "true", "TRUE", "yes", "y", "on", "ON", " on ", "  true\n"]
    )
    def test_truthy_values(self, monkeypatch, raw):
        monkeypatch.setenv("DISABLE_BACKGROUND_CLEANUP", raw)
        assert self.main._env_flag("DISABLE_BACKGROUND_CLEANUP") is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "maybe", "   "])
    def test_falsy_values(self, monkeypatch, raw):
        monkeypatch.setenv("DISABLE_BACKGROUND_CLEANUP", raw)
        assert self.main._env_flag("DISABLE_BACKGROUND_CLEANUP") is False

    def test_unset_uses_the_default(self, monkeypatch):
        monkeypatch.delenv("DISABLE_BACKGROUND_CLEANUP", raising=False)
        assert self.main._env_flag("DISABLE_BACKGROUND_CLEANUP") is False
        assert self.main._env_flag("DISABLE_BACKGROUND_CLEANUP", True) is True

    def test_an_empty_value_uses_the_default(self, monkeypatch):
        """``VAR=`` ב-render.yaml הוא "לא הוגדר", לא "כבוי"."""
        monkeypatch.setenv("SNIPPET_CHUNKS_CLEANUP_ENABLED", "")
        assert self.main._env_flag("SNIPPET_CHUNKS_CLEANUP_ENABLED", True) is True

    @pytest.mark.parametrize("raw", ["on", "ON", " on ", " true\n", "y"])
    def test_the_values_the_old_inline_expression_missed(self, monkeypatch, raw):
        """תיעוד הבאג עצמו, ולא רק התיקון.

        הביטוי שהיה בקוד — ``.lower() in {"1", "true", "yes"}`` בלי ``strip``
        — מחזיר ``False`` לכל אחד מהערכים האלה, בעוד ש-``file_manager.py``
        מכיר אותם. אותו דגל, שתי התנהגויות.
        """

        def _old_expression(value):
            return str(value or "").lower() in {"1", "true", "yes"}

        assert _old_expression(raw) is False, "this value was never the bug"

        monkeypatch.setenv("DISABLE_BACKGROUND_CLEANUP", raw)
        assert self.main._env_flag("DISABLE_BACKGROUND_CLEANUP") is True

    def test_main_has_no_leftover_inline_flag_parsing(self):
        """הגנה על השורש: עותק חוזר של הביטוי הוא איך שזה נסחף מלכתחילה."""
        source = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
        assert 'DISABLE_BACKGROUND_CLEANUP", ""' not in source
        assert source.count('_env_flag("DISABLE_BACKGROUND_CLEANUP")') >= 3

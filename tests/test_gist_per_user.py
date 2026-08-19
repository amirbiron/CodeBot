"""בדיקות ש-Gist נוצר תחת חשבון ה-GitHub של המשתמש ולא של המערכת.

הטוקן הגלובלי (``GITHUB_TOKEN``) שייך לחשבון שמריץ את הבוט. שימוש בו
ליצירת Gist היה יוצר את כל ה-Gists של כל המשתמשים תחת אותו חשבון —
ובאופן ציבורי. הבדיקות כאן נועלות את ההפרדה.
"""

import ast
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

import pytest

import integrations


USER_TOKEN = "ghp_user_token_for_tests"
GLOBAL_TOKEN = "ghp_global_system_token"


class _FakeGistFile:
    """קובץ בתוך Gist, במבנה ש-PyGithub מחזיר."""

    def __init__(self, name, content):
        self.filename = name
        self.type = "text/plain"
        self.language = "Python"
        self.size = len(content)
        self.raw_url = f"https://gist.githubusercontent.com/raw/{name}"


class _FakeGist:
    """אובייקט Gist עם כל השדות ש-``create_gist`` קורא בפועל.

    הסטאב נאמן לשדות האמיתיים בכוונה: סטאב חסר-שדות היה גורם ל-``AttributeError``
    שנבלע ב-``except`` הרחב, ``create_gist`` היה מחזיר ``None``, והבדיקות היו
    עוברות על מסלול כושל בשקט.
    """

    def __init__(self, public, files, description):
        self.id = "abc123"
        self.html_url = "https://gist.github.com/abc123"
        self.git_pull_url = "https://gist.github.com/abc123.git"
        self.git_push_url = "https://gist.github.com/abc123.git"
        self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.description = description
        self.public = public
        self.files = {
            name: _FakeGistFile(name, getattr(content, "content", ""))
            for name, content in files.items()
        }


@pytest.fixture
def fake_github(monkeypatch):
    """מחליף את ``Github`` בכפיל שרושם באיזה טוקן נעשה שימוש."""
    created = []

    class _FakeUser:
        def __init__(self, token):
            self.login = f"user-of-{token}"
            self._token = token

        def create_gist(self, public, files, description):
            created.append({"token": self._token, "public": public, "files": dict(files)})
            return _FakeGist(public, files, description)

    class _FakeGithub:
        def __init__(self, token):
            self._token = token

        def get_user(self):
            return _FakeUser(self._token)

    monkeypatch.setattr(integrations, "Github", _FakeGithub)
    return created


def _set_user_token(monkeypatch, token):
    """מזריק ``database.db`` מדומה שמחזיר את הטוקן האישי."""
    db_stub = ModuleType("database")
    db_stub.db = SimpleNamespace(get_github_token=lambda uid: token)
    monkeypatch.setitem(sys.modules, "database", db_stub)


def test_user_gist_uses_the_users_own_token(monkeypatch, fake_github):
    """הטוקן שמשמש ליצירה הוא של המשתמש, לא הגלובלי."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    _set_user_token(monkeypatch, USER_TOKEN)

    gist, error = integrations.resolve_gist_for_user(555)
    assert gist is not None
    assert error is None

    result = gist.create_gist("a.py", "print(1)", "python")
    # ``create_gist`` בולע כל חריגה ומחזיר ``None``; בלי הבדיקה הזו כשל שקט
    # של הסטאב היה נראה כמו הצלחה.
    assert result is not None
    assert result["url"] == "https://gist.github.com/abc123"

    assert fake_github[0]["token"] == USER_TOKEN
    assert fake_github[0]["token"] != GLOBAL_TOKEN


def test_user_without_token_gets_none_and_never_falls_back(monkeypatch, fake_github):
    """זו הליבה: בלי טוקן אישי לא נוצר Gist — ובוודאי לא בחשבון המערכת."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    _set_user_token(monkeypatch, None)

    gist, error = integrations.resolve_gist_for_user(555)
    assert gist is None
    assert error == integrations.GIST_NEEDS_GITHUB_MESSAGE
    assert fake_github == []


def test_missing_user_id_returns_none(monkeypatch, fake_github):
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    _set_user_token(monkeypatch, USER_TOKEN)
    assert integrations.resolve_gist_for_user(0).integration is None
    assert integrations.resolve_gist_for_user(None).integration is None


def test_db_failure_returns_none_rather_than_system_account(monkeypatch, fake_github):
    """כשל בקריאת הטוקן לא מדרדר ליצירה בחשבון המערכת."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)

    def _boom(_uid):
        raise RuntimeError("db down")

    db_stub = ModuleType("database")
    db_stub.db = SimpleNamespace(get_github_token=_boom)
    monkeypatch.setitem(sys.modules, "database", db_stub)

    gist, error = integrations.resolve_gist_for_user(555)
    assert gist is None
    assert fake_github == []
    # תקלה זמנית אינה "לא חיברת GitHub" — משתמש מחובר לא אמור לקבל הנחיית חיבור
    assert error == integrations.GIST_TEMPORARY_FAILURE_MESSAGE
    assert error != integrations.GIST_NEEDS_GITHUB_MESSAGE


def test_revoked_token_asks_to_reconnect(monkeypatch, fake_github):
    """טוקן שמור שכבר לא תקף — המשתמש מתבקש לחבר מחדש, לא 'נסה שוב'."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    _set_user_token(monkeypatch, USER_TOKEN)

    class _RejectingGithub:
        def __init__(self, token):
            pass

        def get_user(self):
            raise integrations.GithubException(401, "Bad credentials", None)

    monkeypatch.setattr(integrations, "Github", _RejectingGithub)

    gist, error = integrations.resolve_gist_for_user(555)
    assert gist is None
    assert error == integrations.GIST_NEEDS_GITHUB_MESSAGE


def test_explicit_token_wins_over_global(monkeypatch, fake_github):
    """הבנאי מכבד טוקן מפורש; הגלובלי הוא רק ברירת מחדל."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    integration = integrations.GitHubGistIntegration(token=USER_TOKEN)
    assert integration.is_available()
    assert integration.create_gist("a.py", "print(1)", "python") is not None
    assert fake_github[0]["token"] == USER_TOKEN


def test_constructor_without_token_still_uses_global(monkeypatch, fake_github):
    """תאימות לאחור: שימושים תפעוליים ללא משתמש ממשיכים לעבוד."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    integration = integrations.GitHubGistIntegration()
    assert integration.is_available()
    assert integration.create_gist("a.py", "print(1)", "python") is not None
    assert fake_github[0]["token"] == GLOBAL_TOKEN


def test_guidance_message_points_to_github_menu_and_alternative():
    """ההודעה למשתמש בלי טוקן מסבירה גם איך לחבר וגם מה החלופה."""
    msg = integrations.GIST_NEEDS_GITHUB_MESSAGE
    assert "GitHub" in msg
    assert "Pastebin" in msg
    # הכפתור בתפריט הראשי הוא "🔧 GitHub". הפניה לאימוג'י אחר שולחת את
    # המשתמש לחפש כפתור שלא קיים.
    assert "🔧 GitHub" in msg


def _iter_call_sites(source):
    """מחזיר את כל קריאות ה-``Call`` בקובץ, לצד הפונקציה העוטפת שלהן."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call):
                yield node, call


SHARING_MODULES = ('conversation_handlers.py', 'bot_handlers.py', 'refactor_handlers.py')


def _read_sharing_sources():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    return {name: (root / name).read_text(encoding='utf-8') for name in SHARING_MODULES}


def test_no_global_gist_singleton_exists():
    """אין אינסטנס Gist גלובלי שאפשר להיתקל בו בטעות.

    כל עוד ``integrations.gist_integration`` קיים, שורה אחת של קוד עתידי
    מספיקה כדי להחזיר את כל ה-Gists לחשבון המערכת.
    """
    assert not hasattr(integrations, 'gist_integration')
    assert not hasattr(integrations, 'get_gist_integration_for_user'), (
        "שני שמות לאותה פעולה — נשארת נקודת כניסה אחת: resolve_gist_for_user"
    )


def test_all_gist_call_sites_go_through_the_per_user_factory():
    """אף מסלול שיתוף לא נשאר על ה-singleton הגלובלי.

    זו הנעילה האמיתית: אם מישהו יוסיף בעתיד קריאה ל-``gist_integration``
    באחד ממסלולי השיתוף, ה-Gist ייווצר שוב תחת חשבון המערכת.
    """
    for name, source in _read_sharing_sources().items():
        assert 'resolve_gist_for_user' in source, f"{name} לא עבר לפקטורי"
        assert 'gist_integration.create_gist' not in source, (
            f"{name} עדיין יוצר Gist דרך ה-singleton הגלובלי"
        )
        # ‎code_sharing.share_code(service="gist")‎ עוקף את הפקטורי ומשתמש
        # ב-‎self.gist‎ הגלובלי — מסלול שקל לפספס כי הוא לא מזכיר gist_integration.
        # מזוהה ב-AST ולא בחיפוש מחרוזת, כדי לא לתפוס קריאות פנימיות לגיטימיות.
        for _fn, call in _iter_call_sites(source):
            if not (isinstance(call.func, ast.Attribute) and call.func.attr == 'share_code'):
                continue
            passed = [a.value for a in call.args if isinstance(a, ast.Constant)]
            passed += [
                kw.value.value
                for kw in call.keywords
                if kw.arg == 'service' and isinstance(kw.value, ast.Constant)
            ]
            assert 'gist' not in passed, (
                f"{name} משתף ל-Gist דרך code_sharing.share_code במקום דרך הפקטורי"
            )


def test_no_blocking_gist_call_inside_async_handler():
    """הקריאות ל-GitHub ול-DB לא חוסמות את ה-event loop.

    ``resolve_gist_for_user`` פונה ל-DB ו-``create_gist*`` פונה לרשת. קריאה
    ישירה מתוך handler אסינכרוני מקפיאה את הבוט לכל המשתמשים עד שהיא חוזרת,
    ולכן הן חייבות לעבור דרך ``asyncio.to_thread``.
    """
    blocking = {'resolve_gist_for_user', 'create_gist', 'create_gist_multi'}

    for name, source in _read_sharing_sources().items():
        for fn, call in _iter_call_sites(source):
            if not isinstance(fn, ast.AsyncFunctionDef):
                continue
            func = call.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', None)
            if called not in blocking:
                continue
            # קריאה ישירה = הפרה. הצורה המותרת היא ‎asyncio.to_thread(fn, ...)‎,
            # ושם הפונקציה מופיעה כארגומנט ולא כ-``call.func``.
            raise AssertionError(
                f"{name}:{call.lineno} — {fn.name} קורא ל-{called} ישירות במקום דרך asyncio.to_thread"
            )

        # ואימות חיובי: הקריאות אכן מועברות ל-to_thread
        for _fn, call in _iter_call_sites(source):
            func = call.func
            if not (isinstance(func, ast.Attribute) and func.attr == 'to_thread'):
                continue
            if not call.args:
                continue
            first = call.args[0]
            passed = first.attr if isinstance(first, ast.Attribute) else getattr(first, 'id', None)
            assert passed is not None, f"{name}:{call.lineno} — to_thread בלי פונקציה מזוהה"

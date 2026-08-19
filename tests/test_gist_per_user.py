"""בדיקות ש-Gist נוצר תחת חשבון ה-GitHub של המשתמש ולא של המערכת.

הטוקן הגלובלי (``GITHUB_TOKEN``) שייך לחשבון שמריץ את הבוט. שימוש בו
ליצירת Gist היה יוצר את כל ה-Gists של כל המשתמשים תחת אותו חשבון —
ובאופן ציבורי. הבדיקות כאן נועלות את ההפרדה.
"""

import ast
import sys
from types import ModuleType, SimpleNamespace

import pytest

import integrations


USER_TOKEN = "ghp_user_token_for_tests"
GLOBAL_TOKEN = "ghp_global_system_token"


@pytest.fixture
def fake_github(monkeypatch):
    """מחליף את ``Github`` בכפיל שרושם באיזה טוקן נעשה שימוש."""
    created = []

    class _FakeUser:
        def __init__(self, token):
            self.login = f"user-of-{token}"
            self._token = token

        def create_gist(self, public, files, description):
            created.append({"token": self._token, "public": public})
            return SimpleNamespace(
                html_url="https://gist.github.com/abc",
                id="abc",
                created_at=None,
                files=files,
            )

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

    gist = integrations.get_gist_integration_for_user(555)
    assert gist is not None
    gist.create_gist("a.py", "print(1)", "python")

    assert fake_github[0]["token"] == USER_TOKEN
    assert fake_github[0]["token"] != GLOBAL_TOKEN


def test_user_without_token_gets_none_and_never_falls_back(monkeypatch, fake_github):
    """זו הליבה: בלי טוקן אישי לא נוצר Gist — ובוודאי לא בחשבון המערכת."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    _set_user_token(monkeypatch, None)

    assert integrations.get_gist_integration_for_user(555) is None
    assert fake_github == []


def test_missing_user_id_returns_none(monkeypatch, fake_github):
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    _set_user_token(monkeypatch, USER_TOKEN)
    assert integrations.get_gist_integration_for_user(0) is None
    assert integrations.get_gist_integration_for_user(None) is None


def test_db_failure_returns_none_rather_than_system_account(monkeypatch, fake_github):
    """כשל בקריאת הטוקן לא מדרדר ליצירה בחשבון המערכת."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)

    def _boom(_uid):
        raise RuntimeError("db down")

    db_stub = ModuleType("database")
    db_stub.db = SimpleNamespace(get_github_token=_boom)
    monkeypatch.setitem(sys.modules, "database", db_stub)

    assert integrations.get_gist_integration_for_user(555) is None
    assert fake_github == []


def test_explicit_token_wins_over_global(monkeypatch, fake_github):
    """הבנאי מכבד טוקן מפורש; הגלובלי הוא רק ברירת מחדל."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    integration = integrations.GitHubGistIntegration(token=USER_TOKEN)
    assert integration.is_available()
    integration.create_gist("a.py", "print(1)", "python")
    assert fake_github[0]["token"] == USER_TOKEN


def test_constructor_without_token_still_uses_global(monkeypatch, fake_github):
    """תאימות לאחור: שימושים תפעוליים ללא משתמש ממשיכים לעבוד."""
    monkeypatch.setattr(integrations, "_get_github_token", lambda: GLOBAL_TOKEN)
    integration = integrations.GitHubGistIntegration()
    assert integration.is_available()
    integration.create_gist("a.py", "print(1)", "python")
    assert fake_github[0]["token"] == GLOBAL_TOKEN


def test_guidance_message_points_to_github_menu_and_alternative():
    """ההודעה למשתמש בלי טוקן מסבירה גם איך לחבר וגם מה החלופה."""
    msg = integrations.GIST_NEEDS_GITHUB_MESSAGE
    assert "GitHub" in msg
    assert "Pastebin" in msg


def test_all_gist_call_sites_go_through_the_per_user_factory():
    """אף מסלול שיתוff לא נשאר על ה-singleton הגלובלי.

    זו הנעילה האמיתית: אם מישהו יוסיף בעתיד קריאה ל-``gist_integration``
    באחד ממסלולי השיתוף, ה-Gist ייווצר שוב תחת חשבון המערכת.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for name in ('conversation_handlers.py', 'bot_handlers.py', 'refactor_handlers.py'):
        source = (root / name).read_text(encoding='utf-8')
        assert 'get_gist_integration_for_user' in source, f"{name} לא עבר לפקטורי"
        assert 'gist_integration.create_gist' not in source, (
            f"{name} עדיין יוצר Gist דרך ה-singleton הגלובלי"
        )
        # ‎code_sharing.share_code(service="gist")‎ עוקף את הפקטורי ומשתמש
        # ב-‎self.gist‎ הגלובלי — מסלול שקל לפספס כי הוא לא מזכיר gist_integration.
        # מזוהה ב-AST ולא בחיפוש מחרוזת, כדי לא לתפוס קריאות פנימיות לגיטימיות.
        for call in ast.walk(ast.parse(source)):
            if not isinstance(call, ast.Call):
                continue
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

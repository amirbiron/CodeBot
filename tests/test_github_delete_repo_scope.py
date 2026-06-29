"""בדיקות למחיקת ריפו ב-GitHub כשלטוקן חסרה הרשאת delete_repo.

הרקע: כשמוחקים ריפו דרך ה-API עם טוקן שאין לו את ההרשאה ``delete_repo``,
GitHub מחזיר 403 "Must have admin rights to Repository" – גם כשהמשתמש הוא
הבעלים. הבוט אמור לזהות את המקרה ולהציג הסבר ברור במקום שגיאה מבלבלת.
"""
import types

import pytest

import github_menu_handler as gmh


class _Msg:
    def __init__(self):
        self.texts = []

    async def edit_text(self, text, **kwargs):
        self.texts.append(text)
        return self


class _Query:
    def __init__(self, user_id=5):
        self.message = _Msg()
        self.data = ""
        self.from_user = types.SimpleNamespace(id=user_id)

    async def edit_message_text(self, text, **kwargs):
        self.message.texts.append(text)
        return self.message

    async def answer(self, *args, **kwargs):
        return None


class _Update:
    def __init__(self, user_id=5):
        self.callback_query = _Query(user_id)
        self.effective_user = types.SimpleNamespace(id=user_id)


class _Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


class _FakeGithubException(gmh.GithubException):
    """חריגה תואמת GithubException עם status/data ניתנים להגדרה.

    ב-PyGithub האמיתי (כפי שמותקן ב-CI) השדות ``status`` ו-``data`` הם
    properties לקריאה בלבד, ולכן השמה ישירה אליהם זורקת AttributeError.
    כאן אנחנו מצלילים אותם כתכונות מחלקה רגילות (הן קודמות ב-MRO לפרופרטי
    של מחלקת האב), כך שאפשר להגדיר אותם בטסט בלי תלות בגרסת PyGithub.
    """

    status = None
    data = None

    def __init__(self, status, data):
        self.status = status
        self.data = data


class _FakeRepoOwner:
    def __init__(self, login):
        self.login = login


class _FakeRepo:
    def __init__(self, owner_login, delete_exc=None):
        self.owner = _FakeRepoOwner(owner_login)
        self._delete_exc = delete_exc
        self.deleted = False

    def delete(self):
        if self._delete_exc is not None:
            raise self._delete_exc
        self.deleted = True


class _FakeUser:
    def __init__(self, login):
        self.login = login


def _make_fake_github(owner_login="octocat", oauth_scopes=None, delete_exc=None):
    """מחזיר מחלקה שמחקה את PyGithub.Github עם scopes/בעלים נשלטים."""
    repo_holder = {}

    class _FakeGithub:
        def __init__(self, token):
            self.token = token
            self.oauth_scopes = oauth_scopes

        def get_repo(self, name):
            repo = _FakeRepo(owner_login, delete_exc=delete_exc)
            repo_holder["repo"] = repo
            return repo

        def get_user(self):
            return _FakeUser("octocat")

    return _FakeGithub, repo_holder


def _build_handler(monkeypatch, fake_github):
    handler = gmh.GitHubMenuHandler()
    handler.user_sessions[5] = {"selected_repo": "octocat/demo", "github_token": "ghp_x"}
    monkeypatch.setattr(handler, "get_user_token", lambda uid: "ghp_x")

    # נעקוב אחרי קריאות לרענון התפריט כדי לוודא שלא דורסים הודעות שגיאה/עזרה.
    handler.menu_calls = []

    async def _noop_menu(update, context):
        handler.menu_calls.append(True)
        return None

    monkeypatch.setattr(handler, "github_menu_command", _noop_menu)
    monkeypatch.setattr(gmh, "Github", fake_github)
    return handler


@pytest.mark.asyncio
async def test_delete_repo_blocked_when_scope_missing(monkeypatch):
    """כשידוע ש-delete_repo חסרה בכותרת ה-scopes – חוסמים מראש ולא קוראים ל-delete()."""
    fake_github, repo_holder = _make_fake_github(oauth_scopes=["repo", "gist"])
    handler = _build_handler(monkeypatch, fake_github)
    update, context = _Update(), _Context()

    await handler.confirm_delete_repo(update, context)

    last = update.callback_query.message.texts[-1]
    assert "delete_repo" in last
    # לא בוצעה מחיקה בפועל
    assert repo_holder["repo"].deleted is False
    # לא דורסים את ההסבר ברענון התפריט
    assert handler.menu_calls == []


@pytest.mark.asyncio
async def test_delete_repo_success_when_scope_present(monkeypatch):
    """כש-delete_repo קיימת – המחיקה מתבצעת ומוצגת הודעת הצלחה."""
    fake_github, repo_holder = _make_fake_github(oauth_scopes=["repo", "delete_repo"])
    handler = _build_handler(monkeypatch, fake_github)
    update, context = _Update(), _Context()

    await handler.confirm_delete_repo(update, context)

    assert repo_holder["repo"].deleted is True
    assert any("נמחק בהצלחה" in t for t in update.callback_query.message.texts)
    # במסלול ההצלחה כן מרעננים את התפריט
    assert handler.menu_calls == [True]


@pytest.mark.asyncio
async def test_delete_repo_not_blocked_for_empty_scope_header(monkeypatch):
    """טוקן fine-grained/GitHub App מחזיר כותרת X-OAuth-Scopes ריקה ש-PyGithub
    עלול לרשום כ-[""]. אסור שזה ייחשב כ'חסר delete_repo' ויחסום – צריך להמשיך
    למחיקה בפועל (ולהסתמך על הרשאות ה-Administration של הטוקן)."""
    fake_github, repo_holder = _make_fake_github(oauth_scopes=[""])
    handler = _build_handler(monkeypatch, fake_github)
    update, context = _Update(), _Context()

    await handler.confirm_delete_repo(update, context)

    # לא נחסם – המחיקה בוצעה
    assert repo_holder["repo"].deleted is True
    assert any("נמחק בהצלחה" in t for t in update.callback_query.message.texts)


@pytest.mark.asyncio
async def test_delete_repo_403_admin_rights_shows_scope_help(monkeypatch):
    """אם ה-scopes לא ידועים (טוקן fine-grained) ו-GitHub מחזיר 403 admin rights –
    מציגים את הסבר ה-delete_repo במקום השגיאה הגולמית."""
    exc = _FakeGithubException(403, {"message": "Must have admin rights to Repository."})
    fake_github, _ = _make_fake_github(oauth_scopes=None, delete_exc=exc)
    handler = _build_handler(monkeypatch, fake_github)
    update, context = _Update(), _Context()

    await handler.confirm_delete_repo(update, context)

    last = update.callback_query.message.texts[-1]
    assert "delete_repo" in last
    # גם כאן ההסבר נשאר על המסך ולא מרעננים את התפריט
    assert handler.menu_calls == []

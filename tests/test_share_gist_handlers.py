"""בדיקות ברמת ה-handler למסלולי שיתוף ה-Gist.

הבדיקות ב-``test_gist_per_user.py`` נועלות את שכבת האינטגרציה ואת צורת
הקריאה (AST). כאן בודקים את מה שהמשתמש בפועל רואה: איזו הודעה מוצגת בכל
מצב, ושהקריאות החוסמות אכן רצות דרך ``asyncio.to_thread`` בזמן ריצה ולא
רק לפי צורת הקוד.
"""

import sys
import threading
from types import SimpleNamespace

import pytest

import integrations


FILE_ID = "6512ab00000000000000abcd"


class _Query:
    """callback_query מינימלי שרושם את מה שנשלח למשתמש."""

    def __init__(self):
        self.sent = []
        self.answers = []
        self.data = ""

    async def answer(self, text=None, **_kwargs):
        self.answers.append(text)

    async def edit_message_text(self, text=None, **kwargs):
        self.sent.append(text)


def _update(query, user_id=555):
    return SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=user_id))


@pytest.fixture
def ch(monkeypatch):
    """טוען את ``conversation_handlers`` עם גישה לקובץ מדומה."""
    sys.modules.pop("conversation_handlers", None)
    mod = __import__("conversation_handlers")
    monkeypatch.setattr(
        mod,
        "_get_owned_document_by_id",
        lambda uid, fid: (
            {"file_name": "a.py", "code": "print(1)", "programming_language": "python"},
            False,
        ),
    )
    return mod


@pytest.mark.asyncio
async def test_user_without_github_sees_connect_guidance(ch, monkeypatch):
    """בלי חיבור GitHub מוצגת הנחיית חיבור — לא הודעת שגיאה גנרית."""
    monkeypatch.setattr(
        integrations,
        "resolve_gist_for_user",
        lambda uid: integrations.GistResolution(None, integrations.GIST_NEEDS_GITHUB_MESSAGE),
    )
    query = _Query()

    await ch.share_single_by_id(_update(query), SimpleNamespace(user_data={}), "gist", FILE_ID)

    assert query.sent == [integrations.GIST_NEEDS_GITHUB_MESSAGE]


@pytest.mark.asyncio
async def test_temporary_failure_does_not_ask_to_connect(ch, monkeypatch):
    """תקלה זמנית לא שולחת משתמש מחובר לחבר חשבון שכבר מחובר."""
    monkeypatch.setattr(
        integrations,
        "resolve_gist_for_user",
        lambda uid: integrations.GistResolution(
            None, integrations.GIST_TEMPORARY_FAILURE_MESSAGE
        ),
    )
    query = _Query()

    await ch.share_single_by_id(_update(query), SimpleNamespace(user_data={}), "gist", FILE_ID)

    assert query.sent == [integrations.GIST_TEMPORARY_FAILURE_MESSAGE]
    assert integrations.GIST_NEEDS_GITHUB_MESSAGE not in query.sent


@pytest.mark.asyncio
async def test_successful_share_returns_the_gist_url(ch, monkeypatch):
    """הצלחה מציגה את הקישור שחזר מ-GitHub."""
    created = []

    class _Gist:
        def create_gist(self, file_name, code, language, description=""):
            created.append(file_name)
            return {"url": "https://gist.github.com/abc123"}

    monkeypatch.setattr(
        integrations,
        "resolve_gist_for_user",
        lambda uid: integrations.GistResolution(_Gist(), None),
    )
    query = _Query()

    await ch.share_single_by_id(_update(query), SimpleNamespace(user_data={}), "gist", FILE_ID)

    assert created == ["a.py"]
    assert any("https://gist.github.com/abc123" in text for text in query.sent)


@pytest.mark.asyncio
async def test_failed_creation_reports_failure_not_success(ch, monkeypatch):
    """``create_gist`` מחזירה ``None`` בכשל — אסור לדווח הצלחה.

    זה דפוס K11: הפונקציה לא זורקת, אז ``except`` לבדו לא היה תופס כלום
    והמשתמש היה מקבל ✅ על Gist שלא נוצר.
    """

    class _FailingGist:
        def create_gist(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        integrations,
        "resolve_gist_for_user",
        lambda uid: integrations.GistResolution(_FailingGist(), None),
    )
    query = _Query()

    await ch.share_single_by_id(_update(query), SimpleNamespace(user_data={}), "gist", FILE_ID)

    assert query.sent, "המשתמש לא קיבל שום הודעה"
    assert all("gist.github.com" not in text for text in query.sent)
    assert any("נכשל" in text for text in query.sent)


@pytest.mark.asyncio
async def test_blocking_work_runs_off_the_event_loop(ch, monkeypatch):
    """אימות בזמן ריצה: שתי הקריאות החוסמות רצות בת'רד אחר.

    בדיקת ה-AST מאמתת את צורת הקוד; כאן מאמתים את ההתנהגות בפועל, כי
    ``to_thread`` שנקרא על עטיפה שכבר עשתה את העבודה היה עובר את ה-AST.
    """
    main_thread = threading.current_thread().ident
    threads = {}

    def _resolve(_uid):
        threads["resolve"] = threading.current_thread().ident
        return integrations.GistResolution(_Gist(), None)

    class _Gist:
        def create_gist(self, *_args, **_kwargs):
            threads["create"] = threading.current_thread().ident
            return {"url": "https://gist.github.com/abc123"}

    monkeypatch.setattr(integrations, "resolve_gist_for_user", _resolve)
    query = _Query()

    await ch.share_single_by_id(_update(query), SimpleNamespace(user_data={}), "gist", FILE_ID)

    assert threads["resolve"] != main_thread, "טעינת הטוקן רצה על ה-event loop"
    assert threads["create"] != main_thread, "יצירת ה-Gist רצה על ה-event loop"

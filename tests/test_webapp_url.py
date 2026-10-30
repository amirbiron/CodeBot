"""כתובת ה-WebApp — ``webapp_url.py``, הקורא היחיד של ``WEBAPP_URL``, וההתנהגות של הצרכנים כשאין כתובת.

שני דברים נבדקים כאן. הראשון: הפורמט — רק ``https://host[:port]``, וכל ערך אחר "פגום" ומטופל כמו חסר.
השני, שהוא הסיבה לכל השינוי: **בלי כתובת תקינה, שום צרכן לא מפנה לכתובת אחרת**. עד אוקטובר 2026 בשישה
מקומות הייתה כתובת השירות באורגון כברירת מחדל, ושירות שלא קיבל את המשתנה המשיך להפנות לשם בשקט. כאן נבדק
שכל צרכן מוותר על הקישור (כפתור, שורה, כפתור התראה) — ושהמצב מוצג (לוג, ``/health``, ``/healthz``).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import types
from urllib.parse import urlparse

import pytest

from webapp_url import (
    STATE_CONFIGURED,
    STATE_INVALID,
    STATE_MISSING,
    log_webapp_url_status,
    webapp_base_url,
    webapp_base_url_for_request,
    webapp_link,
    webapp_url_status,
)

GOOD = "https://webapp.test"


@pytest.fixture(autouse=True)
def _no_url(monkeypatch):
    """מצב התחלה ידוע: אין כתובת. טסט שצריך כתובת מגדיר אותה בעצמו."""
    monkeypatch.delenv("WEBAPP_URL", raising=False)


# ---------------------------------------------------------------------------
# הפורמט
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [GOOD, "https://code-keeper.example.com", "https://h:8443", "https://a-b.c-d.example"])
def test_a_clean_https_origin_is_configured(monkeypatch, value):
    monkeypatch.setenv("WEBAPP_URL", value)
    status = webapp_url_status()
    assert (status.state, status.url, status.problem) == (STATE_CONFIGURED, value, None)
    assert webapp_base_url() == value


def test_surrounding_whitespace_is_not_part_of_the_value(monkeypatch):
    monkeypatch.setenv("WEBAPP_URL", f"  {GOOD}\n")
    assert webapp_base_url() == GOOD


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing(monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("WEBAPP_URL", value)
    status = webapp_url_status()
    assert (status.state, status.url, status.problem) == (STATE_MISSING, None, None)
    assert webapp_base_url() is None


@pytest.mark.parametrize(
    "value, problem",
    [
        ("http://webapp.test", "not_https"),
        ("HTTPS://webapp.test", "not_https"),
        ("webapp.test", "not_https"),
        (f"{GOOD}/", "trailing_slash"),
        (f"{GOOD}/app", "has_path"),
        (f"{GOOD}?", "has_path"),
        (f"{GOOD}?a=1", "has_path"),
        (f"{GOOD}#x", "has_path"),
        ("https://user:secret@webapp.test", "bad_host"),
        ("https://exa mple.test", "bad_host"),
        ("https://[::1]", "bad_host"),
        ("https://[bad", "bad_host"),
        ("https:///path", "bad_host"),
        ("https://webapp.test:", "bad_host"),
        ("https://webapp.test:99999", "bad_port"),
        ("https://webapp.test:0", "bad_port"),
    ],
)
def test_invalid_values_are_treated_as_missing(monkeypatch, value, problem):
    monkeypatch.setenv("WEBAPP_URL", value)
    status = webapp_url_status()
    assert (status.state, status.url, status.problem) == (STATE_INVALID, None, problem)
    assert webapp_base_url() is None


def test_webapp_link_joins_a_path(monkeypatch):
    monkeypatch.setenv("WEBAPP_URL", GOOD)
    assert webapp_link("/files?q=a#results") == f"{GOOD}/files?q=a#results"


def test_webapp_link_is_none_without_a_url():
    assert webapp_link("/files") is None


@pytest.mark.parametrize("path", ["files", "", None, "https://other.test/x"])
def test_webapp_link_refuses_a_path_that_is_not_absolute(monkeypatch, path):
    """נתיב בלי ``/`` בהתחלה הוא באג של הקורא — זורק, גם כשאין כתובת, כדי שלא יתגלה רק בפרודקשן."""
    with pytest.raises(ValueError):
        webapp_link(path)
    monkeypatch.setenv("WEBAPP_URL", GOOD)
    with pytest.raises(ValueError):
        webapp_link(path)


def test_inside_a_webapp_request_the_fallback_is_the_request_address(monkeypatch):
    request = types.SimpleNamespace(url_root="http://self.test/")
    assert webapp_base_url_for_request(request) == "http://self.test"
    monkeypatch.setenv("WEBAPP_URL", GOOD)
    assert webapp_base_url_for_request(request) == GOOD
    monkeypatch.setenv("WEBAPP_URL", f"{GOOD}/")  # פגום — כמו חסר
    assert webapp_base_url_for_request(request) == "http://self.test"


# ---------------------------------------------------------------------------
# הלוג בעלייה
# ---------------------------------------------------------------------------


def test_the_startup_line_is_info_when_configured(monkeypatch, caplog):
    monkeypatch.setenv("WEBAPP_URL", GOOD)
    with caplog.at_level(logging.INFO, logger="t.webapp_url"):
        status = log_webapp_url_status(logging.getLogger("t.webapp_url"), service="bot")
    assert status.state == STATE_CONFIGURED
    assert [(r.levelno, GOOD in r.getMessage()) for r in caplog.records] == [(logging.INFO, True)]


def test_the_startup_line_is_an_error_when_missing(caplog):
    with caplog.at_level(logging.INFO, logger="t.webapp_url"):
        log_webapp_url_status(logging.getLogger("t.webapp_url"), service="bot")
    assert [r.levelno for r in caplog.records] == [logging.ERROR]
    assert "not set" in caplog.records[0].getMessage()


def test_an_invalid_value_is_logged_by_its_problem_and_never_by_its_value(monkeypatch, caplog):
    """ערך פגום יכול לשאת משתמש וסיסמה — הלוג נושא את קוד הבעיה בלבד."""
    monkeypatch.setenv("WEBAPP_URL", "https://admin:hunter2@webapp.test")
    with caplog.at_level(logging.INFO, logger="t.webapp_url"):
        log_webapp_url_status(logging.getLogger("t.webapp_url"), service="mcp")
    [record] = caplog.records
    assert record.levelno == logging.ERROR
    assert "bad_host" in record.getMessage()
    assert "hunter2" not in record.getMessage() and "admin" not in record.getMessage()


# ---------------------------------------------------------------------------
# הצרכנים בבוט
# ---------------------------------------------------------------------------


class _Btn:
    def __init__(self, text, callback_data=None, url=None, **_):
        self.text = text
        self.callback_data = callback_data
        self.url = url


def _button_urls(rows):
    return [b.url for row in rows for b in row if getattr(b, "url", None)]


def _run_community_catalog_menu(monkeypatch):
    import conversation_handlers as ch

    captured = {}

    async def _edit(query, text, reply_markup=None, parse_mode=None):
        captured["rows"] = reply_markup

    async def _answer(*_a, **_k):
        return None

    monkeypatch.setattr(ch, "InlineKeyboardButton", _Btn)
    monkeypatch.setattr(ch, "InlineKeyboardMarkup", lambda rows: rows)
    monkeypatch.setattr(ch, "_safe_edit_message_text", _edit)
    monkeypatch.setattr(ch, "_safe_answer", _answer)
    update = types.SimpleNamespace(callback_query=types.SimpleNamespace())
    asyncio.run(ch.community_catalog_menu(update, types.SimpleNamespace()))
    return captured["rows"]


def test_the_community_menu_has_no_web_button_without_a_url(monkeypatch):
    rows = _run_community_catalog_menu(monkeypatch)
    assert _button_urls(rows) == []
    # שאר התפריט נשאר: הוספת מוצר וחזרה.
    assert [b.callback_data for row in rows for b in row] == ["community_submit", "community_hub"]


def test_the_community_menu_web_button_uses_the_url(monkeypatch):
    """הבקרה של הטסט שלמעלה: עם כתובת הכפתור קיים, כלומר הטסט ההוא מדד את היעדר הכתובת."""
    monkeypatch.setenv("WEBAPP_URL", GOOD)
    rows = _run_community_catalog_menu(monkeypatch)
    assert _button_urls(rows) == [f"{GOOD}/community-library"]


def test_the_approval_notice_drops_the_link_without_a_url(monkeypatch):
    import conversation_handlers as ch

    assert ch._approval_notice("אושר.", "/snippets") == "אושר."
    monkeypatch.setenv("WEBAPP_URL", GOOD)
    assert ch._approval_notice("אושר.", "/snippets") == f"אושר.\nאפשר לצפות כאן: {GOOD}/snippets"


def test_the_help_page_shows_the_configured_address_or_none(monkeypatch):
    import conversation_handlers as ch

    [page] = [p for p in ch.HELP_PAGES if ch._HELP_WEBAPP_ADDRESS_SLOT in p]
    without = ch._render_help_page(page)
    assert ch._HELP_WEBAPP_ADDRESS_SLOT not in without and "🔗 כתובת" not in without
    monkeypatch.setenv("WEBAPP_URL", GOOD)
    assert ch._render_help_page(page).endswith("\n\n🔗 כתובת: webapp.test")


def test_a_login_request_without_a_url_says_so_and_creates_no_token(monkeypatch):
    import conversation_handlers as ch

    calls = []
    monkeypatch.setattr(ch, "_call_files_api", lambda name, *a, **k: calls.append(name))
    monkeypatch.setattr(ch.user_stats, "log_user", lambda *a, **k: None)
    monkeypatch.setattr(ch, "reporter", types.SimpleNamespace(report_activity=lambda uid: None))
    replies = []

    async def _reply(text, **kwargs):
        replies.append(text)

    update = types.SimpleNamespace(
        message=types.SimpleNamespace(reply_text=_reply),
        effective_user=types.SimpleNamespace(id=7, username="u", first_name="U"),
    )
    result = asyncio.run(ch.start_command(update, types.SimpleNamespace(args=["webapp_login"], user_data={})))

    assert result == ch.ConversationHandler.END
    assert len(replies) == 1 and "לא זמין" in replies[0]
    assert "insert_webapp_login_token" not in calls


@pytest.mark.parametrize(
    "flag, url, shown",
    [
        (None, GOOD, False),
        ("false", GOOD, False),
        ("true", None, False),
        ("true", f"{GOOD}/", False),
        ("true", GOOD, True),
        ("TRUE", GOOD, True),
    ],
)
def test_the_internal_share_link_needs_its_flag_and_a_url(monkeypatch, flag, url, shown):
    """הכפתור היה כבוי כי ``PUBLIC_BASE_URL`` לא הוגדר. אחרי ביטול המשתנה הוא נשאר כבוי עד שהדגל דלוק."""
    import bot_handlers as bh

    if flag is None:
        monkeypatch.delenv("ENABLE_INTERNAL_SHARE_LINKS", raising=False)
    else:
        monkeypatch.setenv("ENABLE_INTERNAL_SHARE_LINKS", flag)
    if url is not None:
        monkeypatch.setenv("WEBAPP_URL", url)
    assert bh._internal_share_links_enabled() is shown


# ---------------------------------------------------------------------------
# ההתראות
# ---------------------------------------------------------------------------


def _forward_one_alert(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")
    fake_obs = types.SimpleNamespace(emit_event=lambda *a, **k: None)
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)
    import alert_forwarder as af

    importlib.reload(af)
    posts = []

    def _pooled(method, url, json=None, timeout=5):  # noqa: ARG001
        posts.append((url, json))
        return types.SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    monkeypatch.setattr(af, "_pooled_request", _pooled)
    af.forward_alerts([{"status": "firing", "labels": {"alertname": "HighErrorRate", "severity": "error"},
                        "annotations": {"summary": "x"}}])
    by_host = {urlparse(url).hostname: payload or {} for url, payload in posts}
    return by_host["api.telegram.org"], by_host["hooks.slack.test"]


def test_an_alert_without_a_url_still_goes_out_without_a_dashboard_link(monkeypatch):
    telegram, slack = _forward_one_alert(monkeypatch)
    assert "reply_markup" not in telegram  # כפתור בלי url נדחה בטלגרם — ואז ההתראה כולה לא הייתה יוצאת
    assert "📊 Dashboard" not in str(slack.get("text") or "")
    assert "x" in str(telegram.get("text") or "")


def test_an_alert_with_a_url_carries_the_dashboard_link(monkeypatch):
    """הבקרה: אותה התראה עם כתובת — הכפתור והשורה חוזרים, כלומר הטסט שלמעלה מדד את היעדר הכתובת."""
    monkeypatch.setenv("WEBAPP_URL", GOOD)
    telegram, slack = _forward_one_alert(monkeypatch)
    assert telegram["reply_markup"]["inline_keyboard"][0][0]["url"] == f"{GOOD}/admin/observability"
    assert f"📊 Dashboard: {GOOD}/admin/observability" in str(slack.get("text") or "")


def test_a_relative_quick_fix_link_stays_relative_without_a_url():
    from services.observability_dashboard import _absolute_for_chat

    assert _absolute_for_chat("/admin/docs-index") == "/admin/docs-index"


# ---------------------------------------------------------------------------
# מצב היועץ
# ---------------------------------------------------------------------------


def test_the_knowledge_file_carries_no_address_of_its_own():
    from services import advisor_service as adv

    knowledge = adv.KNOWLEDGE_FILE.read_text(encoding="utf-8")
    assert "onrender.com" not in knowledge
    assert knowledge.count(adv.WEBAPP_SECTION_START) == knowledge.count(adv.WEBAPP_SECTION_END) == 1


def test_the_gallery_section_follows_the_url():
    from services import advisor_service as adv

    knowledge = adv.KNOWLEDGE_FILE.read_text(encoding="utf-8").strip()
    with_url = adv.render_knowledge(knowledge, GOOD)
    assert f"{GOOD}/gallery" in with_url
    assert "webapp-link" not in with_url and adv.WEBAPP_URL_TOKEN not in with_url
    without = adv.render_knowledge(knowledge, None)
    assert "/gallery" not in without and "גלריית צילומי מסך" not in without
    assert "webapp-link" not in without and adv.WEBAPP_URL_TOKEN not in without


def test_a_token_outside_the_marked_section_is_a_bug_in_the_file():
    from services import advisor_service as adv

    text = f"{adv.WEBAPP_SECTION_START}\nx\n{adv.WEBAPP_SECTION_END}\nראו {adv.WEBAPP_URL_TOKEN}/gallery"
    with pytest.raises(RuntimeError):
        adv.render_knowledge(text, None)


# ---------------------------------------------------------------------------
# הוובאפ ושירות ה-MCP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, state, url, problem",
    [
        (None, STATE_MISSING, None, None),
        (f"{GOOD}/", STATE_INVALID, None, "trailing_slash"),
        (GOOD, STATE_CONFIGURED, GOOD, None),
    ],
)
def test_webapp_health_shows_the_url_state(monkeypatch, value, state, url, problem):
    import webapp.app as app_mod

    if value is not None:
        monkeypatch.setenv("WEBAPP_URL", value)
    app_mod.app.testing = True
    with app_mod.app.test_client() as client:
        config = client.get("/health").get_json()["config"]
    assert config["WEBAPP_URL"] == url
    assert config["WEBAPP_URL_STATUS"] == state
    assert config.get("WEBAPP_URL_PROBLEM") == problem


def test_a_webapp_link_without_a_url_points_at_the_service_itself(monkeypatch):
    """בתוך בקשה לוובאפ, בלי כתובת — הכתובת שהבקשה הגיעה אליה, ולא כתובת של שירות אחר."""
    import webapp.app as app_mod

    with app_mod.app.test_request_context("/x", base_url="http://self.test"):
        assert app_mod._webapp_base_url() == "http://self.test"
    monkeypatch.setenv("WEBAPP_URL", GOOD)
    with app_mod.app.test_request_context("/x", base_url="http://self.test"):
        assert app_mod._webapp_base_url() == GOOD


def test_the_drive_redirect_uri_comes_from_the_same_place(monkeypatch):
    import webapp.app as app_mod
    from webapp import drive_auth

    monkeypatch.setenv("WEBAPP_URL", GOOD)
    with app_mod.app.test_request_context("/x", base_url="http://self.test"):
        assert drive_auth._get_redirect_uri() == f"{GOOD}/api/drive/callback"


@pytest.mark.parametrize("value, state", [(None, STATE_MISSING), ("http://web.test", STATE_INVALID), (GOOD, STATE_CONFIGURED)])
def test_mcp_healthz_shows_the_url_state_without_the_value(monkeypatch, value, state):
    from mcp_server.server import _healthz

    if value is not None:
        monkeypatch.setenv("WEBAPP_URL", value)
    body = json.loads(asyncio.run(_healthz(None)).body)
    assert body == {"status": "ok", "service": "codekeeper-mcp", "webapp_url": state}

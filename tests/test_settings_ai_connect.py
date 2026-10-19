"""הסעיף "חיבור סוכן AI" בעמוד ההגדרות — מה שהשרת מרנדר, בלי דפדפן.

טסטי הדפדפן של הסעיף (``tests/test_settings_ai_connect_browser.py``) מדולגים ב-CI, שאין
בו Chromium. הקובץ הזה רץ שם, ומקבע את מה שנקבע בצד השרת: הכתובת שנבנית מ-``MCP_SERVER_URL``
(``_mcp_connect_url`` ב-``webapp/routes/settings_routes.py``), מה קורה כשהוא חסר או נדחה,
הקישור לבוט, העוגן וקישור העזרה. ובאותו עמוד גם ההסבר המתקפל "איך מחברים את זה ל-Claude Code?"
בכרטיס "הוראות לסוכן", שמתאר את ההוק ב-``.claude/hooks/codekeeper-primer.sh``.

``get_db`` מוחלף ב-``None`` — החוזה הקיים של "אין מסד" — כדי שהעמוד לא ינסה להתחבר.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from mcp_server.public_url import MCP_ENDPOINT_PATH
from webapp import app as webapp_app

BASE = "https://mcp.example.test"
ROUTE_LOGGER = "webapp.routes.settings_routes"
URL_ROW = re.compile(r'<code class="ai-connect__code" dir="ltr" id="ai-connect-url-([^"]+)">([^<]*)</code>')
PRIMER_HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "codekeeper-primer.sh"


class _CacheDisabled:
    is_enabled = False


def _render(monkeypatch, mcp_server_url: str | None) -> str:
    if mcp_server_url is None:
        monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    else:
        monkeypatch.setenv("MCP_SERVER_URL", mcp_server_url)
    monkeypatch.setattr(webapp_app, "get_db", lambda: None, raising=True)
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)
    with webapp_app.app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 123
            sess["user_data"] = {"id": 123, "first_name": "Test", "is_admin": False, "is_premium": False}
        response = client.get("/settings")
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize("value", [BASE, BASE + "/", f"  {BASE}  "])
def test_the_url_is_the_configured_base_followed_by_the_mcp_path(monkeypatch, value):
    """אותה קריאה כמו בשער של ``/oauth/identify``: ``strip``, ובלי ``/`` כפול לפני הנתיב."""
    html = _render(monkeypatch, value)
    assert URL_ROW.findall(html) == [("claude-web", BASE + MCP_ENDPOINT_PATH), ("gemini", BASE + MCP_ENDPOINT_PATH)]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_without_a_url_there_is_no_url_row_and_nothing_is_logged(monkeypatch, caplog, value):
    """לא הוגדר — מצב מוכר, ולא תקלה: בלי שורת כתובת, בלי טקסט חלופי ובלי WARNING."""
    with caplog.at_level(logging.WARNING, logger=ROUTE_LOGGER):
        html = _render(monkeypatch, value)
    assert 'id="ai-connect"' in html
    assert URL_ROW.findall(html) == []
    assert "ai-connect__url" not in html.split('id="ai-connect"', 1)[1].split("</script>", 1)[0]
    assert [r for r in caplog.records if r.name == ROUTE_LOGGER] == []


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("https://user:hunter2@mcp.example.test", "carries a user name or password"),
        ("https://mcp.example.test/?token=hunter2", "carries a query or a fragment"),
        ("ftp://mcp.example.test/hunter2", "scheme is not http or https"),
    ],
)
def test_a_rejected_url_is_not_shown_and_is_logged_by_its_reason_only(monkeypatch, caplog, value, reason):
    """ערך שנדחה אינו מגיע לאף משתמש, ובלוג נרשמת הסיבה — לא הערך, שעלול להיות סוד (K13)."""
    with caplog.at_level(logging.WARNING, logger=ROUTE_LOGGER):
        html = _render(monkeypatch, value)
    assert URL_ROW.findall(html) == []
    assert "hunter2" not in html
    records = [r for r in caplog.records if r.name == ROUTE_LOGGER]
    assert [r.levelno for r in records] == [logging.WARNING]
    message = records[0].getMessage()
    assert reason in message
    assert "hunter2" not in message


@pytest.mark.parametrize("username", ["some_test_bot", ""])
def test_the_bot_link_is_built_from_the_configured_username(monkeypatch, username):
    """``bot_username`` מגיע מ-``BOT_USERNAME``; כשהוא ריק אין קישור שבור ל-``https://t.me/``."""
    monkeypatch.setattr(webapp_app, "BOT_USERNAME_CLEAN", username, raising=True)
    html = _render(monkeypatch, BASE)
    panel = html.split('id="ai-connect-panel-claude-code"', 1)[1].split("</script>", 1)[0]
    links = re.findall(r'href="(https://t\.me/[^"]*)"', panel)
    assert links == ([f"https://t.me/{username}"] if username else [])
    # הפקודה עצמה מוצגת גם בלי קישור.
    assert '<code dir="ltr">/connect_claude</code>' in panel


def test_the_anchor_and_the_help_link_are_rendered_once(monkeypatch):
    html = _render(monkeypatch, BASE)
    assert html.count('id="ai-connect"') == 1
    help_links = re.findall(r'<p class="settings-help-link">.*?<a href="([^"]+)"', html, flags=re.S)
    assert help_links == ["https://t.me/moominAmir"]


def _primer_setup(html: str) -> str:
    """הבלוק המתקפל "איך מחברים את זה ל-Claude Code?" בכרטיס "הוראות לסוכן"."""
    assert html.count('id="agent-primer-setup"') == 1
    return html.split('id="agent-primer-setup"', 1)[1].split("</details>", 1)[0]


def test_the_primer_setup_names_the_variable_and_the_host_the_hook_uses(monkeypatch):
    """ההסבר חוזר על שתי עובדות שהבעלים שלהן הוא ההוק: שם המשתנה שהוא שולח כטוקן, והשרת
    שהוא פונה אליו כשלא הוגדר ``CODEKEEPER_PRIMER_URL``. שתיהן נגזרות כאן מהסקריפט עצמו, כך
    ששינוי שם או כתובת שם מפיל את הטסט, ולא משאיר בעמוד הסבר שמוביל להוק שלא מגיע לשרת."""
    script = PRIMER_HOOK.read_text(encoding="utf-8")
    variable = re.search(r'"Authorization: Bearer \$\{(\w+)\}"', script)
    host = re.search(r'^PRIMER_URL="\$\{CODEKEEPER_PRIMER_URL:-https://([^/"]+)/', script, flags=re.M)
    assert variable and host, "הצורה של הכותרת או של PRIMER_URL השתנתה בסקריפט — עדכנו את הגזירה כאן"

    block = _primer_setup(_render(monkeypatch, BASE))
    assert f'<code dir="ltr">{variable.group(1)}=</code>' in block
    assert f'<code dir="ltr">{host.group(1)}</code>' in block


@pytest.mark.parametrize("username", ["some_test_bot", ""])
def test_the_primer_setup_links_the_configured_bot(monkeypatch, username):
    """כמו בלשונית של Claude Code בטרמינל: הקישור נבנה מ-``BOT_USERNAME``, ובלעדיו אין קישור שבור."""
    monkeypatch.setattr(webapp_app, "BOT_USERNAME_CLEAN", username, raising=True)
    block = _primer_setup(_render(monkeypatch, BASE))
    links = re.findall(r'href="(https://t\.me/[^"]*)"', block)
    assert links == ([f"https://t.me/{username}"] if username else [])
    assert (f">@{username}</a>" in block) == bool(username)
    assert '<code dir="ltr">/connect_claude</code>' in block

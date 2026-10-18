"""עמוד הבית (``/``): מה מופיע בראש העמוד לכל מבקר, ומה כבר לא מופיע בו.

- **בראש העמוד.** מבקר שלא התחבר מקבל את ההתחברות ואת הבוט. משתמש מחובר מקבל ברכה עם השם שלו, ואת הדשבורד והקבצים. הקישורים נגזרים מה-HTML שנוצר, בתוך האזור שמסומן ב-``data-testid`` של המצב שרונדר — הסרגל העליון מקשר גם הוא לדשבורד ולקבצים, ולכן חיפוש בכל העמוד לא היה מבחין.
- **בלי סטטיסטיקות.** הן ירדו מהעמוד, וגם הקוד שחישב אותן בכל כניסה: ה-route לא קורא ל-``fetch_external_uptime``, והעמוד לא מושך את ``/api/public_stats`` ואת ``/api/uptime``. שני ה-API עצמם נשארו.
- **הקרדיט למפתח** עבר מהמסך לנתונים המובנים: ``author`` ב-JSON-LD.

הקישור למדיניות הפרטיות בתחתית העמוד נבדק ב-``tests/test_privacy_page.py``.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser

import pytest

pytest.importorskip("flask")


#: תגיות בלי תגית סגירה ב-HTML — הן אינן פותחות רמה, ובלעדיהן ספירת העומק לא הייתה חוזרת לאפס
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _ActionLinks(HTMLParser):
    """ה-``href`` של כל ``<a>`` בתוך האלמנט שה-``data-testid`` שלו נמסר — כמו שהמבקר רואה ולוחץ."""

    def __init__(self, testid: str) -> None:
        super().__init__()
        self._testid = testid
        self._depth = 0
        self.found = False
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self._depth:
            if tag == "a":
                self.hrefs.append(attrs.get("href") or "")
            if tag not in _VOID_TAGS:
                self._depth += 1
        elif attrs.get("data-testid") == self._testid:
            self.found = True
            self._depth = 1

    def handle_startendtag(self, tag, attrs):
        # ``<x />`` נסגרת בעצמה, ולכן אינה פותחת רמה
        if self._depth and tag == "a":
            self.hrefs.append(dict(attrs).get("href") or "")

    def handle_endtag(self, tag):
        if self._depth and tag not in _VOID_TAGS:
            self._depth -= 1


def _actions(html: str, testid: str) -> _ActionLinks:
    parser = _ActionLinks(testid)
    parser.feed(html)
    return parser


def _client():
    from webapp import app as webapp_app

    return webapp_app.app.test_client()


def _home_html(client) -> str:
    resp = client.get("/")
    assert resp.status_code == 200, resp.status_code
    return resp.get_data(as_text=True)


def test_guest_gets_login_and_bot_at_the_top():
    from webapp import app as webapp_app

    html = _home_html(_client())

    guest = _actions(html, "home-actions-guest")
    assert guest.found
    assert guest.hrefs == ["/login", f"https://t.me/{webapp_app.BOT_USERNAME_CLEAN}"]
    assert not _actions(html, "home-actions-member").found


def test_member_gets_greeting_dashboard_and_files_at_the_top(monkeypatch):
    from webapp import app as webapp_app

    monkeypatch.setitem(webapp_app.app.config, "SECRET_KEY", "home-page-tests")
    client = _client()
    with client.session_transaction() as sess:
        sess["user_id"] = 42
        sess["user_data"] = {"id": 42, "first_name": "Dana"}

    html = _home_html(client)

    member = _actions(html, "home-actions-member")
    assert member.found
    assert member.hrefs == ["/dashboard", "/files"]
    assert "שלום Dana! 👋" in html
    assert not _actions(html, "home-actions-guest").found


def test_the_page_neither_computes_nor_fetches_stats(monkeypatch):
    """הדמה **סופרת** קריאות ולא זורקת: הקוד הישן עטף את הקריאה ב-``except Exception``, ודמה שזורקת הייתה נבלעת שם והטסט היה עובר גם עליו."""
    from webapp import app as webapp_app

    calls: list[int] = []
    monkeypatch.setattr(webapp_app, "fetch_external_uptime", lambda: calls.append(1))

    html = _home_html(_client())

    assert calls == []
    assert "/api/public_stats" not in html
    assert "/api/uptime" not in html


def test_structured_data_names_the_author():
    html = _home_html(_client())

    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert len(blocks) == 1, blocks
    data = json.loads(blocks[0])
    assert data["@context"] == "https://schema.org"
    assert data["@type"] == "WebApplication"
    assert data["name"] == "CodeKeeper"
    assert data["author"] == {"@type": "Person", "name": "אמיר בירון"}
    # התיאור הוא אותו משפט שמוצג בראש העמוד — מוגדר פעם אחת בתבנית
    assert data["description"] and data["description"] in html.replace(blocks[0], "")

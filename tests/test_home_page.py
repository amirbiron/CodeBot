"""עמוד הבית (``/``): מה מופיע בראש העמוד לכל מבקר, ומה כבר לא מופיע בו.

- **בראש העמוד.** מבקר שלא התחבר מקבל את ההתחברות ואת הבוט. משתמש מחובר מקבל ברכה עם השם שלו, ואת הדשבורד והקבצים. הקישורים נגזרים מה-HTML שנוצר, בתוך האזור שמסומן ב-``data-testid`` של המצב שרונדר — הסרגל העליון מקשר גם הוא לדשבורד ולקבצים, ולכן חיפוש בכל העמוד לא היה מבחין.
- **בלי סטטיסטיקות.** הן ירדו מהעמוד, וגם הקוד שחישב אותן בכל כניסה: ה-route לא קורא ל-``fetch_external_uptime``, והעמוד לא מושך את ``/api/public_stats`` ואת ``/api/uptime``. שני ה-API עצמם נשארו.
- **הקרדיט למפתח** עבר מהמסך לנתונים המובנים: ``author`` ב-JSON-LD.
- **התצוגה המקדימה של הקישור** (וואטסאפ, טלגרם, לינקדאין): תגיות ה-``og:`` ו-``twitter:card``, נבדקות כמו שהסורק קורא אותן — מתוך ה-HTML, והתמונה מהכתובת שב-``og:image``.

הקישור למדיניות הפרטיות בתחתית העמוד נבדק ב-``tests/test_privacy_page.py``.
"""

from __future__ import annotations

import html as html_lib
import io
import json
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

pytest.importorskip("flask")
Image = pytest.importorskip("PIL.Image")

#: התקרות של וואטסאפ, מ-https://developers.facebook.com/documentation/business-messaging/whatsapp/link-previews/ (נקרא ב-8.11.2026):
#: "This image should be under 600KB in size", "300px or more in width with 4:1 width/height or less aspect ratio",
#: ו-"The <head> containing the HTML mark-ups must appear within the first 300KB of the HTML". הדף לא אומר אם KB הוא 1000
#: או 1024 בתים, ולכן בשתי התקרות כאן הקטנה מבין השתיים.
WHATSAPP_IMAGE_MAX_BYTES = 600 * 1000
WHATSAPP_IMAGE_MIN_WIDTH = 300
WHATSAPP_IMAGE_MAX_RATIO = 4
WHATSAPP_HEAD_WINDOW_BYTES = 300 * 1000

#: התגיות שהעמוד מצהיר עליהן לתצוגה המקדימה: ``property`` של Open Graph, ``name`` של ``description`` ושל X
_PREVIEW_PROPERTIES = (
    "og:type",
    "og:site_name",
    "og:locale",
    "og:title",
    "og:description",
    "og:url",
    "og:image",
    "og:image:type",
    "og:image:width",
    "og:image:height",
    "og:image:alt",
)
_PREVIEW_NAMES = ("description", "twitter:card")

_RLM = "\u200f"


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


class _PreviewMeta(HTMLParser):
    """ה-``content`` של כל ``<meta>``, לפי ``property`` (Open Graph) או ``name`` (``description``, X) — כמו שהסורק של וואטסאפ קורא אותן. רשימה לכל מפתח, כדי שתגית כפולה תיראה."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = dict(attrs)
        key = a.get("property") or a.get("name")
        if key:
            self.tags.setdefault(key, []).append(a.get("content") or "")


def _is_absolute_http_url(parts) -> bool:
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def test_link_preview_tags_point_to_absolute_urls_and_a_servable_image():
    """מה שוואטסאפ וטלגרם צריכים כדי להציג תמונה, כותרת ותיאור לקישור לעמוד הבית.

    - כל תגית פעם אחת, לא ריקה — בלי כפילות עם ``base.html``.
    - ``og:title`` הוא ה-``<title>`` עם RLM בתחילתו, ו-``<title>`` עצמו בלי (ההסבר בהערה שב-``extra_head`` של ``index.html``).
    - כתובות מלאות ב-``og:url`` וב-``og:image``, ומזהה גרסה על התמונה, כמו בגלריה.
    - התמונה מתבקשת מהכתובת שב-``og:image``, כמו שהסורק מבקש אותה: עונה, בסוג ובגודל שהתגיות מצהירות, ובתקרות של וואטסאפ.
    - כל התגיות בתוך החלון שוואטסאפ קורא, למרות כל מה ש-``base.html`` מגיש לפני ``extra_head``.
    """
    client = _client()
    resp = client.get("/")
    assert resp.status_code == 200, resp.status_code
    body = resp.get_data()
    page = body.decode("utf-8")

    parser = _PreviewMeta()
    parser.feed(page)
    expected = _PREVIEW_PROPERTIES + _PREVIEW_NAMES
    counts = {key: len(parser.tags.get(key, [])) for key in expected}
    assert all(n == 1 for n in counts.values()), counts
    tags = {key: parser.tags[key][0] for key in expected}
    assert all(tags.values()), tags

    title = html_lib.unescape(re.search(r"<title>(.*?)</title>", page, re.S).group(1))
    assert not title.startswith(_RLM)
    assert tags["og:title"] == _RLM + title, (tags["og:title"], title)

    ld_json = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
    # התיאור — אותו משפט שבראש העמוד ובנתונים המובנים, ופותח בעברית, ולכן בלי RLM
    assert tags["og:description"] == tags["description"] == ld_json["description"]
    assert tags["twitter:card"] == "summary_large_image"

    og_url = urlsplit(tags["og:url"])
    assert _is_absolute_http_url(og_url) and og_url.path == "/" and not og_url.query, tags["og:url"]

    og_image = urlsplit(tags["og:image"])
    assert _is_absolute_http_url(og_image), tags["og:image"]
    assert re.fullmatch(r"v=[^&\s]+", og_image.query), tags["og:image"]

    image_resp = client.get(f"{og_image.path}?{og_image.query}")
    assert image_resp.status_code == 200, (og_image.path, image_resp.status_code)
    assert image_resp.mimetype == tags["og:image:type"]
    data = image_resp.get_data()
    assert len(data) < WHATSAPP_IMAGE_MAX_BYTES, len(data)
    with Image.open(io.BytesIO(data)) as im:
        assert Image.MIME[im.format] == tags["og:image:type"], im.format
        assert im.size == (int(tags["og:image:width"]), int(tags["og:image:height"])), im.size
        width, height = im.size
    assert width >= WHATSAPP_IMAGE_MIN_WIDTH and width <= WHATSAPP_IMAGE_MAX_RATIO * height, (width, height)

    for key in _PREVIEW_PROPERTIES:
        offset = body.find(f'property="{key}"'.encode())
        assert 0 < offset < WHATSAPP_HEAD_WINDOW_BYTES, (key, offset)
    for key in _PREVIEW_NAMES:
        offset = body.find(f'name="{key}"'.encode())
        assert 0 < offset < WHATSAPP_HEAD_WINDOW_BYTES, (key, offset)

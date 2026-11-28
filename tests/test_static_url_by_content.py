"""``?v=`` לפי התוכן של הקובץ (``static_url_by_content`` ב-``webapp/app.py``): צילומי הגלריה ותמונות ה-``og:image``.

גוגל מאנדקס את צילומי הגלריה לפי הכתובת שלהם, וואטסאפ וטלגרם שומרים את התצוגה המקדימה של קישור לפי הכתובת של התמונה. ``static_version`` מתחלף בכל דיפלוי, ולכן הכתובות האלה נגזרות מהתוכן: קובץ שלא השתנה שומר על הכתובת שלו בין דיפלויים, וקובץ שהתוכן שלו השתנה מקבל כתובת חדשה — כך שצילום שהוחלף באותו שם עדיין מגיע למבקרים. הבדיקות עוברות דרך מה שהצרכנים קוראים: העמודים וה-sitemap. הרקע: ``docs/webapp/gallery.rst``.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

pytest.importorskip("flask")

IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"

#: העמודים שיש בהם ``og:image`` שנגזר מהתוכן.
OG_PAGES = ("/", "/markdown-editor", "/gallery")


class _Images(HTMLParser):
    """``og:image``, וה-``src`` של הצילום שבסימון של הגלריה (``#galleryImage``)."""

    def __init__(self) -> None:
        super().__init__()
        self.og_image: str | None = None
        self.gallery_img: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("property") == "og:image":
            self.og_image = a.get("content")
        if tag == "img" and a.get("id") == "galleryImage":
            self.gallery_img = a.get("src")


def _path_and_query(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}"


def _image_urls(client, page_query: str = "") -> dict[str, str]:
    """כל כתובת של תמונה שנגזרת מהתוכן, כמו שהצרכנים רואים אותה — ``תווית ← נתיב?v=…``."""
    urls: dict[str, str] = {}
    gallery_html = ""
    for page in OG_PAGES:
        with client.get(page + page_query) as resp:
            assert resp.status_code == 200, (page, resp.status_code)
            text = resp.get_data(as_text=True)
        parser = _Images()
        parser.feed(text)
        assert parser.og_image, page
        urls[f"og:image {page}"] = parser.og_image
        if page == "/gallery":
            gallery_html = text
            assert parser.gallery_img
            urls["gallery <img>"] = parser.gallery_img

    m = re.search(r"var slides = (\[.*?\]);\n", gallery_html, re.S)
    assert m, "רשימת הצילומים לא נמצאה בסקריפט של הגלריה"
    for i, slide in enumerate(json.loads(m.group(1)), 1):
        urls[f"gallery slide {i}"] = slide["src"]

    with client.get("/sitemap.xml") as resp:
        sitemap = ET.fromstring(resp.get_data())
    for i, el in enumerate(sitemap.iter(f"{{{IMAGE_NS}}}loc"), 1):
        urls[f"sitemap image {i}"] = el.text
    return {label: _path_and_query(url) for label, url in urls.items()}


@pytest.fixture
def wa():
    import webapp.app as webapp_app

    return webapp_app


@pytest.fixture
def fresh_process(wa):
    """כל דיפלוי מעלה תהליך חדש, עם קאש ריק — קריאה ל-fixture מדמה אותו. הקאש מאופס גם לפני הטסט וגם אחריו, כדי
    שה-hash של קבצי הטסט לא יישאר בזיכרון של התהליך לטסטים שאחריו."""
    wa._static_content_version.cache_clear()
    yield wa._static_content_version.cache_clear
    wa._static_content_version.cache_clear()


def test_every_url_carries_the_hash_of_the_file_it_serves(wa, fresh_process):
    """כל כתובת נושאת ``?v=`` עם שמונת התווים הראשונים של SHA-256 של הקובץ שהיא מגישה — ולא את הגרסה של הדיפלוי."""
    from webapp.gallery import GALLERY_SLIDES

    client = wa.app.test_client()
    urls = _image_urls(client)

    assert len([label for label in urls if label.startswith("gallery slide ")]) == len(GALLERY_SLIDES)
    assert len([label for label in urls if label.startswith("sitemap image ")]) == len(GALLERY_SLIDES)
    for label, url in urls.items():
        path, _, query = url.partition("?")
        with client.get(path) as resp:
            assert resp.status_code == 200, (label, url, resp.status_code)
            body = resp.get_data()
        assert query == "v=" + hashlib.sha256(body).hexdigest()[:8], (label, url)


def test_a_deploy_changes_only_the_url_of_a_file_whose_content_changed(wa, fresh_process, tmp_path, monkeypatch):
    """דיפלוי שלא נגע בקובץ — אותה כתובת, גם כש-``static_version`` התחלף. דיפלוי שהחליף קובץ באותו שם — כתובת חדשה
    לקובץ הזה בלבד, בעמוד וב-sitemap. ``?nc=1`` (חותמת זמן ב-``static_version``) לא משנה את הכתובות האלה."""
    from webapp.gallery import GALLERY_SLIDES

    client = wa.app.test_client()

    # תיקיית static של הטסט, עם כל הקבצים שהכתובות מפנות אליהם, ותוכן שונה לכל אחד
    names = sorted({url.partition("?")[0].removeprefix("/static/") for url in _image_urls(client).values()})
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"first {name}".encode())
    monkeypatch.setattr(wa.app, "static_folder", str(tmp_path))
    fresh_process()
    before = _image_urls(client)

    # דיפלוי בלי שינוי בקבצים: גרסה אחרת לכל האתר, ותהליך חדש
    monkeypatch.setattr(wa, "_STATIC_VERSION", "deploy2")
    fresh_process()
    assert _image_urls(client) == before
    assert _image_urls(client, "?nc=1") == before

    # דיפלוי שמחליף את הצילום הראשון באותו שם
    replaced = "/static/gallery/" + GALLERY_SLIDES[0].image
    (tmp_path / replaced.removeprefix("/static/")).write_bytes(b"second")
    monkeypatch.setattr(wa, "_STATIC_VERSION", "deploy3")
    fresh_process()
    after = _image_urls(client)

    expected = {label for label, url in before.items() if url.partition("?")[0] == replaced}
    # הצילום מופיע ברשימה שבסקריפט, בסימון וב-sitemap
    assert {"gallery slide 1", "gallery <img>", "sitemap image 1"} <= expected
    assert {label for label in before if after[label] != before[label]} == expected
    assert all(after[label].partition("?")[0] == replaced for label in expected)

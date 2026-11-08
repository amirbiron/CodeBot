"""התצוגה המקדימה של קישור לעמוד ציבורי — מה שהסורק של וואטסאפ, טלגרם ולינקדאין קורא מה-HTML, ומה שהוא מבקש אחר כך מהכתובת שב-``og:image``.

משותף לעמודים שיש להם תמונת תצוגה מקדימה: ``tests/test_home_page.py`` ו-``tests/test_markdown_editor_page.py``. הכללים כאן הם של הסורק ולא של עמוד מסוים, ולכן הם במקום אחד: עמוד נוסף עם תמונה קורא לאותן שתי פונקציות. מה שייחודי לעמוד — הכותרת, התיאור, הכתובת — נבדק בקובץ שלו.

``tests/test_gallery_page.py`` בודק את התגיות של הגלריה בעצמו, מול הקבועים של ``scripts/build_gallery_image.py``, שמייצר את התמונה שלה.
"""

from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

#: התקרות של וואטסאפ, מ-https://developers.facebook.com/documentation/business-messaging/whatsapp/link-previews/ (נקרא ב-8.11.2026):
#: "This image should be under 600KB in size", "300px or more in width with 4:1 width/height or less aspect ratio",
#: ו-"The <head> containing the HTML mark-ups must appear within the first 300KB of the HTML". הדף לא אומר אם KB הוא 1000
#: או 1024 בתים, ולכן בשתי התקרות כאן הקטנה מבין השתיים.
WHATSAPP_IMAGE_MAX_BYTES = 600 * 1000
WHATSAPP_IMAGE_MIN_WIDTH = 300
WHATSAPP_IMAGE_MAX_RATIO = 4
WHATSAPP_HEAD_WINDOW_BYTES = 300 * 1000

#: התגיות של תצוגה מקדימה עם תמונה: ``property`` של Open Graph, ``name`` של ``description`` ושל X
PREVIEW_PROPERTIES = (
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
PREVIEW_NAMES = ("description", "twitter:card")


class _PreviewMeta(HTMLParser):
    """ה-``content`` של כל ``<meta>``, לפי ``property`` (Open Graph) או ``name`` (``description``, X) — כמו שהסורק קורא אותן. רשימה לכל מפתח, כדי שתגית כפולה תיראה."""

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


def is_absolute_http_url(url: str) -> bool:
    """כתובת מלאה — סכמה וכתובת שרת, כמו שוואטסאפ דורש ב-``og:image``. פירוק ולא בדיקת תחילית (K16)."""
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def read_preview_tags(body: bytes) -> dict[str, str]:
    """התגיות של התצוגה המקדימה מתוך ה-HTML שהעמוד הגיש, לפי מפתח.

    כל תגית מופיעה פעם אחת ואינה ריקה — כך גם תגית שנוספת ב-``base.html`` ומתנגשת בתגית של העמוד נופלת כאן — וכולן בתוך ``WHATSAPP_HEAD_WINDOW_BYTES`` הראשונים, למרות כל מה ש-``base.html`` מגיש לפני ``extra_head``.
    """
    parser = _PreviewMeta()
    parser.feed(body.decode("utf-8"))
    expected = PREVIEW_PROPERTIES + PREVIEW_NAMES
    counts = {key: len(parser.tags.get(key, [])) for key in expected}
    assert all(n == 1 for n in counts.values()), counts
    tags = {key: parser.tags[key][0] for key in expected}
    assert all(tags.values()), tags

    for attr, keys in (("property", PREVIEW_PROPERTIES), ("name", PREVIEW_NAMES)):
        for key in keys:
            offset = body.find(f'{attr}="{key}"'.encode())
            assert 0 < offset < WHATSAPP_HEAD_WINDOW_BYTES, (key, offset)
    return tags


def check_preview_image(client, tags: dict[str, str]) -> None:
    """התמונה שב-``og:image``, כמו שהסורק מבקש אותה.

    - כתובת מלאה, ומזהה גרסה (``?v=``), כי ``SEND_FILE_MAX_AGE_DEFAULT`` שומר סטטיקה לזמן ארוך.
    - הכתובת עונה, והתמונה בסוג שב-``og:image:type`` ובגודל שב-``og:image:width`` / ``og:image:height`` — נגזר מהקובץ שהוגש, כך שתמונה שהוחלפה בגודל אחר בלי לעדכן את התגיות נופלת כאן.
    - בתקרות של וואטסאפ (``WHATSAPP_IMAGE_*``).
    - ``twitter:card`` מסוג ``summary_large_image``, כי לעמוד יש תמונה להציג בגדול.
    """
    image_module = pytest.importorskip("PIL.Image")

    assert is_absolute_http_url(tags["og:image"]), tags["og:image"]
    og_image = urlsplit(tags["og:image"])
    assert re.fullmatch(r"v=[^&\s]+", og_image.query), tags["og:image"]
    assert tags["twitter:card"] == "summary_large_image", tags["twitter:card"]

    resp = client.get(f"{og_image.path}?{og_image.query}")
    assert resp.status_code == 200, (og_image.path, resp.status_code)
    assert resp.mimetype == tags["og:image:type"], resp.mimetype
    data = resp.get_data()
    assert len(data) < WHATSAPP_IMAGE_MAX_BYTES, (og_image.path, len(data))
    with image_module.open(io.BytesIO(data)) as im:
        assert image_module.MIME[im.format] == tags["og:image:type"], im.format
        declared = (int(tags["og:image:width"]), int(tags["og:image:height"]))
        assert im.size == declared, (og_image.path, im.size, declared)
        width, height = im.size
    assert width >= WHATSAPP_IMAGE_MIN_WIDTH and width <= WHATSAPP_IMAGE_MAX_RATIO * height, (width, height)

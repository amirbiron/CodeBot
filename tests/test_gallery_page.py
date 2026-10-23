"""גלריית צילומי המסך (``/gallery``) — ציבורית, נשענת על הקבצים שב-``static/gallery``, ומוכנה לשיתוף בוואטסאפ ובטלגרם.

העמוד מקושר מפוסטים בקבוצות, כלומר מבקר בלי סשן הוא המקרה הרגיל, והטסטים מבקשים אותו מ-client חדש. מה שנבדק כאן הוא מה שהשרת מגיש; ההתנהגות בדפדפן (החלקה, חיצים, זום, טעינה מראש) נמדדה בכרומיום, ותועדה ב-PR. הרקע: ``docs/webapp/gallery.rst``.
"""

from __future__ import annotations

import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

pytest.importorskip("flask")
Image = pytest.importorskip("PIL.Image")

REPO_ROOT = Path(__file__).resolve().parents[1]
GALLERY_DIR = REPO_ROOT / "webapp" / "static" / "gallery"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_gallery_image.py"


class _Meta(HTMLParser):
    """אוסף את תגיות ה-``<meta property=...>`` ואת ה-``src`` של כל ``<img>`` — כמו שהסורק של וואטסאפ והדפדפן רואים אותם."""

    def __init__(self) -> None:
        super().__init__()
        self.props: dict[str, str] = {}
        self.img_srcs: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("property"):
            self.props[a["property"]] = a.get("content") or ""
        if tag == "img" and a.get("src"):
            self.img_srcs.append(a["src"])


def _get_gallery():
    from webapp import app as webapp_app

    # client חדש, בלי session_transaction — כמו מבקר שהגיע מקישור בקבוצה
    return webapp_app.app.test_client().get("/gallery")


def _script_constant(name: str) -> int:
    """קורא קבוע מהסקריפט שמייצר את התמונות, בלי לייבא אותו (``scripts/`` אינו חבילה)."""
    tree = ast.parse(BUILD_SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            value = node.value
            # literal_eval לא מחשב ביטוי כמו ``300 * 1024``
            if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Mult):
                return ast.literal_eval(value.left) * ast.literal_eval(value.right)
            return ast.literal_eval(value)
    raise AssertionError(f"{name} לא נמצא ב-{BUILD_SCRIPT}")


def _rendered_slides(html: str) -> list[dict]:
    m = re.search(r"var slides = (\[.*?\]);\n", html, re.S)
    assert m, "רשימת הצילומים לא נמצאה בסקריפט של העמוד"
    return json.loads(m.group(1))


def test_gallery_answers_without_login():
    resp = _get_gallery()

    # 200 ישיר ולא הפניה ל-/login
    assert resp.status_code == 200, resp.status_code
    assert resp.mimetype == "text/html"


def test_slides_are_rendered_from_the_single_list_in_order():
    from webapp.gallery import GALLERY_SLIDES

    slides = _rendered_slides(_get_gallery().get_data(as_text=True))

    assert [(s["title"], s["desc"], s["alt"]) for s in slides] == [(s.title, s.desc, s.alt) for s in GALLERY_SLIDES]
    assert [s["src"].split("?")[0] for s in slides] == [f"/static/gallery/{s.image}" for s in GALLERY_SLIDES]


def test_every_image_url_carries_the_static_version():
    """``SEND_FILE_MAX_AGE_DEFAULT`` שומר סטטיקה בדפדפן לזמן ארוך; צילום שהוחלף באותו שם מגיע למבקרים רק דרך ``?v=``."""
    html = _get_gallery().get_data(as_text=True)
    parser = _Meta()
    parser.feed(html)

    urls = [s["src"] for s in _rendered_slides(html)] + parser.img_srcs + [parser.props["og:image"]]
    missing = [u for u in urls if not re.search(r"\?v=[^&\s]+$", u)]
    assert not missing, missing


def test_slides_are_webp_and_the_preview_is_jpeg():
    """הצילומים בעמוד — בסקריפט וב-``<img>`` — הם WebP, ותמונת התצוגה המקדימה (``og:image``) היא ה-JPEG הנפרד."""
    html = _get_gallery().get_data(as_text=True)
    parser = _Meta()
    parser.feed(html)

    slide_urls = [s["src"] for s in _rendered_slides(html)] + parser.img_srcs
    not_webp = [u for u in slide_urls if not u.split("?")[0].endswith(".webp")]
    assert not not_webp, not_webp
    assert parser.props["og:image"].split("?")[0].endswith(".jpg"), parser.props["og:image"]
    assert parser.props["og:image:type"] == "image/jpeg"


def test_share_tags_point_to_absolute_urls_and_the_first_slide():
    from webapp.gallery import GALLERY_SLIDES, share_image

    parser = _Meta()
    parser.feed(_get_gallery().get_data(as_text=True))
    props = parser.props

    for key in ("og:title", "og:description", "og:url", "og:image", "og:type", "og:image:alt"):
        assert props.get(key), key
    # וואטסאפ דורש כתובת מלאה ב-og:image
    assert re.match(r"^https?://[^/]+/gallery$", props["og:url"]), props["og:url"]
    assert re.match(r"^https?://[^/]+/static/gallery/", props["og:image"]), props["og:image"]
    assert props["og:image"].split("?")[0].endswith("/" + share_image(GALLERY_SLIDES[0]))
    assert props["og:image:alt"] == GALLERY_SLIDES[0].alt


def test_share_tags_sit_within_the_first_300kb():
    """וואטסאפ קורא את תגיות התצוגה המקדימה רק מתוך 300KB הראשונים של ה-HTML."""
    body = _get_gallery().get_data()

    offset = body.find(b'property="og:image"')
    assert 0 < offset < 300 * 1024, offset


def test_every_slide_file_exists_and_is_a_resized_webp():
    from webapp.gallery import GALLERY_SLIDES

    max_width = _script_constant("MAX_WIDTH")
    for slide in GALLERY_SLIDES:
        path = GALLERY_DIR / slide.image
        assert path.is_file(), path
        with Image.open(path) as im:
            assert im.format == "WEBP", (slide.image, im.format)
            assert im.width <= max_width, (slide.image, im.width)


def test_share_image_of_the_first_slide_is_a_jpeg_of_the_declared_size():
    """תמונת התצוגה המקדימה: JPEG ב-``SHARE_SIZE`` בדיוק, ולא מעל ``SHARE_MAX_BYTES`` — שניהם מהסקריפט שמייצר אותה."""
    from webapp.gallery import GALLERY_SLIDES, share_image

    path = GALLERY_DIR / share_image(GALLERY_SLIDES[0])
    assert path.is_file(), f"{path} חסר — הריצו את scripts/build_gallery_image.py עם --share על הצילום הראשון"
    assert path.stat().st_size <= _script_constant("SHARE_MAX_BYTES")
    with Image.open(path) as im:
        assert im.format == "JPEG"
        assert im.size == _script_constant("SHARE_SIZE")


def test_every_slide_has_hebrew_alt_text_that_is_not_the_title():
    from webapp.gallery import GALLERY_SLIDES

    for slide in GALLERY_SLIDES:
        assert slide.alt.strip() and slide.alt != slide.title, slide.image
        assert re.search(r"[א-ת]", slide.alt), slide.image


def test_no_stray_files_in_the_gallery_folder():
    """קובץ בתיקייה שאף צילום ברשימה לא מפנה אליו הוא שארית של החלפה — הוא מוגש לכל דורש ושוקל בריפו."""
    from webapp.gallery import GALLERY_SLIDES, share_image

    expected = {s.image for s in GALLERY_SLIDES} | {share_image(GALLERY_SLIDES[0])}
    actual = {p.name for p in GALLERY_DIR.iterdir() if p.is_file()}
    assert actual == expected, {"extra": sorted(actual - expected), "missing": sorted(expected - actual)}

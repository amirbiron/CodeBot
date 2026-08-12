"""בדיקות לאייקוני השפה המצוירים (SVG) של ה-Webapp.

הבדיקה החשובה כאן היא test_every_slug_exists_in_sprite: היא מונעת מצב שבו
מוסיפים שפה לרשימה בקוד אבל שוכחים לצייר לה אייקון בספרייט, ואז המשתמש
מקבל ריבוע ריק במקום אייקון.
"""

import re
import sys
from pathlib import Path

import pytest

from webapp.app import (
    LANG_EMOJI_ICONS,
    LANG_ICON_ALIASES,
    LANG_ICON_FALLBACK_SLUG,
    LANG_ICON_SLUGS,
    get_language_icon,
    get_language_slug,
    lang_icon,
    lang_icon_data,
)

SPRITE_PATH = (
    Path(__file__).resolve().parent.parent
    / "webapp"
    / "templates"
    / "components"
    / "lang_sprite.html"
)


def _sprite_symbols():
    """מחזיר את קבוצת השפות שיש להן <symbol> בספרייט בפועל"""
    content = SPRITE_PATH.read_text(encoding="utf-8")
    return set(re.findall(r'<symbol id="lang-([a-z0-9+#-]+)"', content))


# ---------------------------------------------------------------- שלמות הנתונים

def test_every_slug_exists_in_sprite():
    """לכל שפה ברשימה חייב להיות אייקון מצויר בספרייט"""
    missing = LANG_ICON_SLUGS - _sprite_symbols()
    assert not missing, f"שפות ללא אייקון בספרייט: {sorted(missing)}"


def test_every_sprite_symbol_is_registered():
    """כל אייקון שצויר בספרייט חייב להיות רשום ברשימה, אחרת לא ישתמשו בו"""
    unregistered = _sprite_symbols() - LANG_ICON_SLUGS
    assert not unregistered, f"אייקונים בספרייט שלא נרשמו: {sorted(unregistered)}"


def test_aliases_point_to_real_slugs():
    """כל שם נרדף חייב להצביע על שפה שיש לה אייקון"""
    broken = {k: v for k, v in LANG_ICON_ALIASES.items() if v not in LANG_ICON_SLUGS}
    assert not broken, f"שמות נרדפים שמצביעים לשומקום: {broken}"


def test_sprite_is_in_sync_with_source_icons():
    """הספרייט נגזר מקבצי ה-SVG הבודדים ולא נערך ידנית.

    אם הבדיקה נופלת, מישהו הוסיף או שינה אייקון בלי להריץ את הסקריפט.
    """
    import subprocess

    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "scripts/build_lang_sprite.py", "--check"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "הספרייט אינו מסונכרן עם קבצי המקור. "
        "הריצו: python scripts/build_lang_sprite.py\n" + result.stdout + result.stderr
    )


def test_sprite_is_not_hidden_with_display_none():
    """display:none מונע מהדפדפן לרנדר את הגרדיאנטים והאריחים יוצאים שקופים"""
    content = SPRITE_PATH.read_text(encoding="utf-8")
    svg_tag = re.search(r"<svg\b[^>]*>", content)
    assert svg_tag, "לא נמצא תג svg בספרייט"
    style = svg_tag.group(0).replace(" ", "")
    assert "display:none" not in style, "הספרייט מוסתר בדרך ששוברת את הגרדיאנטים"
    assert "position:absolute" in style


# ---------------------------------------------------------------- get_language_slug

@pytest.mark.parametrize(
    "value,expected",
    [
        ("python", "python"),
        ("Python", "python"),
        ("  YAML  ", "yaml"),
        ("shell", "bash"),
        ("sh", "bash"),
        ("py", "python"),
        ("ts", "typescript"),
        ("dotenv", "env"),
        ("c++", "cpp"),
    ],
)
def test_slug_normalization_and_aliases(value, expected):
    assert get_language_slug(value) == expected


@pytest.mark.parametrize("value", ["cobol", "fortran", "", None, "   "])
def test_slug_empty_when_no_drawn_icon(value):
    """שפה בלי אייקון מצויר מחזירה מחרוזת ריקה, וזה מה שמפעיל את ה-fallback"""
    assert get_language_slug(value) == ""


def _language_without_icon():
    """שפה שיש לה אמוג'י אבל עדיין אין לה אייקון מצויר.

    נבחרת דינמית ולא מקובעת ברשימה, כדי שהבדיקות לא יישברו ברגע
    שיצוירו האייקונים החסרים.
    """
    for name in sorted(LANG_EMOJI_ICONS):
        if not get_language_slug(name):
            return name
    return None


# ---------------------------------------------------------------- lang_icon

def test_known_language_renders_svg():
    html = str(lang_icon("python", 32))
    assert '<use href="#lang-python">' in html
    assert 'width="32"' in html and 'height="32"' in html
    assert 'aria-label="python"' in html


def test_alias_renders_target_icon():
    assert '<use href="#lang-bash">' in str(lang_icon("shell", 24))


def test_language_without_icon_falls_back_to_emoji():
    """שפה שעדיין אין לה אייקון מצויר חייבת לשמור על האמוג'י הישן שלה"""
    lang = _language_without_icon()
    if lang is None:
        pytest.skip("לכל השפות כבר יש אייקון מצויר")
    html = str(lang_icon(lang, 24))
    assert "<svg" not in html
    assert get_language_icon(lang) in html
    assert "font-size:24px" in html


@pytest.mark.parametrize("unknown", ["cobol", "fortran", "", None, "   "])
def test_unknown_language_falls_back_to_text_icon(unknown):
    """שפה לא מזוהה מקבלת את אייקון ה-text, כדי שלא תתקבל תערובת עם אמוג'י"""
    html = str(lang_icon(unknown, 24))
    assert f'<use href="#lang-{LANG_ICON_FALLBACK_SLUG}">' in html


def test_fallback_slug_has_an_icon():
    """אם ל-fallback עצמו אין אייקון, כל קובץ לא מזוהה יחזור לאמוג'י"""
    assert LANG_ICON_FALLBACK_SLUG in LANG_ICON_SLUGS


@pytest.mark.parametrize("bad_size", ["abc", None, "", [], {}])
def test_invalid_size_falls_back_to_default(bad_size):
    assert 'width="32"' in str(lang_icon("go", bad_size))


@pytest.mark.parametrize("size,expected", [(4, 8), (9999, 256), (32, 32)])
def test_size_is_clamped(size, expected):
    assert f'width="{expected}"' in str(lang_icon("go", size))


def test_css_class_is_escaped():
    """שם מחלקה לא אמור לאפשר שבירה של ה-HTML"""
    html = str(lang_icon("go", 24, '"><script>alert(1)</script>'))
    assert "<script>" not in html


# ---------------------------------------------------------------- lang_icon_data

def test_data_for_client_matches_server():
    """הנתונים שנשלחים ל-JS חייבים להיות אותם נתונים שהשרת עובד לפיהם"""
    data = lang_icon_data()
    assert set(data["slugs"]) == LANG_ICON_SLUGS
    assert data["aliases"] == LANG_ICON_ALIASES
    assert data["emoji"] == LANG_EMOJI_ICONS
    assert data["fallback"] == LANG_ICON_FALLBACK_SLUG


def test_emoji_map_covers_the_default_fallback():
    """text הוא ה-fallback של כל קובץ לא מזוהה — הוא חייב להישאר במפה"""
    assert "text" in LANG_EMOJI_ICONS


# ---------------------------------------------------------------- שקילות שרת/לקוח

BASE_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "webapp" / "templates" / "base.html"
)

# הקלטים שנבדקים בשני הצדדים. כוללים מקרי קצה של גודל, כי דווקא שם
# התגלה בעבר פער בין השרת ללקוח (0 נתן 8 בשרת ו-32 בדפדפן).
EQUIVALENCE_CASES = [
    ("python", 32), ("Python", 24), ("  YAML  ", 24), ("shell", 24),
    ("scss", 32), ("cobol", 32), ("", 32), (None, 32), ("text", 36),
    ("go", 0), ("go", 4), ("go", 8), ("go", 257), ("go", 9999),
    ("go", "abc"), ("go", ""), ("go", None), ("go", 32.7),
]


def _extract_client_functions() -> str:
    """שולף את window.langSlug ו-window.langIcon מתוך base.html"""
    content = BASE_TEMPLATE.read_text(encoding="utf-8")
    start = content.index("window.langSlug = function(language)")
    end = content.index("// נשמר לתאימות עם קוד קיים", start)
    return content[start:end]


def test_client_and_server_produce_identical_html():
    """window.langIcon חייבת להחזיר בדיוק את מה ש-lang_icon מחזירה.

    שתיהן נשענות על אותם נתונים, ולכן כל פער ביניהן הוא באג שמתבטא
    בהבדל בין מה שמגיע מהשרת לבין מה שנבנה בדפדפן.
    """
    import json
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        pytest.skip("node אינו זמין בסביבה")

    script = f"""
    global.window = global;
    window.LANG_ICON_DATA = {json.dumps(lang_icon_data(), ensure_ascii=False)};
    {_extract_client_functions()}
    const cases = {json.dumps(EQUIVALENCE_CASES, ensure_ascii=False)};
    console.log(JSON.stringify(cases.map(c => window.langIcon(c[0], c[1]))));
    """

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(script)
        script_path = f.name
    try:
        result = subprocess.run(
            [node, script_path], capture_output=True, text=True, timeout=60
        )
    finally:
        Path(script_path).unlink(missing_ok=True)

    assert result.returncode == 0, f"הרצת ה-JS נכשלה: {result.stderr}"
    client_output = json.loads(result.stdout)

    mismatches = []
    for (language, size), from_client in zip(EQUIVALENCE_CASES, client_output):
        from_server = str(lang_icon(language, size))
        if from_server != from_client:
            mismatches.append(
                f"  lang={language!r} size={size!r}\n"
                f"    שרת:  {from_server}\n"
                f"    לקוח: {from_client}"
            )

    assert not mismatches, "פער בין השרת ללקוח:\n" + "\n".join(mismatches)

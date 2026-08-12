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


def _languages_with_emoji_but_no_icon():
    """שפות שיש להן אמוג'י ייחודי אבל אין להן אייקון מצויר.

    נבחרות דינמית ולא מקובעות ברשימה, כדי שהבדיקות לא יישברו כשיצוירו
    אייקונים נוספים. binary נמצא כאן כי הוא לא שפה אלא מצב תצוגה.
    """
    return [name for name in sorted(LANG_EMOJI_ICONS) if not get_language_slug(name)]


# ---------------------------------------------------------------- lang_icon

def test_known_language_renders_svg():
    html = str(lang_icon("python", 32))
    assert '<use href="#lang-python">' in html
    assert 'width="32"' in html and 'height="32"' in html


def test_alias_renders_target_icon():
    assert '<use href="#lang-bash">' in str(lang_icon("shell", 24))


def test_language_with_own_emoji_keeps_it():
    """שפה שאין לה אייקון אבל יש לה סמל ייחודי שומרת עליו ולא נופלת ל-text.

    המקרה שבגללו זה קיים: קובץ בינארי מוצג עם 🔒, וללא הכלל הזה הוא
    היה מקבל אייקון מסמך רגיל ומאבד את המידע שהתוכן לא ניתן להצגה.
    """
    languages = _languages_with_emoji_but_no_icon()
    if not languages:
        pytest.skip("לכל השפות שבמפה יש כבר אייקון מצויר")
    for lang in languages:
        html = str(lang_icon(lang, 24))
        assert "<svg" not in html, f"{lang} אמור להישאר אמוג'י"
        assert LANG_EMOJI_ICONS[lang] in html
        assert "font-size:24px" in html


def test_binary_file_keeps_its_lock_symbol():
    """רגרסיה: קובץ בינארי מוצג עם 🔒 ולא עם אייקון מסמך גנרי"""
    html = str(lang_icon("binary", 36))
    assert "🔒" in html
    assert "<svg" not in html


@pytest.mark.parametrize("unknown", ["cobol", "fortran", "", None, "   "])
def test_unknown_language_falls_back_to_text_icon(unknown):
    """שפה לא מזוהה מקבלת את אייקון ה-text, כדי שלא תתקבל תערובת עם אמוג'י"""
    html = str(lang_icon(unknown, 24))
    assert f'<use href="#lang-{LANG_ICON_FALLBACK_SLUG}">' in html


# ---------------------------------------------------------------- נגישות

def test_icon_is_hidden_from_screen_readers_by_default():
    """בכל מקום שהאייקון מוצג בו מופיע לצדו שם הקובץ או תגית השפה,
    ולכן הקראה שלו רק מכפילה את המידע"""
    html = str(lang_icon("python", 32))
    assert 'aria-hidden="true"' in html
    assert "aria-label" not in html


def test_icon_can_be_labelled_when_it_is_the_only_signal():
    html = str(lang_icon("python", 32, decorative=False))
    assert 'aria-label="python"' in html
    assert 'role="img"' in html
    assert "aria-hidden" not in html


def test_emoji_variant_is_always_hidden():
    """לאמוג'י אין תווית טובה לקורא מסך — 🔒 יוקרא כ-lock"""
    assert 'aria-hidden="true"' in str(lang_icon("binary", 24))


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

# הקלטים שנבדקים בשני הצדדים, כ-(שפה, גודל, decorative).
# מקרי הקצה של הגודל נמצאים כאן כי דווקא שם התגלה פער אמיתי
# (0 נתן 8 בשרת ו-32 בדפדפן), ו-binary נמצא כי הוא היחיד שנשען על
# הענף ששומר אמוג'י ייחודי.
EQUIVALENCE_CASES = [
    ("python", 32, True), ("python", 32, False),
    ("Python", 24, True), ("  YAML  ", 24, True), ("shell", 24, True),
    ("scss", 32, True), ("cobol", 32, True), ("", 32, True),
    (None, 32, True), ("text", 36, True),
    ("binary", 36, True), ("binary", 24, False),
    ("go", 0, True), ("go", 4, True), ("go", 8, True),
    ("go", 257, True), ("go", 9999, True),
    ("go", "abc", True), ("go", "", True), ("go", None, True), ("go", 32.7, True),
    ("go", "24", True), ("go", "24px", True), ("go", " 40 ", True), ("go", -5, True),
]

# מסמנים את גבולות הבלוק בתוך base.html כדי שהחילוץ לא יישבר
# מעריכה של הערה או של שם פונקציה בקרבת מקום
CLIENT_BLOCK_START = "/* lang-icon:client-block:start */"
CLIENT_BLOCK_END = "/* lang-icon:client-block:end */"


def _extract_client_functions() -> str:
    """שולף את קוד אייקוני השפה של צד הלקוח מתוך base.html"""
    content = BASE_TEMPLATE.read_text(encoding="utf-8")
    assert CLIENT_BLOCK_START in content and CLIENT_BLOCK_END in content, (
        "סמני הבלוק נעלמו מ-base.html — בלעדיהם אי אפשר לבדוק שקילות שרת/לקוח"
    )
    start = content.index(CLIENT_BLOCK_START) + len(CLIENT_BLOCK_START)
    return content[start:content.index(CLIENT_BLOCK_END, start)]


def test_client_and_server_produce_identical_html():
    """window.langIcon חייבת להחזיר בדיוק את מה ש-lang_icon מחזירה.

    שתיהן נשענות על אותם נתונים, ולכן כל פער ביניהן הוא באג שמתבטא
    בהבדל בין מה שמגיע מהשרת לבין מה שנבנה בדפדפן.
    """
    import json
    import os
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if not node:
        # מקומית מותר לדלג, אבל ב-CI היעדר node אומר שרשת הביטחון הזו
        # לא רצה בכלל — ודילוג שקט שם מסוכן יותר מכישלון רועש
        if os.environ.get("CI"):
            pytest.fail(
                "node אינו זמין ב-CI ולכן בדיקת השקילות בין השרת ללקוח לא רצה. "
                "הוסיפו actions/setup-node ל-workflow."
            )
        pytest.skip("node אינו זמין בסביבה המקומית")

    script = f"""
    global.window = global;
    window.LANG_ICON_DATA = {json.dumps(lang_icon_data(), ensure_ascii=False)};
    {_extract_client_functions()}
    const cases = {json.dumps(EQUIVALENCE_CASES, ensure_ascii=False)};
    console.log(JSON.stringify(cases.map(c => window.langIcon(c[0], c[1], c[2]))));
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
    for (language, size, decorative), from_client in zip(EQUIVALENCE_CASES, client_output):
        from_server = str(lang_icon(language, size, decorative=decorative))
        if from_server != from_client:
            mismatches.append(
                f"  lang={language!r} size={size!r} decorative={decorative!r}\n"
                f"    שרת:  {from_server}\n"
                f"    לקוח: {from_client}"
            )

    assert not mismatches, "פער בין השרת ללקוח:\n" + "\n".join(mismatches)

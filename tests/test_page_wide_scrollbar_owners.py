"""מי מעצב את פס הגלילה של כל העמוד — שלושה בעלים, ואף קובץ של עמוד או רכיב.

**הבאג שהקובץ הזה שומר עליו.** ב-``repo-browser.css`` היה ``::-webkit-scrollbar`` בלי שום בורר לפניו, בצבעים
קבועים (``--scrollbar-thumb`` / ``--scrollbar-track`` שהוגדרו ב-``:root`` שלו) ובעובי משלו. כלל כזה חל על **כל**
רכיב נגלל בעמוד שטוען את הקובץ: הסייר, הקוד, פתקים ומודאלים מהנבבר. הוא דרס את הכללים הגלובליים, ולכן בכל
ערכה שאין לה כלל פס גלילה ב-``dark-mode.css`` או ב-``high-contrast.css`` — ערכות בהירות, וכל ערכה מיובאת —
דפדפן הריפו הציג פסים כהים, ובכל הערכות העובי שלהם לא תאם לשאר האתר. ובערכה מיובאת שאינה מצהירה על
``--text-muted``, ה-hover שלו (``var(--text-muted)``) קרא את הפלטה שב-``:root`` של ``repo-browser.css``. הדוגמה
הועתקה מ-``GUIDES/REPO_SYNC_ENGINE_UI_GUIDE.md``, שהמליץ עליה.

**הבעלים.** הכללים הגלובליים יושבים בבלוק ה-``<style>`` של ``base.html`` (עובי מ-``--scrollbar-width``, וצבעים),
והדריסות לפי ערכה ב-``dark-mode.css`` וב-``high-contrast.css``. כל עמוד יורש אותם, וכך עמוד הקבצים נראה כמו
שהוא נראה. רכיב שצריך פס אחר כותב כלל עם הבורר שלו (כמו ``.result-card-snippet ::-webkit-scrollbar`` ב-
``global_search.css``), ולא כלל לכל העמוד.

**ולמה גם height.** ``width`` של ``::-webkit-scrollbar`` הוא העובי של הפס האנכי, ו-``height`` של האופקי.
בלי ``height`` הפס האופקי מקבל את העובי של הדפדפן ולא את ``--scrollbar-width``, ובדפדפן הריפו — שבו הקוד נגלל
לרוחב — זה בולט.

הבדיקה כאן טקסטואלית, ושומרת על ההחלטה. ההתנהגות עצמה נמדדה בכרומיום 153 מול הוובאפ האמיתי (נובמבר 2026):
עובי בשני הצירים וצבעי המסילה והידית, בעמוד הקבצים ובדפדפן הריפו, בערכות המובנות ובערכות מיובאות — אישית
בהירה, אישית כהה (מלאה, ודלילה בלי ``--text-muted``) וציבורית כהה. הפירוט בתיאור ה-PR שהוסיף את הקובץ.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEBAPP = ROOT / "webapp"
BASE_TEMPLATE = WEBAPP / "templates" / "base.html"

#: הקבצים שמותר להם לעצב את פס הגלילה של כל העמוד. ``base.html`` — הכללים הגלובליים; שני קובצי הערכות — הדריסות
#: לפי ``data-theme``.
OWNERS = {
    BASE_TEMPLATE,
    WEBAPP / "static" / "css" / "dark-mode.css",
    WEBAPP / "static" / "css" / "high-contrast.css",
}

#: בורר שחל על כל פס גלילה בעמוד: לפני ה-pseudo-element יש רק ``*``, ``html``, ``body``, ``:root`` או בורר תכונה
#: (``[data-theme="..."]``) — כלומר שום דבר שמצמצם אותו לרכיב אחד.
PAGE_WIDE = re.compile(r"^(?:[*\s]|html|body|:root|\[[^\]]*\])*::-webkit-scrollbar")


def _without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _style_blocks(html: str) -> list[str]:
    return re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S | re.I)


def _selectors(css: str):
    for match in re.finditer(r"([^{}]+)\{", _without_comments(css)):
        for selector in match.group(1).split(","):
            yield selector.strip()


def _page_wide_selectors(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    sources = [text] if path.suffix == ".css" else _style_blocks(text)
    return [s for css in sources for s in _selectors(css) if PAGE_WIDE.match(s)]


def test_only_the_owners_style_every_scrollbar_on_the_page():
    offenders = []
    for path in sorted([*WEBAPP.rglob("*.css"), *WEBAPP.rglob("*.html")]):
        if path in OWNERS:
            continue
        offenders += [f"{path.relative_to(ROOT)}: {s}" for s in _page_wide_selectors(path)]
    assert not offenders, (
        "כלל ::-webkit-scrollbar שחל על כל העמוד, מחוץ ל-base.html ולקובצי הערכות. הוא דורס את הכללים הגלובליים "
        "בכל רכיב נגלל בעמוד — כולל פתקים ומודאלים מהנבבר. כתבו אותו עם הבורר של הרכיב:\n" + "\n".join(offenders)
    )


def test_the_owners_still_hold_page_wide_rules():
    """בקרה לבדיקה שלמעלה: אם הבורר שלה היה מפסיק לזהות כלל לכל העמוד, היא הייתה עוברת תמיד."""
    for path in OWNERS:
        assert _page_wide_selectors(path), f"לא זוהה כלל פס גלילה לכל העמוד ב-{path.relative_to(ROOT)}"


def test_the_global_rule_sets_both_axes_from_the_scrollbar_token():
    rules = [
        body
        for css in _style_blocks(BASE_TEMPLATE.read_text(encoding="utf-8"))
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", _without_comments(css))
        if [s.strip() for s in selector.split(",")] == ["::-webkit-scrollbar"]
    ]
    assert len(rules) == 1, f"צריך כלל גלובלי אחד ל-::-webkit-scrollbar ב-base.html, נמצאו {len(rules)}"
    declared = dict(
        (name.strip(), value.strip()) for name, value in re.findall(r"([\w-]+)\s*:\s*([^;]+);", rules[0])
    )
    assert declared.get("width") == "var(--scrollbar-width)", declared
    assert declared.get("height") == "var(--scrollbar-width)", declared

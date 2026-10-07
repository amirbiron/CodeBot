"""הטוקנים שתצוגת ה-Markdown קוראת, בכל עמוד שטוען את ``markdown-preview.css``.

הקובץ נטען בדפדפן הקוד ובעמוד הקבצים (כרטיסי החיפוש בתיעוד). שניהם יורשים מ-``base.html``, אבל רק דפדפן
הקוד טוען את ``repo-browser.css``, ו-``--border-color`` ו-``--accent-blue`` מוגדרים רק בפלטה שב-``:root``
שלו. בלי מקור בעמוד הקבצים, הקישורים בכרטיסי התיעוד קיבלו את צבע הטקסט והגבולות את ``currentColor`` —
נמדד בדפדפן מול דפדפן הקוד. לכן הקובץ המשותף מגדיר טוקנים משלו, ``--md-preview-border`` ו-
``--md-preview-accent``, שקוראים את השניים עם fallback של אותה פלטה.

הטסטים כאן שומרים על שני הקצוות: ה-fallback שווה לערך בפלטה, וכל טוקן שכלל משותף קורא מוגדר בכל עמוד
שטוען את הקובץ — כלל שקורא טוקן של עמוד אחד בלבד נראה תקין רק שם.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "webapp" / "static" / "css"
BASE_TEMPLATE = ROOT / "webapp" / "templates" / "base.html"
TOKENS = {"--md-preview-border": "--border-color", "--md-preview-accent": "--accent-blue"}


def _root_block(css: str) -> str:
    match = re.search(r"^:root\s*\{(?P<body>.*?)^\}", css, re.S | re.M)
    assert match, "לא נמצא בלוק :root"
    return match.group("body")


def _without_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _declares(text: str, token: str) -> bool:
    return re.search(re.escape(token) + r"\s*:", text) is not None


def test_the_fallbacks_are_the_repo_browser_palette():
    palette = _root_block((CSS / "repo-browser.css").read_text(encoding="utf-8"))
    shared = (CSS / "markdown-preview.css").read_text(encoding="utf-8")
    for token, source in TOKENS.items():
        defined = re.findall(rf"{token}:\s*var\({source},\s*([^)]+)\);", shared)
        assert len(defined) == 1, f"{token} צריך הגדרה אחת שקוראת את {source}: {defined}"
        value = re.search(rf"{source}:\s*([^;]+);", palette)
        assert value, f"{source} אינו מוגדר ב-:root של repo-browser.css"
        assert defined[0].strip().lower() == value.group(1).strip().lower(), (token, defined[0], value.group(1))


def test_every_token_a_shared_rule_reads_is_defined_on_every_page_that_loads_it():
    """מוגדר ב-``base.html``, שכל העמודים יורשים, או בקובץ המשותף עצמו.

    החריגים: ההגדרות של טוקני הרכיב, שקוראות את הפלטה של דפדפן הקוד בכוונה, ווו דריסה (``--*-override``),
    שאין לו ערך בשום מקום בכוונה — ולכן הוא חייב להיקרא עם fallback, אחרת הכלל כולו בטל כשאין הצהרה.
    """
    shared = _without_comments((CSS / "markdown-preview.css").read_text(encoding="utf-8"))
    rules = re.sub(rf"^\s*(?:{'|'.join(TOKENS)}):[^;]*;$", "", shared, flags=re.M)
    base = BASE_TEMPLATE.read_text(encoding="utf-8")
    problems = set()
    for token, closer in re.findall(r"var\(\s*(--[\w-]+)\s*([,)])", rules):
        if token.endswith("-override"):
            if closer != ",":
                problems.add(f"{token} (וו דריסה בלי fallback)")
        elif not (_declares(shared, token) or _declares(base, token)):
            problems.add(token)
    assert not problems, (
        f"כלל משותף קורא טוקן שלא מוגדר בכל עמוד שטוען את הקובץ: {sorted(problems)} — "
        f"להגדיר טוקן של הרכיב, כמו {sorted(TOKENS)}"
    )

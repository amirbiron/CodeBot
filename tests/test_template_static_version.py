"""כל נכס סטטי מקומי בתבנית נושא מזהה גרסה.

**למה זה טסט ולא משמעת.** ``SEND_FILE_MAX_AGE_DEFAULT`` בוובאפ הוא שנה,
והנכסים מוגשים בשמות קבועים. המוסכמה בפרויקט היא ``?v={{ static_version }}``,
אבל היא חיה בכל תבנית בנפרד — ותגית אחת שנשכחה מגישה קוד ישן **עד שנה**
למי שכבר ביקר בדף. הכשל הזה אינו מייצר בקשה, אינו מייצר לוג ואי אפשר
לראות אותו בשום כלי צד-שרת; הסימפטום היחיד הוא "הקוד החדש לא עובד אצל
חלק מהאנשים", ואצל המפתח — שמרענן בכוח — הכול עובד.

זה גם מה שהמדיניות הכתובה של הפרויקט אומרת: ``docs/webapp/static-checklist.rst``
מתיר ``max-age`` ארוך רק לשם עם fingerprint, ובלעדיו דורש ``no-cache``.

**על ה-allowlist.** התגיות ברשימה למטה היו כאלה עוד לפני הטסט הזה. הן
**חוב מתועד, לא אישור** — הרשימה כאן כדי שהמחלקה לא תוכל לגדול, ולא
כדי להכשיר את מה שכבר בה. כל תגית חדשה בלי מזהה גרסה מפילה את הטסט.
מי שמתקן אחת מהן — מוחק אותה מכאן, וזו הדרך שהרשימה מתקצרת.
"""

import pathlib
import re

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "webapp" / "templates"

_TAG = re.compile(
    r"""<(?:script|link)\b[^>]*?(?:src|href)\s*=\s*"\s*\{\{\s*url_for\(\s*['"]static['"].*?\}\}([^"]*)"[^>]*>""",
    re.S | re.I,
)
_FILENAME = re.compile(r"""filename\s*=\s*['"]([^'"]+)['"]""")

#: ‏(תבנית יחסית, שם הנכס) — תגיות שנוצרו לפני הטסט הזה.
KNOWN_MISSING = {
    ("admin_rules.html", "css/rule-builder.css"),
    ("admin_rules.html", "js/rule-builder.js"),
    # אייקון ולא קוד, אבל אותה מחלקת התיישנות בדיוק.
    ("base.html", "icons/apple-touch-icon-180.png"),
    ("bookmarks_snippet.html", "css/bookmarks.css"),
    ("bookmarks_snippet.html", "js/bookmarks.js"),
    ("collections.html", "css/card-preview.css"),
    ("collections.html", "js/card-preview.js"),
    ("files.html", "css/multi-select.css"),
    ("files.html", "css/card-preview.css"),
    ("files.html", "js/multi-select.js"),
    ("files.html", "js/bulk-actions.js"),
    ("files.html", "js/card-preview.js"),
    ("reader_mode.html", "css/reader.css"),
    ("repo/base_repo.html", "js/repo-history.js"),
    ("repo/base_repo.html", "js/utils/safe-highlight.js"),
    ("repo/base_repo.html", "js/md-anchors.js"),
    ("repo/base_repo.html", "js/md-mark-plugin.js"),
    ("repo/base_repo.html", "js/live-preview.js"),
}


def _unversioned():
    found = set()
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(TEMPLATES).as_posix()
        for match in _TAG.finditer(text):
            if "v=" in match.group(1):
                continue
            name = _FILENAME.search(match.group(0))
            found.add((rel, name.group(1) if name else match.group(0)[:80]))
    return found


def test_no_new_static_tag_is_served_without_a_version_id():
    new = _unversioned() - KNOWN_MISSING
    assert not new, (
        "תגיות סטטיות בלי ?v={{ static_version }} — מול max-age של שנה הן "
        "מגישות קוד ישן עד שנה:\n" + "\n".join(sorted(f"  {t} → {a}" for t, a in new))
    )


def test_the_allowlist_has_no_stale_entries():
    """רשומה שכבר תוקנה חייבת לרדת מהרשימה, אחרת היא מסתירה נסיגה."""
    stale = KNOWN_MISSING - _unversioned()
    assert not stale, (
        "רשומות ב-allowlist שכבר אינן חריגות — יש למחוק אותן:\n"
        + "\n".join(sorted(f"  {t} → {a}" for t, a in stale))
    )


def test_the_compare_and_markdown_pages_are_versioned():
    """הקבצים שה-PR הזה נוגע בהם — בדיקה ישירה ולא דרך ההפרש.

    בלעדיה, מי שיוסיף אותם ל-allowlist יעבור את הטסט למעלה.
    """
    offenders = {t for t, _ in _unversioned()}
    for template in ("compare.html", "compare_files.html", "compare_paste.html",
                     "md_preview.html", "view_file.html"):
        assert template not in offenders, f"{template} מגיש נכס בלי מזהה גרסה"

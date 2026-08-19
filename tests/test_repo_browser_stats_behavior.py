"""מריץ את קוד המונים האמיתי ובודק מה הוא מייצר בפועל.

``test_repo_browser_stats_sync.py`` בודק את *צורת* הקוד — שהקריאה קיימת,
שכל מונה מסומן ממופה. הוא לא יכול לתפוס רגרסיה ששומרת על הצורה ושוברת
את התוצאה: סלקטור שגוי, מקור ערך שגוי, או מיפוי מנותק.

כאן מריצים את ``renderRepoStats`` ו-``getRepoTotalFiles`` **עצמן**, כפי
שהן כתובות בקובץ, מול DOM מינימלי. שתי הפונקציות נוגעות רק ב-
``querySelectorAll``, ב-``dataset`` וב-``textContent``, ולכן כפיל קטן
מספיק — ואין צורך ב-Playwright או ב-jsdom, ששניהם לא מותקנים ולא רצים
ב-CI ולכן לא היו מגנים על כלום.

**מה עדיין לא מכוסה:** הפריסה בפועל בדפדפן — CSS, סדר טעינה, והאם
המשתמש רואה את הערך. לזה נדרש דפדפן אמיתי.
"""

import json
import shutil
import subprocess
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "webapp" / "static" / "js" / "repo-browser.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node לא זמין להרצת קוד הצד-לקוח"
)


def _extract_function(source, name):
    """חילוץ הפונקציה מהקובץ האמיתי, לפי איזון סוגריים."""
    match = re.search(r'function\s+%s\s*\([^)]*\)\s*\{' % re.escape(name), source)
    assert match, f"הפונקציה {name} לא נמצאה"
    depth = 1
    for i in range(match.end(), len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():i + 1]
    raise AssertionError(f"סוגריים לא מאוזנים ב-{name}")


def _run(repo_metadata, current_repo, marked_stats, initial_text="1529"):
    """מריץ את הפונקציות האמיתיות ומחזיר את הטקסט של כל אלמנט מסומן.

    ``marked_stats`` היא רשימת הערכים של ``data-repo-stat`` שיהיו ב-DOM.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    functions = "\n".join(
        _extract_function(source, name)
        for name in ("getRepoTotalFiles", "renderRepoStats")
    )

    harness = """
const repoMetadataByName = %(meta)s;

const elements = %(stats)s.map(stat => ({
    dataset: { repoStat: stat },
    textContent: %(initial)s,
}));

const document = {
    querySelectorAll(selector) {
        if (selector !== '[data-repo-stat]') {
            throw new Error('סלקטור לא צפוי: ' + selector);
        }
        return elements;
    },
};

%(functions)s

renderRepoStats(%(current)s);
console.log(JSON.stringify(elements.map(el => el.textContent)));
""" % {
        "meta": json.dumps(repo_metadata),
        "stats": json.dumps(marked_stats),
        "initial": json.dumps(initial_text),
        "current": json.dumps(current_repo),
        "functions": functions,
    }

    result = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, f"הרצת ה-JS נכשלה:\n{result.stderr}"
    return json.loads(result.stdout.strip())


def test_switching_repo_shows_the_new_repos_count():
    """הבאג המקורי: הערך שמוצג הוא של הריפו שנבחר, לא של הקודם."""
    meta = {"CodeBot": {"total_files": 1529}, "OtherRepo": {"total_files": 42}}

    assert _run(meta, "OtherRepo", ["total_files"]) == ["42"]
    assert _run(meta, "CodeBot", ["total_files"]) == ["1529"]


def test_every_marked_element_is_updated_not_just_the_first():
    """המונה מופיע בכותרת וגם בתחתית הסיידבר — שניהם חייבים להתעדכן."""
    meta = {"OtherRepo": {"total_files": 42}}

    assert _run(meta, "OtherRepo", ["total_files", "total_files"]) == ["42", "42"]


def test_zero_files_is_shown_as_zero_not_as_missing():
    """ריפו ריק באמת — ``0`` הוא ערך תקין ולא ״חסר נתון״."""
    meta = {"Empty": {"total_files": 0}}

    assert _run(meta, "Empty", ["total_files"]) == ["0"]


@pytest.mark.parametrize(
    "raw", [None, False, "", "abc", [], {}], ids=["null", "false", "empty", "text", "list", "dict"]
)
def test_non_numeric_count_is_shown_as_dash_not_as_zero(raw):
    """ערך לא מספרי מוצג כ-``—``.

    ``Number(null)``, ``Number(false)`` ו-``Number('')`` כולם ``0``
    ו-``Number.isFinite`` מאשר אותם, ולכן ריפו שסונכרן חלקית היה מציג
    ״0 files״ — מספר שנראה אמיתי ואינו.
    """
    meta = {"Partial": {"total_files": raw}}

    assert _run(meta, "Partial", ["total_files"]) == ["—"]


def test_unmapped_stat_is_shown_as_dash():
    """מונה שסומן בתבנית בלי מיפוי מוצג כ-``—`` ולא כערך של מונה אחר."""
    meta = {"OtherRepo": {"total_files": 42}}

    assert _run(meta, "OtherRepo", ["total_branches"]) == ["—"]


def test_unknown_repo_keeps_the_server_rendered_value():
    """בלי מטא-דאטה לריפו — הערך שהשרת רינדר נשאר על מכונו."""
    meta = {"CodeBot": {"total_files": 1529}}

    assert _run(meta, "NotSynced", ["total_files"], initial_text="1529") == ["1529"]

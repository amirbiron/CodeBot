"""נועל את סנכרון מוני הריפו בדפדפן הקוד.

הבאג שהבדיקות כאן מונעות: המונים רונדרו בשרת פעם אחת בזמן טעינת הדף,
ו-``updateRepoDisplay`` — הפונקציה שמרעננת את ה-UI בהחלפת ריפו — עדכנה
את שם הריפו ואת ה-dropdown אבל לא נגעה בהם. התוצאה הייתה מונה תקוע על
הערכים של הריפו הראשון בכל ריפו שעברו אליו.

זה דפוס U5 (``linked-field-atomicity``): פעולה לוגית אחת דורשת עדכון של
קבוצת שדות מקושרים, והקוד מעדכן חלק מהם ושוכח את השאר.

**מה הבדיקות כאן לא מוכיחות:** הן סטטיות וקוראות את התבנית ואת ה-JS
כטקסט. הן מוודאות שכל מונה מסומן מטופל בקוד, אבל לא מריצות דפדפן ולכן
לא מוכיחות שהעדכון אכן מצויר על המסך. אימות כזה דורש Playwright.
"""

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "webapp" / "templates" / "repo" / "base_repo.html"
SCRIPT = ROOT / "webapp" / "static" / "js" / "repo-browser.js"

# הסימון שמחבר בין אלמנט בתבנית לבין הערך שממלא אותו בצד הלקוח
STAT_ATTR_RE = re.compile(r'data-repo-stat=["\']([^"\']+)["\']')


@pytest.fixture(scope="module")
def template_source():
    return TEMPLATE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def script_source():
    return SCRIPT.read_text(encoding="utf-8")


def _js_function_body(source, name):
    """גוף הפונקציה ``name``, לפי איזון סוגריים מסולסלים.

    עדיף על regex פשוט: ``renderRepoStats`` מכילה אובייקט ו-callback,
    וחיפוש ``}`` ראשון היה חותך אותה באמצע.
    """
    match = re.search(r'function\s+%s\s*\([^)]*\)\s*\{' % re.escape(name), source)
    assert match, f"הפונקציה {name} לא נמצאה ב-{SCRIPT.name}"
    start = match.end()
    depth = 1
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i]
    raise AssertionError(f"סוגריים לא מאוזנים בגוף {name}")


def test_template_declares_at_least_one_stat(template_source):
    """אם הסימון נעלם מהתבנית, שאר הבדיקות כאן היו עוברות על ריק."""
    assert STAT_ATTR_RE.findall(template_source), (
        "אין אף data-repo-stat בתבנית — הבדיקות הבאות מאבדות משמעות"
    )


def test_every_marked_stat_is_filled_by_the_renderer(template_source, script_source):
    """כל מונה שמסומן בתבנית חייב לקבל ערך מ-``renderRepoStats``.

    הסימונים נגזרים מה-HTML שנוצר ולא מרשימה קשיחה בבדיקה, כך שמונה
    חדש שיתווסף לתבנית ולא יטופל בקוד — ייפול כאן.
    """
    body = _js_function_body(script_source, "renderRepoStats")

    for stat in sorted(set(STAT_ATTR_RE.findall(template_source))):
        assert stat in body, (
            f"המונה '{stat}' מסומן בתבנית אבל renderRepoStats לא ממלאת אותו"
        )


def test_repo_switch_refreshes_the_stats(script_source):
    """``updateRepoDisplay`` היא נקודת העדכון בהחלפת ריפו — ועליה לרענן גם מונים.

    זו הבדיקה שנופלת על הקוד שלפני התיקון: שם הפונקציה עדכנה שם ריפו
    ו-dropdown בלבד.
    """
    body = _js_function_body(script_source, "updateRepoDisplay")
    assert "renderRepoStats" in body, (
        "updateRepoDisplay לא מרעננת את המונים — הם יישארו של הריפו הקודם"
    )


def test_stats_come_from_already_loaded_metadata(script_source):
    """הערכים נלקחים מהזיכרון ולא בקריאת רשת חדשה.

    זה מה שמונע את דפוס U2§5 (עדכון אחרי ``await`` בלי בדיקת ביטול):
    כל עוד המסלול סינכרוני, החלפה מהירה פעמיים לא יכולה לגרום לתשובה
    ישנה לדרוס חדשה. בדיקה זו נופלת אם מישהו יהפוך את המסלול לאסינכרוני
    בלי להוסיף הגנה.
    """
    body = _js_function_body(script_source, "renderRepoStats")
    assert "await" not in body, (
        "renderRepoStats הפכה לאסינכרונית — נדרשת הגנה מפני תגובה מאוחרת"
    )

    helper = _js_function_body(script_source, "getRepoTotalFiles")
    assert "repoMetadataByName" in helper, (
        "מקור הנתונים השתנה; ודא שאין קריאת רשת בתוך מסלול העדכון"
    )
    assert "fetch" not in helper


def test_missing_metadata_does_not_wipe_the_server_rendered_value(script_source):
    """בלי מטא-דאטה לריפו — לא נוגעים במונה שהשרת כבר רינדר.

    בלי היציאה המוקדמת הזו, כשל רגעי של ``/api/repos`` היה מוחק ערך
    תקין ומציג ``—`` במקומו. מטא-דאטה שקיים אבל חסר בו השדה כן נמחק,
    כי אז הערך שמוצג שייך לריפו אחר — וזה הבאג המקורי.
    """
    body = _js_function_body(script_source, "renderRepoStats")
    guard = body.split("querySelectorAll")[0]
    assert "repoMetadataByName" in guard and "return" in guard, (
        "renderRepoStats מעדכנת בלי לוודא שיש מטא-דאטה — היא תמחק ערך תקין"
    )


def test_per_language_counters_are_gone(template_source):
    """המונים לפי שפה הוסרו לבקשת המשתמש — הם הוצגו בלי תווית ובלבלו.

    נעילה גם על ההסרה של האגרגציה בשרת: אם הם יחזרו לתבנית, מישהו
    יצטרך להחזיר גם את החישוב, ובלעדיו הם יציגו אפס תמיד.
    """
    assert "file_types" not in template_source, (
        "מוני השפות חזרו לתבנית; ראה את הסרת האגרגציה ב-repo_browser.py"
    )

"""ההגדרה "הצגת כפתור סימניות" — עמוד ההגדרות כותב, ``bookmarks.js`` קורא, באותו מפתח.

המפתח ב-localStorage כתוב פעמיים: ``BM_KEY`` בסקריפט של ``settings.html``, ו-
``TOGGLE_VISIBILITY_KEY`` ב-``BookmarkUI`` (``webapp/static/js/bookmarks.js``). עמוד
ההגדרות אינו טוען את ``bookmarks.js``, ולכן אין מקור אחד שאפשר לייבא משני הצדדים.
מאז נובמבר 2026 ההגדרה מכבה גם את יצירת הסימניות (``isEnabled``), ולכן שני מפתחות
שנפרדו היו משאירים את המשתמש עם "מוסתר" בהגדרות וסימניות שנוצרות בכל נגיעה — בלי
שום שגיאה. הבדיקה הזו היא מה שצועק כשהם נפרדים.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _one(pattern: str, path: pathlib.Path) -> str:
    found = re.findall(pattern, path.read_text(encoding="utf-8"))
    assert len(found) == 1, f"ציפיתי להגדרה אחת ב-{path.name}, נמצאו {found}"
    return found[0]


def test_the_settings_page_and_bookmarks_js_use_the_same_key():
    settings_key = _one(r"const BM_KEY = '([^']+)';", ROOT / "webapp" / "templates" / "settings.html")
    script_key = _one(r"this\.TOGGLE_VISIBILITY_KEY = '([^']+)';", ROOT / "webapp" / "static" / "js" / "bookmarks.js")
    assert settings_key == script_key

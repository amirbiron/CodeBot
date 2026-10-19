"""החוזה של חיפוש התיעוד: מה שהכותב (מעבר האינדוקס בוובאפ) והקורא (החיפוש) חייבים להסכים עליו.

שמות האוספים והשדות, האינדקס הווקטורי, כתובת האתר וקובץ הייצוא, והדקדוק של מה שנכנס לכתובת
באתר (נתיב עמוד, עוגן). מודול טהור: בלי I/O ובלי ייבוא כבד, כדי שכל צד יוכל לייבא אותו בלי
למשוך איתו מסד, קונפיג או רשת.

**קובץ הייצוא נכתב בבניית האתר, ביחידת פריסה אחרת** — ``scripts/docs_export_sections.py``,
שרץ ב-``.github/workflows/documentation.yml`` עם התלויות של התיעוד בלבד. :data:`SCHEMA_VERSION`,
:data:`EXPORT_PATH` ו-:func:`export_path_for_commit` הם לכן עותק של אותם שמות בסקריפט, ו-
``tests/test_docs_search_contract.py`` משווה ביניהם — וגם את :data:`SITE_URL` מול
``DOCS_SITE_URL`` ב-workflow — כדי שסחיפה תיכשל ב-CI ולא תתגלה בפרודקשן. ייבוא ישיר לא
מתאים לאף כיוון: הסקריפט שייבא את ``services`` היה מריץ את ``services/__init__.py`` בסביבה
של התיעוד, ואילו ``scripts`` הוא namespace package, וחבילה רגילה באותו שם ב-site-packages
גוברת עליו בייבוא. ובזמן ריצה הוובאפ משווה בנוסף את ``site_url`` שבקובץ ל-:data:`SITE_URL`,
ומסרב כשהם שונים.

**כתובת האתר קבועה, בלי משתנה סביבה** (החלטה מ-7.10.2026). היא ממילא נקבעת ב-workflow, שבונה
ממנה את הקישורים שבקובץ. ``DOCUMENTATION_URL`` ב-``webapp/app.py`` הוא עניין אחר: לאן מפנים
קישורי העזרה בממשק, והוא ניתן לשינוי בלי לגעת במקור של האינדקס.
"""

from __future__ import annotations

import re
from typing import Any, Dict, TypeGuard
from urllib.parse import quote

# ---------------------------------------------------------------------------
# האתר והקובץ
# ---------------------------------------------------------------------------

#: הכתובת שבה אתר התיעוד מוגש, ומשם קובץ הייצוא מורד. מסתיימת ב-``/``.
SITE_URL = "https://amirbiron.github.io/CodeBot/"

#: הריפו שממנו האתר נבנה ונפרס. השם הוא גם ``repo_name`` של המראה שלו בוובאפ (``repo_metadata``),
#: ולפיו עמוד האדמין מציג את ה-HEAD של המראה.
SOURCE_REPO_OWNER = "amirbiron"
SOURCE_REPO_NAME = "CodeBot"

#: כפי שהוא מופיע ב-``repository.full_name`` של webhook.
SOURCE_REPO_FULL_NAME = f"{SOURCE_REPO_OWNER}/{SOURCE_REPO_NAME}"

#: שם הסביבה של פריסת GitHub Pages, כפי שהוא מופיע ב-``deployment.environment`` של webhook.
PAGES_ENVIRONMENT = "github-pages"

#: גרסת המבנה של הקובץ שהוובאפ יודע לקרוא. עותק של ``SCHEMA_VERSION`` בסקריפט הייצוא, שגם מתעד מה
#: השתנה בכל גרסה.
SCHEMA_VERSION = 2

#: מיקום הקובץ הראשי, יחסית ל-:data:`SITE_URL`. עותק של ``EXPORT_PATH`` בסקריפט הייצוא.
EXPORT_PATH = "_export/sections.json"

_SHA_RE = re.compile(r"[0-9a-f]{40}")


def is_commit_sha(value: object) -> TypeGuard[str]:
    """האם הערך הוא sha מלא של קומיט: 40 תווי hex קטנים, ולא שום דבר אחר."""
    return isinstance(value, str) and _SHA_RE.fullmatch(value) is not None


def export_path_for_commit(source_commit: str) -> str:
    """מיקום העותק של הקובץ בשם שתלוי בקומיט, יחסית ל-:data:`SITE_URL`.

    עותק של ``export_path_for_commit`` בסקריפט הייצוא, שמסביר גם למה העותק קיים (מטמון
    האתר מתעלם מ-query). ערך שאינו sha מלא נדחה ב-``ValueError``, כי הוא נכנס לכתובת.
    """
    if not is_commit_sha(source_commit):
        raise ValueError(f"expected a 40-character commit sha, got {source_commit!r}")
    folder, _, name = EXPORT_PATH.rpartition("/")
    stem, dot, suffix = name.rpartition(".")
    return f"{folder}/{stem}-{source_commit}{dot}{suffix}"


# ---------------------------------------------------------------------------
# מה שנכנס לכתובת באתר — מה שהמעבר מבטיח על כל ערך שהוא שומר
# ---------------------------------------------------------------------------

#: עוגן של סעיף (``id`` ב-HTML). נמדד על הייצוא של האתר כולו (7.10.2026): כל העוגנים
#: ASCII, מאותיות קטנות, ספרות ומקף. הדקדוק רחב מזה כדי לכלול גם תוויות ש-Sphinx משאיר
#: כמו שהן, אבל עדיין רק תווים שמותרים בעוגן של כתובת בלי קידוד.
ANCHOR_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]*")

_SEGMENT = r"[A-Za-z0-9_-][A-Za-z0-9_.-]*"

#: נתיב של עמוד באתר, יחסית ל-:data:`SITE_URL`. בלי ``/`` בהתחלה, בלי סכמה, ובלי ``.``
#: או ``..`` כמקטע — מקטע אינו יכול להתחיל בנקודה.
PAGE_PATH_RE = re.compile(rf"(?:{_SEGMENT}/)*{_SEGMENT}\.html")

#: קובץ המקור של עמוד, יחסית לשורש הריפו (למשל ``docs/webapp/global-search.rst``).
SOURCE_PATH_RE = re.compile(rf"(?:{_SEGMENT}/)*{_SEGMENT}\.(?:rst|md)")

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def is_dependency_path(value: object) -> TypeGuard[str]:
    """האם הערך הוא קובץ בריפו שעמוד נבנה ממנו מלבד קובץ המקור שלו (``dependencies`` בקובץ הייצוא):
    קוד ש-``literalinclude`` מציג, קובץ ש-``include`` משלב, תמונה, או מודול ש-autodoc מתעד.

    נתיב יחסי לשורש הריפו בצורה מנורמלת: בלי ``/`` בהתחלה, בלי מקטע ריק, ``.`` או ``..``, ובלי תווי
    בקרה. **התווים עצמם חופשיים**, בניגוד ל-:data:`SOURCE_PATH_RE`: הנתיב לא נכנס לכתובת, ובריפו יש
    קבצים עם רווח בשם. בדקדוק צר, שם אחד כזה היה מכשיל את קובץ הייצוא כולו; כך הוא מגיע ל-
    ``get_blob_ids`` במראה, שדוחה אותו, והתצוגה של העמוד ההוא בלבד אומרת שאי אפשר לבדוק.
    """
    if not isinstance(value, str) or not value or _CONTROL_RE.search(value):
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


#: קבצי המקור שהמעבר שומר להם עמוד מורכב (:data:`PAGES_COLLECTION`), לפי הסיומת: rst בלבד. עמוד md
#: מוצג בדפדפן הריפו מהמקור עצמו, בתצוגת ה-Markdown הקיימת. כאן ולא במעבר, כי גם דפדפן הריפו שואל את
#: זה, בלי לייבא את המעבר (``services/docs_page_view.py``).
PAGE_SOURCE_SUFFIXES = frozenset({".rst"})


def text_fragment(text: object) -> str:
    """החלק בכתובת שמקפיץ את הדף אל טקסט בתוכו: ``:~:text=`` והטקסט, מקודד.

    התחביר הוא של URL Fragment Text Directives (https://wicg.github.io/scroll-to-text-fragment/):
    ``-``, ``&`` ו-``,`` הם תחביר של ההנחיה, ולכן בתוך הטקסט הם מקודדים ("Dash (-), ampersand (&), and
    comma (,) characters in text parameters are percent-encoded"). ``quote`` מקודד את ``&`` ואת ``,``,
    אבל משאיר את ``-`` כמו שהוא (``_ALWAYS_SAFE`` ב-``urllib.parse``), ולכן המקף מוחלף כאן. בלעדיו
    הדפדפן קורא את המקף כחלק מההנחיה, ולא מוצא טקסט כמו "ולא את ה-DOM." (נמדד ב-Chromium על העמוד של
    What's New, 11.10.2026; ``test_an_update_headline_is_the_text_on_the_page_and_its_link_jumps_to_it`` ב-
    ``tests/test_docs_export_sections_browser.py`` קופץ גם לפתיח עם מקף).

    הדפדפן מחפש את הטקסט בכל הדף. כשהוא לא מוצא אותו (למשל כי הדף השתנה אחרי שהקישור נבנה), הוא עובר
    לעוגן שלפני ``:~:``, כמו בכתובת בלי ההנחיה — לפי התקן, "If the user agent finishes searching for a text
    directive, ensure it tries the regular fragment as a fallback". ב-Chromium 141 וב-131 זה קורה אחרי
    שהחיפוש נכשל, ולא מיד (נמדד 11.10.2026; אותו טסט מחכה לזה). דפדפן שאינו מכיר את התחביר לא נמדד.
    טקסט ריק אינו הנחיה, ונדחה ב-``ValueError``.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"not a text to jump to: {text!r}")
    return ":~:text=" + quote(text, safe="").replace("-", "%2D")


def section_url(page_path: object, anchor: object, text: object = "") -> str:
    """הכתובת של סעיף באתר: :data:`SITE_URL`, נתיב העמוד והעוגן, אחרי שכל חלק נבדק בדקדוק שלו.

    המעבר בודק את שניהם לפני שהוא שומר (``services/docs_export_client.py``), ולכן ערך שנכשל כאן
    הגיע למסד ממקור אחר. ``ValueError``, כמו ב-:func:`export_path_for_commit`, כי הוא נכנס לכתובת.

    ``text`` — טקסט בתוך הסעיף שהכתובת קופצת אליו (:func:`text_fragment`), למשל הפתיח של עדכון אחד
    בתוך יום ב-What's New. ריק — הכתובת מובילה לעוגן בלבד.
    """
    if not (isinstance(page_path, str) and PAGE_PATH_RE.fullmatch(page_path)):
        raise ValueError(f"not a page path: {page_path!r}")
    if not (isinstance(anchor, str) and ANCHOR_RE.fullmatch(anchor)):
        raise ValueError(f"not an anchor: {anchor!r}")
    if not isinstance(text, str):
        raise ValueError(f"not a text to jump to: {text!r}")
    return f"{SITE_URL}{page_path}#{anchor}" + (text_fragment(text) if text else "")


# ---------------------------------------------------------------------------
# המסד
# ---------------------------------------------------------------------------

#: סעיף אחד במסמך: עמוד, עוגן, שביל כותרות ומארקדאון — מה שהכרטיס בחיפוש מציג.
SECTIONS_COLLECTION = "docs_sections"

#: נתח אחד במסמך: הטקסט שהוטמע והווקטור שלו.
CHUNKS_COLLECTION = "docs_chunks"

#: עמוד אחד במסמך, מורכב מכל הסעיפים שלו לפי הסדר — מה שהתצוגה המרונדרת בדפדפן הריפו מציגה.
#: ה-``_id`` הוא קובץ המקור (``SOURCE_PATH_RE``).
PAGES_COLLECTION = "docs_pages"

#: מסמך המצב של האינדקס, וה-lease של המעבר.
STATE_COLLECTION = "docs_index_state"

#: שם האינדקס הווקטורי ב-Atlas, על :data:`CHUNKS_COLLECTION`. נוצר ידנית.
VECTOR_INDEX_NAME = "docs_vector_index"

#: השדות של הנתח שהאינדקס הווקטורי נשען עליהם. אותם שמות כמו ב-``snippet_chunks``
#: (``services/embedding_worker.py``), כדי שלא יהיו שתי מוסכמות לאותו דבר.
VECTOR_FIELD = "chunkEmbedding"
MODEL_KEY_FIELD = "embeddingModelKey"

#: התקרה של Atlas על מספר המימדים בווקטור: "less than or equal to 8192"
#: (https://www.mongodb.com/docs/vector-search/indexes/vector-search-type/).
ATLAS_MAX_DIMENSIONS = 8192


def vector_index_definition(dimensions: int) -> Dict[str, Any]:
    """ההגדרה ליצירת :data:`VECTOR_INDEX_NAME` ב-Atlas, לפי המימד של ההגדרות הפעילות.

    ``cosine``, כמו ש-``search_engine.py`` מתאר את ``vector_index`` של הסניפטים, ופילטר על
    :data:`MODEL_KEY_FIELD` כדי
    שהחיפוש יוכל לסנן כבר בתוך ``$vectorSearch`` לנתחים של המודל הפעיל. התחביר מהתיעוד של
    Atlas (https://www.mongodb.com/docs/vector-search/indexes/vector-search-type/).
    """
    if type(dimensions) is not int or not 1 <= dimensions <= ATLAS_MAX_DIMENSIONS:
        raise ValueError(f"dimensions must be an int in 1..{ATLAS_MAX_DIMENSIONS}, got {dimensions!r}")
    return {
        "fields": [
            {
                "type": "vector",
                "path": VECTOR_FIELD,
                "numDimensions": dimensions,
                "similarity": "cosine",
            },
            {"type": "filter", "path": MODEL_KEY_FIELD},
        ]
    }

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

#: גרסת המבנה של הקובץ שהוובאפ יודע לקרוא. עותק של ``SCHEMA_VERSION`` בסקריפט הייצוא.
SCHEMA_VERSION = 1

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

# ---------------------------------------------------------------------------
# המסד
# ---------------------------------------------------------------------------

#: סעיף אחד במסמך: עמוד, עוגן, שביל כותרות ומארקדאון — מה שהכרטיס בחיפוש מציג.
SECTIONS_COLLECTION = "docs_sections"

#: נתח אחד במסמך: הטקסט שהוטמע והווקטור שלו.
CHUNKS_COLLECTION = "docs_chunks"

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

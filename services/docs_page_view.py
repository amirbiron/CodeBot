"""התצוגה המרונדרת של עמוד rst בדפדפן הריפו: האם יש לו עמוד, מה העמוד, והאם הוא נבנה מהתוכן שמוצג.

**מאיפה העמוד.** מהאינדקס של התיעוד (:data:`~services.docs_search_contract.PAGES_COLLECTION`): מעבר
האינדוקס מרכיב כל עמוד rst מהסעיפים שלו בקובץ הייצוא של האתר (``page_markdown`` ב-
``services/docs_index_service.py``), כלומר מההמרה של Sphinx ולא מממיר rst בוובאפ. עמוד שהייצוא מדלג
עליו (``docs/api/``) אין לו עמוד, והקובץ מוצג כקוד בלבד.

**מתי העמוד ישן מהקובץ.** האתר נבנה ונפרס אחרי מיזוג, והאינדקס מתעדכן אחרי הפריסה; בינתיים המראה
כבר מציגה את הקובץ החדש. לכן התשובה אומרת אם העמוד נבנה מאותו תוכן בדיוק (:func:`freshness`):
הקומיט שהאינדקס נכון אליו (``indexed_source_commit``) מול ה-ref שהדפדפן מציג, בהשוואה של ה-blob בשניהם
— של הקובץ, ושל כל קובץ אחר שהעמוד נבנה ממנו (``dependencies``: קוד ש-``literalinclude`` מציג, מודול
ש-autodoc מתעד). קומיט שלא נגע בהם נותן אותם blobs, ולכן הוא לא נחשב שינוי. מה שלא נמדד: שינוי בממיר
או בתצורה של האתר עצמו (``docs/_static/copy-page.js``, ``docs/conf.py``), שחל על כל העמודים ואינו קלט
של עמוד אחד — גם Sphinx אינו רושם אותו כתלות של עמוד.

**המודול קל בכוונה.** דפדפן הריפו מייבא אותו בזמן שהוא נטען, ו-``webapp/app.py`` מדלג בשקט על blueprint
שהייבוא שלו נכשל. לכן ברמת המודול יש כאן רק את החוזה (:mod:`services.docs_search_contract`), והמעבר
(``services/docs_index_service.py``, עם לקוח ההטמעות והקונפיג שהוא קורא בזמן ייבוא) נטען רק
ב-:func:`read_docs_page`. כשל שם מפיל את התצוגה המרונדרת של קובץ אחד, ולא את דפדפן הריפו.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Dict, Optional, Tuple

from services import docs_search_contract as contract

#: העמוד נבנה מאותו תוכן שמוצג.
FRESHNESS_CURRENT = "current"
#: הקובץ שמוצג שונה ממה שהעמוד נבנה ממנו — בדרך כלל כי הוא השתנה אחרי הבנייה האחרונה של האתר.
FRESHNESS_CHANGED = "changed"
#: הקובץ עצמו לא השתנה, אבל קובץ אחר שהעמוד נבנה ממנו כן (:attr:`Freshness.changed_dependencies`).
FRESHNESS_DEPENDENCY_CHANGED = "dependency_changed"
#: אין עם מה להשוות: האינדקס באמצע מעבר או חלקי, נבנה בכללים אחרים, או שהקומיט שלו (או הקובץ בו)
#: אינו במראה.
FRESHNESS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Freshness:
    """התשובה של :func:`freshness`: אחד מ-``FRESHNESS_*``, והקבצים האחרים שהשתנו כשהוא
    :data:`FRESHNESS_DEPENDENCY_CHANGED`."""

    state: str
    changed_dependencies: Tuple[str, ...] = ()


def offers_docs_page(repo_name: str, file_path: str) -> bool:
    """האם לקובץ הזה בכלל יכול להיות עמוד: קובץ rst בריפו שממנו האתר נבנה. בלי גישה למסד."""
    return (
        repo_name == contract.SOURCE_REPO_NAME
        and PurePosixPath(file_path).suffix in contract.PAGE_SOURCE_SUFFIXES
    )


def has_docs_page(db: Any, file_path: str) -> bool:
    """האם יש באינדקס עמוד לקובץ. קריאה לפי ``_id``, בלי התוכן."""
    return db[contract.PAGES_COLLECTION].find_one({"_id": file_path}, {"_id": 1}) is not None


def read_docs_page(db: Any, file_path: str) -> Optional[Dict[str, Any]]:
    """העמוד של הקובץ עם הקומיט שהוא נבנה ממנו, או ``None`` כשאין לקובץ עמוד.

    ``indexed_commit`` הוא הקומיט שהאינדקס נכון אליו, רק כשמסמך המצב אומר את אותו דבר לפני קריאת
    העמוד ואחריה: מעבר שהתחיל או הסתיים בין שתי הקריאות היה יכול לכתוב עמוד מבנייה אחרת, ואז אין
    קומיט (``None``) והתצוגה אומרת שאי אפשר לבדוק. ``dependencies`` הם הקבצים האחרים שהעמוד נבנה מהם,
    או ``None`` כשהשדה במסמך אינו רשימה של נתיבים — ואז גם אי אפשר לבדוק.
    """
    # המעבר נטען כאן ולא בראש המודול — ההסבר בראש הקובץ.
    from services import docs_index_service

    before = _indexed_commit(docs_index_service.read_state(db), docs_index_service.RECORDS_VERSION)
    page = db[contract.PAGES_COLLECTION].find_one(
        {"_id": file_path}, {"_id": 0, "markdown": 1, "page_path": 1, "title": 1, "dependencies": 1}
    )
    if page is None:
        return None
    after = _indexed_commit(docs_index_service.read_state(db), docs_index_service.RECORDS_VERSION)
    dependencies = page.get("dependencies")
    return {
        "markdown": page.get("markdown"),
        "page_path": page.get("page_path"),
        "title": page.get("title"),
        "dependencies": (
            tuple(dependencies)
            if isinstance(dependencies, list) and all(isinstance(path, str) for path in dependencies)
            else None
        ),
        "indexed_commit": before if before == after else None,
    }


def _indexed_commit(state: Optional[Dict[str, Any]], records_version: int) -> Optional[str]:
    """הקומיט שכל הרשומות באינדקס נכונות אליו — כולל העמודים, ולכן רק בכללים שכותבים עמודים."""
    if not state or state.get("indexed_records_version") != records_version:
        return None
    commit = state.get("indexed_source_commit")
    return commit if contract.is_commit_sha(commit) else None


def freshness(
    git_service: Any,
    repo_name: str,
    file_path: str,
    shown_ref: str,
    indexed_commit: Optional[str],
    dependencies: Optional[Tuple[str, ...]],
) -> Freshness:
    """האם העמוד נבנה מהתוכן שמוצג: :class:`Freshness` עם אחד מ-``FRESHNESS_*``.

    משווים את ה-blobs של הקובץ ושל כל קובץ ב-``dependencies``, בקומיט שהעמוד נבנה ממנו מול ה-ref
    שהדפדפן מציג — פקודת git אחת לכל צד (``get_blob_ids``). שינוי בקובץ עצמו קובע
    :data:`FRESHNESS_CHANGED`; אחרת שינוי בקובץ אחר קובע :data:`FRESHNESS_DEPENDENCY_CHANGED`, וקובץ
    אחר שנמחק מאז הוא שינוי כזה. "אי אפשר לבדוק" (:data:`FRESHNESS_UNKNOWN`) ולא "השתנה": כשאין
    קומיט או רשימת קבצים, כש-``get_blob_ids`` לא ענה (ref שאינו במראה), או כשקובץ חסר בקומיט שהעמוד
    נבנה ממנו — שם הוא היה חייב להיות.
    """
    if indexed_commit is None or dependencies is None:
        return Freshness(FRESHNESS_UNKNOWN)
    paths = [file_path, *dependencies]
    built = git_service.get_blob_ids(repo_name, indexed_commit, paths)
    shown = git_service.get_blob_ids(repo_name, shown_ref, paths)
    if built is None or shown is None or any(path not in built for path in paths) or file_path not in shown:
        return Freshness(FRESHNESS_UNKNOWN)
    if built[file_path] != shown[file_path]:
        return Freshness(FRESHNESS_CHANGED)
    changed = tuple(path for path in dependencies if built[path] != shown.get(path))
    if changed:
        return Freshness(FRESHNESS_DEPENDENCY_CHANGED, changed)
    return Freshness(FRESHNESS_CURRENT)

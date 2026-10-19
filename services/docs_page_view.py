"""התצוגה המרונדרת של עמוד rst בדפדפן הריפו: האם יש לו עמוד, מה העמוד, והאם הוא נבנה מהתוכן שמוצג.

**מאיפה העמוד.** מהאינדקס של התיעוד (:data:`~services.docs_search_contract.PAGES_COLLECTION`): מעבר
האינדוקס מרכיב כל עמוד rst מהסעיפים שלו בקובץ הייצוא של האתר (``page_markdown`` ב-
``services/docs_index_service.py``), כלומר מההמרה של Sphinx ולא מממיר rst בוובאפ. עמוד שהייצוא מדלג
עליו (``docs/api/``) אין לו עמוד, והקובץ מוצג כקוד בלבד.

**מתי העמוד ישן מהקובץ.** האתר נבנה ונפרס אחרי מיזוג, והאינדקס מתעדכן אחרי הפריסה; בינתיים המראה
כבר מציגה את הקובץ החדש. לכן התשובה אומרת אם העמוד נבנה מאותו תוכן בדיוק (:func:`freshness`):
הקומיט שהאינדקס נכון אליו (``indexed_source_commit``) מול ה-ref שהדפדפן מציג, בהשוואה של ה-blob של
הקובץ בשניהם. קומיט שלא נגע בקובץ נותן אותו blob, ולכן הוא לא נחשב שינוי.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Dict, Optional

from services import docs_search_contract as contract
from services.docs_index_service import PAGE_SOURCE_SUFFIXES, RECORDS_VERSION, read_state

#: העמוד נבנה מאותו תוכן שמוצג.
FRESHNESS_CURRENT = "current"
#: הקובץ שמוצג שונה ממה שהעמוד נבנה ממנו — בדרך כלל כי הוא השתנה אחרי הבנייה האחרונה של האתר.
FRESHNESS_CHANGED = "changed"
#: אין עם מה להשוות: האינדקס באמצע מעבר או חלקי, נבנה בכללים אחרים, או שהקומיט שלו (או הקובץ בו)
#: אינו במראה.
FRESHNESS_UNKNOWN = "unknown"


def offers_docs_page(repo_name: str, file_path: str) -> bool:
    """האם לקובץ הזה בכלל יכול להיות עמוד: קובץ rst בריפו שממנו האתר נבנה. בלי גישה למסד."""
    return repo_name == contract.SOURCE_REPO_NAME and PurePosixPath(file_path).suffix in PAGE_SOURCE_SUFFIXES


def has_docs_page(db: Any, file_path: str) -> bool:
    """האם יש באינדקס עמוד לקובץ. קריאה לפי ``_id``, בלי התוכן."""
    return db[contract.PAGES_COLLECTION].find_one({"_id": file_path}, {"_id": 1}) is not None


def read_docs_page(db: Any, file_path: str) -> Optional[Dict[str, Any]]:
    """העמוד של הקובץ עם הקומיט שהוא נבנה ממנו, או ``None`` כשאין לקובץ עמוד.

    ``indexed_commit`` הוא הקומיט שהאינדקס נכון אליו, רק כשמסמך המצב אומר את אותו דבר לפני קריאת
    העמוד ואחריה: מעבר שהתחיל או הסתיים בין שתי הקריאות היה יכול לכתוב עמוד מבנייה אחרת, ואז אין
    קומיט (``None``) והתצוגה אומרת שאי אפשר לבדוק.
    """
    before = _indexed_commit(read_state(db))
    page = db[contract.PAGES_COLLECTION].find_one(
        {"_id": file_path}, {"_id": 0, "markdown": 1, "page_path": 1, "title": 1}
    )
    if page is None:
        return None
    after = _indexed_commit(read_state(db))
    return {
        "markdown": page.get("markdown"),
        "page_path": page.get("page_path"),
        "title": page.get("title"),
        "indexed_commit": before if before == after else None,
    }


def _indexed_commit(state: Optional[Dict[str, Any]]) -> Optional[str]:
    """הקומיט שכל הרשומות באינדקס נכונות אליו — כולל העמודים, ולכן רק בכללים שכותבים עמודים."""
    if not state or state.get("indexed_records_version") != RECORDS_VERSION:
        return None
    commit = state.get("indexed_source_commit")
    return commit if contract.is_commit_sha(commit) else None


def freshness(git_service: Any, repo_name: str, file_path: str, shown_ref: str, indexed_commit: Optional[str]) -> str:
    """:data:`FRESHNESS_CURRENT`, :data:`FRESHNESS_CHANGED` או :data:`FRESHNESS_UNKNOWN`.

    מה שמושווה הוא התוכן של הקובץ (ה-blob) בקומיט שהעמוד נבנה ממנו מול ה-ref שהדפדפן מציג.
    ``get_blob_id`` מחזיר ``None`` כשאין תשובה — ref שאינו במראה, או קובץ שלא קיים בו — וזה
    "אי אפשר לבדוק", לא "השתנה".
    """
    if indexed_commit is None:
        return FRESHNESS_UNKNOWN
    built = git_service.get_blob_id(repo_name, file_path, indexed_commit)
    shown = git_service.get_blob_id(repo_name, file_path, shown_ref)
    if built is None or shown is None:
        return FRESHNESS_UNKNOWN
    return FRESHNESS_CURRENT if built == shown else FRESHNESS_CHANGED

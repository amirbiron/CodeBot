"""Data-access layer for the MCP tools.

Tools/handlers depend on a duck-typed "backend" (any object exposing the read
methods below), so they can be unit-tested with a fake. ``ProductionBackend``
wraps the real in-process database layer (``database.db`` +
``CollectionsManager``) and is imported lazily so this module stays light.

All read paths are ``user_id``-scoped. The one method that touches a
non-user-scoped DB call (``get_file_by_id``) re-checks ownership here.

Per the project's "Smart Projection" rule, list/search results never carry the
heavy ``code``/``content`` fields — full content is returned only by
``get_file`` for an explicit single-file fetch.
"""

from __future__ import annotations

import datetime as _dt
import enum as _enum
import html
import os
import threading
import time as _time
import logging
import uuid as _uuid
from typing import Any, Callable

from .handlers import (
    QUERY_OUTPUT_BYTE_BUDGET,
    QUERY_RESULTS_DEFAULT,
    apply_line_range,
    file_query_request_error,
    normalize_line_range,
    scan_file_query,
)

# מודול שורש טהור (``datetime`` ו-``typing`` בלבד), ולכן ייבוא ישיר ולא עצל:
# הוא אינו גורר את שכבת המסד. ראו ``file_dates.py``.
from file_dates import version_created_at

# גיל התיאור — אותו סוג מודול שורש טהור בדיוק, ולכן אותו ייבוא ישיר.
from file_description import DESCRIPTION_SET_AT_VERSION_FIELD, description_age_field

# ``DuplicateKeyError`` נדרש כדי להבחין בין "שם תפוס" לבין תקלה אמיתית.
# אותה תבנית ייבוא עמיד שבה משתמש ``webapp/sticky_notes_api``: בסביבות
# בדיקה בלי pymongo, מחלקה מקומית שלא תיזרק לעולם עדיפה על ייבוא שמפיל
# את המודול כולו.
try:  # type: ignore
    from pymongo.errors import DuplicateKeyError as _DuplicateKeyError  # type: ignore
except Exception:  # pragma: no cover
    class _DuplicateKeyError(Exception):  # type: ignore
        pass


logger = logging.getLogger(__name__)


def _push_events_enabled() -> bool:
    """האם לרשום אירועי התראה על כתיבה דרך ה-MCP. ברירת המחדל: כן.

    הדגל נקרא כאן, **בצד הכותב**, ולא בצד השולח. אירוע שכובה אינו נרשם כלל
    ולא נרשם-ומסונן, ולכן כיבוי אינו מותיר תור שמתמלא בלי שאף אחד קורא ממנו.

    אותה צורת פענוח כמו ``PUSH_NOTIFICATIONS_ENABLED`` ב-``webapp/push_api.py``.
    """
    return os.getenv("MCP_PUSH_NOTIFICATIONS_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_HEAVY_FIELDS = ("code", "content", "raw_data", "raw_content")

#: תשתית החיפוש הסמנטי, שאינה עניינו של מי שקורא קובץ.
#:
#: ``snippetEmbedding`` לבדו הוא 768 מספרים — כ-9KB בכל תשובה, בלי קשר לגודל
#: הקובץ. הוא היה יוצא גם כשמבקשים שש שורות, וגדול פי כמה מהקובץ עצמו: בדיוק
#: ההפך ממה ש-``lines`` נועד לחסוך. השאר קטנים, אבל אף אחד מהם אינו אומר דבר
#: לצרכן — הם הנהלת חשבונות של ה-EmbeddingWorker.
#:
#: **אף אחד מהם לא נשלף מכאן.** הווקטור נקרא אך ורק בתוך מונגו, ב-
#: ``$vectorSearch`` (``search_engine.py``); שום קוד פייתון לא קורא אותו חזרה
#: ממסמך. את דגלי העיבוד (``needs_embedding``, ``contentHash``, ``chunkCount``
#: וכו׳) שולף ``services/embedding_worker.py`` דרך projection ייעודי משלו
#: (``database/manager.py``), ולא דרך הכלים כאן.
#:
#: **הרשימה משוכפלת במכוון מ-``SNIPPET_SEMANTIC_FIELDS`` שב-``database/schemas.py``.**
#: ייבוא ישיר היה מריץ את ``database/__init__.py``, שבונה ``DatabaseManager()``
#: בזמן טעינת המודול — בניגוד לכלל שבראש החבילה, שלפיו מודול כאן מייבא רק
#: תלויות קלות. מה שמחזיק את שתי הרשימות צמודות הוא טסט שדורש **שוויון מלא**
#: בשני הכיוונים, כדי ששדה שנוסף שם לא ידלוף לכאן, ושדה שהוסר שם לא יישאר
#: כאן תלוי באוויר.
_SEMANTIC_FIELDS = (
    "snippetEmbedding",
    "needs_embedding",
    "needs_chunking",
    "contentHash",
    "embeddingUpdatedAt",
    "embeddingModelKey",
    "embeddingModel",
    "embeddingApiVersion",
    "embeddingDim",
    "chunkCount",
    "chunkerVersion",
)

# שדות הפתק שנחשפים ל-MCP — רזה במכוון (בלי מיקום/גודל פיקסלים, שהם עניין ויזואלי)
#: פתק לוח נושא ``board_id`` ו-``mode``; בלעדיהם הפלט לא אומר איפה הוא
#: יושב. בפתק קובץ שניהם ריקים, ולכן התוספת אינה משנה את מסלול הקובץ.
#: ``repo_name``/``repo_path`` נוספו מאותו טעם בדיוק שבגללו ``board_id``
#: כאן: ``update_note`` מחזיר ``_as_note``, ובלי שני החצאים עדכון של פתק
#: ריפו היה מדווח על פתק **בלי יעד** — כאילו אינו יושב בשום מקום.
_NOTE_FIELDS = (
    "content", "color", "line_start", "anchor_text", "is_minimized",
    "board_id", "mode", "title", "repo_name", "repo_path",
)

class _NoteIndex(_enum.Enum):
    """זהות אינדקס אכיפה — במקום שם מחרוזתי שנפתר ב-``getattr``.

    הערך הוא גם התווית שמופיעה בלוגים, כך שאין שני מקורות אמת לשם.
    """

    BOARD_TITLE = "one_title_per_board"
    REPO_TITLE = "one_title_per_repo_file"
    NOTE_VERSIONS = "one_number_per_note_version"


class _IndexGate:
    """מצב הבנייה של אינדקס אכיפה יחיד.

    ``ok`` ו-``retry_at`` יושבים יחד **בכוונה**: הם זוג שנע כיחידה אחת,
    ופיצולם לשני דגלים נפרדים הוא בדיוק מה שמאפשר למישהו לשתף בטעות את
    האחד בין שני אינדקסים ולא את השני.
    """

    __slots__ = ("ok", "retry_at")

    def __init__(self) -> None:
        self.ok = False
        self.retry_at = 0.0


#: שדות הזיהוי שפגיעת חיפוש מחזירה — **בלי תוכן ובלי תצוגה מקדימה**.
#: ראו :func:`_as_note_ref`.
_NOTE_REF_FIELDS = (
    "title", "file_name", "file_id", "board_id", "repo_name", "repo_path", "updated_at",
)


def _json_safe(value: Any) -> Any:
    """Recursively convert Mongo/BSON types to JSON-friendly values."""
    if isinstance(value, (_dt.datetime, _dt.date)):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if type(value).__name__ == "ObjectId":  # avoid importing bson
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _clean(doc: dict[str, Any], *, include_code: bool = False) -> dict[str, Any]:
    """Serialize a file document. Drops heavy fields unless ``include_code``.

    שדות החיפוש הסמנטי יורדים **תמיד**, גם עם ``include_code``: הם אינם תוכן
    הקובץ אלא תשתית שמתלווה אליו, ומי שביקש את הקוד לא ביקש אותה.

    **גיל התיאור מחושב כאן, ובמכוון במקום אחד ולא בכל כלי בנפרד.**
    ‏``_clean`` הוא הצוואר שכל מסמך קובץ עובר דרכו בשרת הזה —
    ‏``list_files``, ``search_code``, ``get_file`` (דרך ``_full``),
    ‏``list_versions`` ו-``save_file``. חישוב בכל קורא היה מוסיף לכל כלי
    חדש דרישה לזכור, והכלי שישכח יחזיר קובץ בלי שום סימן שמשהו חסר בו.
    ההחלטה מתי השדה מופיע בכלל יושבת ב-``file_description``, ליד החישוב.

    **החותמת הגולמית עצמה יורדת מהתשובה.** ``description_age_versions``
    נגזר ממנה וממספר הגרסה, ושני שדות שאומרים את אותו דבר הם רעש שסוכן
    צריך להכריע ביניהם. החותמת היא פרט אחסון, לא ממשק.
    """
    out: dict[str, Any] = {}
    for key, val in (doc or {}).items():
        if key == "_id":
            out["id"] = str(val)
            continue
        if key in _SEMANTIC_FIELDS or key == DESCRIPTION_SET_AT_VERSION_FIELD:
            continue
        if not include_code and key in _HEAVY_FIELDS:
            continue
        out[key] = _json_safe(val)
    # Friendlier alias without dropping the original field.
    if "programming_language" in out:
        out.setdefault("language", out["programming_language"])
    # מה-doc הגולמי ולא מ-``out``: החותמת כבר ירדה ממנו שתי שורות למעלה.
    out.update(description_age_field(doc))
    return out


def _apply_range_to_file(out: dict[str, Any], lines: Any) -> dict[str, Any]:
    """חותך את תוכן הקובץ לטווח שביקשו, בעזרת אותו עוזר משותף.

    **``code`` הוא הטקסט הקנוני.** ``_full`` כבר מבטיח את זה: קטע רגיל
    (``CodeSnippet``) נושא ``code`` בלבד, קובץ גדול (``LargeFile``) נושא
    ``content`` בלבד ו-``_full`` מעתיק אותו ל-``code``. מסמך שנושא את שניהם
    עם ערכים שונים אינו קיים באף אחד משני המודלים. לכן החיתוך נעשה תמיד
    מ-``code``, ו-``content`` — אם הוא קיים — מקבל את אותו ערך חתוך, כדי
    ששני השדות לא ייפרדו בתשובה.

    שגיאת טווח מוחזרת כמעטפת ``{"ok": false, ...}``, ולכן ``get_file`` שב-
    ``server.py`` מזהה אותה ומעביר אותה כמות שהיא במקום ``{"found": true}``.
    """
    bounds = normalize_line_range(lines)
    if isinstance(bounds, str):
        return {"ok": False, "error": bounds}
    sliced = apply_line_range(out.get("code") or "", *bounds)
    if isinstance(sliced, str):
        return {"ok": False, "error": sliced}
    out["code"] = sliced["text"]
    if "content" in out:
        out["content"] = sliced["text"]
    out["range"] = sliced["range"]
    return out


def _apply_query_to_file(
    out: dict[str, Any], query: str, *, context_lines: int, max_results: int
) -> dict[str, Any]:
    """מחליף את תוכן הקובץ ב**מופעים** של ``query`` בתוכו.

    אותה תבנית שבה ``outline=true`` מחזיר מפה במקום תוכן ב-
    ``codekeeper_get_repo_file``: המטא-דאטה של הקובץ נשארת, התוכן יורד,
    ובמקומו נכנסים השדות של ``codekeeper_search_repo`` — ``query``, ``count``,
    ``total``, ``results`` ו-``truncated``, באותם שמות בדיוק.

    **התוכן יורד, וזה כל הרעיון.** ``_HEAVY_FIELDS`` הוא אותה רשימה שמסירה את
    התוכן בכל מסלול רשימה/חיפוש אחר בשרת הזה, ולא רשימה שנייה שצריך לזכור
    לעדכן: שדה תוכן חדש שיתווסף לה יורד גם מכאן.

    **החיתוך נעשה מ-``code``**, מאותו נימוק בדיוק שכתוב ב-
    :func:`_apply_range_to_file` — ``_full`` כבר מבטיח שהוא הטקסט הקנוני.

    **המעטפת מלאה ולא מסמך.** ``get_file`` ב-``server.py`` עוטף מסמך רגיל
    ב-``{"found": true, "file": ...}``; כאן המעטפת נבנית כאן, ולכן היא נושאת
    ``status`` שמסמן במפורש שזו תשובת מופעים. ``found`` נשאר במקומו כדי
    שצרכן קיים שמסתעף עליו ימשיך לעבוד.
    """
    found = scan_file_query(
        out.get("code") or "",
        query,
        max_results=max_results,
        context_lines=context_lines,
        byte_budget=QUERY_OUTPUT_BYTE_BUDGET,
    )
    meta = {key: val for key, val in out.items() if key not in _HEAVY_FIELDS}
    return {"found": True, "status": "query", "file": meta, "query": query, **found}


def _full(doc: dict[str, Any]) -> dict[str, Any]:
    """Serialize a single file WITH content (regular ``code`` or large ``content``)."""
    out = _clean(doc, include_code=True)
    if not out.get("code") and out.get("content"):
        out["code"] = out["content"]
    return out


def _strip_heavy(value: Any) -> Any:
    """Recursively drop heavy content fields from an already-serialized value."""
    if isinstance(value, dict):
        return {k: _strip_heavy(v) for k, v in value.items() if k not in _HEAVY_FIELDS}
    if isinstance(value, list):
        return [_strip_heavy(v) for v in value]
    return value


def _as_note(doc: dict[str, Any]) -> dict[str, Any]:
    """Serialize a sticky-note document for MCP output (lean, JSON-safe)."""
    doc = doc or {}
    out: dict[str, Any] = {"id": str(doc.get("_id") or "")}
    for key in _NOTE_FIELDS:
        out[key] = _json_safe(doc.get(key))
    # פתקי legacy נשמרו עם HTML entities — משחזרים טקסט כמו שהוובאפ עושה בקריאה
    if isinstance(out.get("content"), str):
        out["content"] = html.unescape(out["content"])
    # **הצבע נגזר ואינו מועתק גולמי — אותו חוזה בדיוק כמו
    # ``webapp/sticky_notes_api._as_note_response``.**
    #
    # מה שיושב במסד הוא מזהה מהפלטה (``yellow``) או ``hex`` legacy, ומאז
    # שהפלטה נוספה שתי הצורות חיות זו לצד זו: פתק שהמיגרציה יישרה מול פתק
    # שלא. העתקה ישירה החזירה לסוכן **שתי תשובות שונות לאותו צבע בדיוק**,
    # בלי שום דרך מצידו לדעת זאת — חוזה שאינו עקבי עם עצמו, שגרוע מחוזה
    # שהשתנה.
    #
    # ``color`` נשאר ``hex`` כי זה מה שהיה כאן מאז ומתמיד וזה מה שסוכן
    # קיים מצפה לו; ``color_id`` הוא המזהה, או ``""`` לצבע שאינו בפלטה.
    # שניהם נגזרים מערך אחד במסמך, ולכן אינם יכולים להיסחף זה מזה.
    from sticky_notes_target import note_color_hex, note_color_id

    raw_color = doc.get("color")
    out["color"] = note_color_hex(raw_color)
    out["color_id"] = note_color_id(raw_color)
    out["created_at"] = _json_safe(doc.get("created_at"))
    out["updated_at"] = _json_safe(doc.get("updated_at"))
    return out


def _as_note_ref(doc: dict[str, Any] | None) -> dict[str, Any]:
    """פגיעת חיפוש: זהות וניווט בלבד.

    **האינווריאנטה:** שדות הזיהוי של פגיעה הם בדיוק רשימת הארגומנטים של
    כלי הרשימה שמתאים ליעד שלה — ``file_name`` ל-``list_notes``,
    ``board_id`` ל-``list_board_notes``, ו-``repo_name``+``repo_path``
    ל-``list_repo_notes``. מי שקיבל פגיעה יכול תמיד להמשיך ממנה.

    **סריאלייזר נפרד ולא ``_as_note`` פחות ``content``** — "לזכור להסיר את
    השדה הכבד" הוא בדיוק מצב הכשל ש-Smart Projection נועד למנוע: שדה כבד
    חדש שייכנס ל-``_NOTE_FIELDS`` היה נשפך לכל תוצאת חיפוש בשקט.
    """
    from sticky_notes_target import note_target_ref

    doc = doc or {}
    out: dict[str, Any] = {"id": str(doc.get("_id") or "")}
    out["title"] = _json_safe(doc.get("title"))
    # ``note_target_ref`` לעולם אינו זורק — שורה פגומה אחת אינה הורגת חיפוש
    out.update(_json_safe(note_target_ref(doc)))
    out["updated_at"] = _json_safe(doc.get("updated_at"))
    return out


def _as_note_summary(doc: dict[str, Any] | None) -> dict[str, Any]:
    """שורת פתק **בלי הגוף** — מה ש-``include_content=false`` מחזיר ברשימה.

    **סריאלייזר משלו ולא ``_as_note`` פחות ``content``**, מאותו נימוק שכתוב
    ב-:func:`_as_note_ref`: "לזכור להסיר את השדה הכבד" הוא בדיוק מצב הכשל
    ש-Smart Projection נועד למנוע. מה שכן יש כאן הוא הזהות, הצבע, מועד
    העדכון — ו**גודל** הגוף, כדי שהקורא יחליט אילו פתקים לקרוא.

    ``content_bytes`` נמדד על הגוף **כפי שהוא מאוחסן**, ב**בתים** של UTF-8
    ולא בתווים — היחידה שבה ``OUTPUT_BYTE_BUDGET`` נמדד, ובפתק עברי ההפרש
    הוא פי שניים. וזה בדיוק גודל ה-``content`` ש-``get_note`` יחזיר לאותו
    פתק, כי גם הוא מחזיר את הגוף המאוחסן. גוף שאינו מחרוזת — אף כותב אינו
    שומר כזה, אבל השדה מגיע מהמסד — מדווח ``None`` ("לא ידוע"), ולא ``0``
    שמשמעו "ידוע שריק".
    """
    from sticky_notes_target import note_color_hex, note_color_id

    doc = doc or {}
    raw_color = doc.get("color")
    content = doc.get("content")
    return {
        "id": str(doc.get("_id") or ""),
        "title": _json_safe(doc.get("title")),
        # אותו זוג נגזר כמו ב-``_as_note``, מאותו ערך אחד במסמך.
        "color": note_color_hex(raw_color),
        "color_id": note_color_id(raw_color),
        "content_bytes": len(content.encode("utf-8")) if isinstance(content, str) else None,
        "updated_at": _json_safe(doc.get("updated_at")),
    }


def _notes_scope_filter(
    user_id: int, scope_id: str | None, related_ids: list[str]
) -> dict[str, Any]:
    """The webapp-parity notes query: by scope_id, plus file_id for legacy notes.

    Module-level and pure so tests can assert the exact query shape.
    """
    clauses: list[dict[str, Any]] = []
    if scope_id:
        clauses.append({"scope_id": scope_id})
    if related_ids:
        clauses.append({"file_id": {"$in": list(related_ids)}})
    if not clauses:
        # בלי אף clause השאילתה הייתה ``{"user_id": uid}`` — כלומר **כל**
        # הפתקים של המשתמש, ולא הפתקים של הקובץ שהתבקש. היום זה לא נגיש,
        # כי scope_id תמיד מחושב משם קובץ לא-ריק; משנוספו פתקי לוח, פתק
        # שאינו שייך לשום קובץ היה נשאב לתשובה. שאילתה שלא תופסת דבר היא
        # התשובה הנכונה ל"אין לי לפי מה לחפש".
        return {"user_id": int(user_id), "_id": {"$in": []}}
    return {"user_id": int(user_id), "$or": clauses}


def _latest_fresh(dbm: Any, user_id: int, file_name: str) -> dict[str, Any] | None:
    """Latest version straight from the DB, bypassing the read cache.

    Edits are read-modify-write: a cached body would make every edit rebuild
    from a stale base, and a cached version number would hand two versions the
    same value. Falls back to the cached getter for DB managers that predate
    ``get_latest_version_fresh`` so an older injection never breaks the server.
    """
    getter = getattr(dbm, "get_latest_version_fresh", None)
    if callable(getter):
        return getter(user_id, file_name)
    return dbm.get_latest_version(user_id, file_name)


class ProductionBackend:
    """Backend backed by the real in-process ``database`` layer.

    Heavy imports (``database``) happen lazily on first use so importing this
    module never drags in the whole application.
    """

    #: Guards the lazy paths whose construction is not free. Tool bodies run on
    #: worker threads since #3379, so two reads can reach an unbuilt lazy field
    #: at the same moment; before that the event loop made every body exclusive
    #: and the question could not arise. It is held only while something is
    #: being built — nothing on the read or write path takes it.
    #:
    #: **On the class and not the instance, deliberately.** The tests in this
    #: repository build backends with ``ProductionBackend.__new__(...)`` in
    #: several places, which never runs ``__init__``; a lock created there would
    #: be missing exactly where a fake is used. One lock shared by every backend
    #: in the process costs nothing, because the only thing it serializes is
    #: first-time construction, and production has one backend.
    _lazy_lock = threading.Lock()

    def __init__(
        self, db_manager: Any = None, mongo_db: Any = None, collections_manager: Any = None
    ) -> None:
        self._dbm = db_manager
        self._mongo = mongo_db
        self._cm = collections_manager
        self._notes_idx_done = False

    # -- lazy wiring -------------------------------------------------------
    def _require_dbm(self) -> Any:
        """The database module, imported on first use.

        Deliberately not locked, and that is a decision rather than an
        oversight. The guard is the value itself, so there is no window where
        one is set and the other is not, and the "construction" is an ``import``
        that Python has already cached — two threads racing here bind the same
        module object twice and nothing else happens.
        """
        if self._dbm is None:
            from database import db as _db  # lazy heavy import

            self._dbm = _db
        return self._dbm

    def _collections(self) -> Any:
        """The collections manager, built on first use — under a lock.

        **Locked because the constructor is not free.**
        ``CollectionsManager.__init__`` calls ``_ensure_indexes``, which issues
        ``create_indexes`` against Mongo and then runs a one-time migration
        guarded by a class attribute (``_migration_done``) that is itself a
        check-then-act. Two threads arriving together would both send the index
        round trips and could both enter that migration, running its
        ``update_many`` backfills over the whole collection twice. The data ends
        up the same — the migration is idempotent — but the work is real, and
        since #3379 two reads can arrive together where before the loop kept
        them apart.

        The publication order needs no fixing: the guard *is* the value, and it
        is assigned only after the constructor returns, so a failure leaves it
        unset and the next call genuinely retries.

        Tests that inject ``collections_manager`` never reach this path at all.
        """
        if self._cm is not None:
            return self._cm
        with self._lazy_lock:
            # Re-checked inside: the thread that waited here may be looking at a
            # field the holder already filled.
            if self._cm is None:
                from database.collections_manager import CollectionsManager  # lazy

                mongo = (
                    self._mongo
                    if self._mongo is not None
                    else getattr(self._require_dbm(), "db", None)
                )
                if mongo is None:
                    raise RuntimeError("MongoDB handle unavailable for collections")
                self._cm = CollectionsManager(mongo)
        return self._cm

    # -- files -------------------------------------------------------------
    def list_files(self, user_id: int, *, page: int = 1, per_page: int = 50) -> dict[str, Any]:
        files, total = self._require_dbm().get_regular_files_paginated(user_id, page, per_page)
        return {
            "files": [_clean(f) for f in (files or [])],
            "total": int(total or 0),
            "page": page,
            "per_page": per_page,
        }

    def search_code(
        self, user_id: int, *, query: str, language: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self._require_dbm().search_code(
            user_id, query, programming_language=language, limit=limit
        )
        return [_clean(r) for r in (rows or [])]

    def get_file(
        self,
        user_id: int,
        *,
        file_name: str | None = None,
        file_id: str | None = None,
        version: int | None = None,
        lines: Any = None,
        query: Any = None,
        context_lines: int | None = None,
        max_results: int | None = None,
    ) -> dict[str, Any] | None:
        # שני מצבי קריאה שאינם מצטברים, ושניהם נבדקים **לפני** הקריאה למסד:
        # שאילתה פסולה לא צריכה לשלם טעינת מסמך שלם רק כדי להיפסל בסוף. זו
        # אותה החלטה ואותו מיקום כמו ``outline_and_lines`` ב-``repo_backend``,
        # והיא יושבת ב-backend ולא ב-``handlers`` כדי שגם קורא שאינו עובר דרך
        # שכבת ה-handlers יקבל את הסירוב ולא התעלמות שקטה מאחד הפרמטרים.
        request_error = file_query_request_error(
            query=query, lines=lines, context_lines=context_lines, max_results=max_results
        )
        if request_error:
            return {"ok": False, "error": request_error}
        dbm = self._require_dbm()
        if file_id:
            doc = dbm.get_file_by_id(file_id)
            # get_file_by_id is NOT user-scoped -> enforce ownership explicitly.
            if not doc or int(doc.get("user_id", -1)) != int(user_id):
                return None
        elif file_name and version is not None:
            doc = dbm.get_version(user_id, file_name, int(version))
        elif file_name:
            # טרי במכוון: edit_file/append_file בונים על התוכן הזה, וקריאה
            # מקאש הופכת אותם לעריכה על גבי גרסה ישנה.
            doc = _latest_fresh(dbm, user_id, file_name)
        else:
            return None
        if not doc:
            return None
        out = _full(doc)
        if query is not None:
            return _apply_query_to_file(
                out,
                query,
                context_lines=0 if context_lines is None else context_lines,
                max_results=QUERY_RESULTS_DEFAULT if max_results is None else max_results,
            )
        if lines is None:
            return out
        return _apply_range_to_file(out, lines)

    def file_exists(self, user_id: int, *, file_name: str) -> bool | None:
        """Does the user already have a file by this name?

        A projected query, not ``get_file``: existence is a yes/no question and
        loading the whole document — content included — to answer it costs the
        full file on every save.

        **The contract:** ``True``/``False`` when the answer is known, and
        ``None`` when it could not be determined. The distinction is not
        cosmetic. ``False`` on a failed lookup reads as "no such file", so the
        caller writes under a name that may well be taken — burying the existing
        content at exactly the moment the guard was meant to fire.

        **Only a query this method owns can answer it.** There is deliberately
        no ``get_file`` fallback: that path ends at
        ``Repository._fetch_latest_version``, which catches its own failures and
        returns ``None`` — the very conflation this contract exists to remove.
        Reading it as "no such file" would put the ambiguity back one layer
        down. No raw handle therefore means ``None``, not ``False``. Production
        never reaches that branch anyway: ``mcp_server.app.create_app`` refuses
        to start without Mongo and always passes ``mongo_db``.

        ``is_active: True`` is part of the question, not an oversight: a name
        sitting in the trash does **not** block a save. Reusing the name of a
        discarded file is allowed, and the version numbering already spans the
        trash so the new document cannot collide with it.

        Same shape as :func:`sticky_notes_target.repo_file_exists`, down to the
        ``{"_id": 1}`` projection and the ``None``-on-failure contract — and its
        caller treats ``None`` the same way, refusing to write rather than
        reading a failed lookup as permission.
        """
        try:
            coll = self._raw_mongo()["code_snippets"]
        except Exception:
            return None
        try:
            doc = coll.find_one(
                {"user_id": int(user_id), "file_name": file_name, "is_active": True},
                {"_id": 1},
            )
        except Exception:
            return None
        return doc is not None

    def list_versions(self, user_id: int, *, file_name: str) -> list[dict[str, Any]]:
        """היסטוריית הגרסאות של קובץ, מטא-דאטה בלבד.

        ``version_created_at`` נגזר **לפני** ``_clean``, וזה לא סידור
        שרירותי: ``_clean`` ממיר ``_id`` למחרוזת ``id``, ואיתה נעלמת חותמת
        הזמן שבתוך ה-ObjectId — הנפילה האחורה למסמכים שנכתבו לפני שהשדה
        קיים. אחרי הניקוי כבר אין ממה לגזור.
        """
        out: list[dict[str, Any]] = []
        for raw in (self._require_dbm().get_all_versions(user_id, file_name) or []):
            cleaned = _clean(raw)
            cleaned["version_created_at"] = _json_safe(version_created_at(raw))
            out.append(cleaned)
        return out

    # -- agent primer ------------------------------------------------------
    def get_agent_instructions(self, user_id: int) -> str:
        """The free-text "instructions for the agent" the user edits in the webapp.

        Stored on ``user_preferences`` — the same per-user document the webapp
        already writes (``attention_settings`` et al.), so the two services share
        one collection instead of one calling the other over HTTP.
        """
        doc = self._raw_mongo()["user_preferences"].find_one(
            {"user_id": int(user_id)}, {"agent_instructions": 1, "_id": 0}
        )
        value = (doc or {}).get("agent_instructions")
        return value if isinstance(value, str) else ""

    def recent_files(self, user_id: int, *, limit: int = 3) -> list[dict[str, Any]]:
        """The last-saved file names + when. Deliberately a cheap query.

        NOT ``get_regular_files_paginated``: that one runs a two-stage ``$group``
        over every file the user owns plus a separate ``$count`` (repository.py)
        — far too heavy for an endpoint hit on every session start. This is a
        plain indexed ``find``: sorting by ``created_at`` lands exactly on the
        existing ``user_active_created_at_idx`` compound index, and since every
        save writes a NEW version document, ``created_at DESC`` *is* the true
        save order.

        Scans a small window and de-dupes by name in Python, because several
        consecutive versions of one file would otherwise fill all the slots.
        """
        want = max(int(limit or 0), 0)
        if not want:
            return []
        window = max(want * 7, 20)  # מרווח לגרסאות חוזרות של אותו קובץ
        out: list[dict[str, Any]] = []
        # ה-try עוטף גם את האיטרציה, ולא רק את בניית הקורסור: קורסור pymongo הוא
        # עצל, והשאילתה יוצאת לרשת רק כאן. AutoReconnect/ExecutionTimeout מגיעים
        # באיטרציה — לעטוף רק את ``find()`` היה משאיר בדיוק אותם בחוץ.
        try:
            rows = (
                self._raw_mongo()["code_snippets"]
                .find(
                    {"user_id": int(user_id), "is_active": True},
                    {"file_name": 1, "created_at": 1, "updated_at": 1, "_id": 0},
                )
                .sort("created_at", -1)
                .limit(window)
            )
            seen: set[str] = set()
            for row in rows:
                name = str((row or {}).get("file_name") or "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                saved_at = row.get("created_at") or row.get("updated_at")
                out.append({"file_name": name, "saved_at": saved_at})
                if len(out) >= want:
                    break
        except Exception:
            logger.warning("recent files lookup failed", exc_info=True)
            return []
        return out

    # -- write (save) ------------------------------------------------------
    def save_file(
        self,
        user_id: int,
        *,
        file_name: str,
        code: str,
        programming_language: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new file or append a new version of an existing one.

        Reuses the same write path the bot/webapp use (``save_code_snippet`` →
        append-only versioning, auto-computed ``file_size``/``lines_count``), so
        an update never overwrites: prior versions remain visible via
        ``list_versions``. Returns metadata only — the heavy ``code`` is never
        echoed back (Smart Projection).
        """
        from database.models import CodeSnippet  # lazy heavy import (see _require_dbm)

        dbm = self._require_dbm()
        # Captured before the save so we can report create vs. update honestly.
        prev = _latest_fresh(dbm, user_id, file_name)
        ok = bool(
            dbm.save_code_snippet(
                CodeSnippet(
                    user_id=int(user_id),
                    file_name=file_name,
                    code=code,
                    programming_language=programming_language,
                    description=description or "",
                    tags=list(tags or []),
                )
            )
        )
        if not ok:
            return {"ok": False, "error": "save_failed"}
        # Re-fetch so the returned version/size are the authoritative DB values.
        saved = _latest_fresh(dbm, user_id, file_name) or {}
        cleaned = _clean(saved)
        # רק אחרי שהשמירה הצליחה — ראו :meth:`_emit_push_event`.
        self._emit_push_event(
            user_id,
            file_name=file_name,
            file_id=str(cleaned.get("id") or ""),
            created=prev is None,
        )
        return {"ok": True, "created": prev is None, "file": cleaned}

    def update_file_description(
        self, user_id: int, *, file_name: str, description: str
    ) -> dict[str, Any]:
        """Set an existing file's ``description`` **without saving a new version**.

        Delegates straight to ``DatabaseManager.update_file_metadata``, which is
        the same path ``POST /api/file/<id>/quick-update`` in the webapp takes —
        the "quick description edit" the file page already offers. Nothing here
        re-implements the write; if the two ever have to diverge, that argument
        belongs in one function rather than in two copies of it.

        **No push event, unlike :meth:`save_file`.** The notification says an
        agent *saved a file*, and this neither creates a version nor touches the
        content. Firing it here would put a "file saved" notice on something the
        user would not recognise as a save. See ``docs/deployment/workers.rst``.

        No ``getattr`` probe on the manager, deliberately: a db manager without
        this method cannot serve the tool, and a silent fallback would answer
        "updated" for a write that never happened
        (``bugbot-rules/silent-fallback-to-worse-path.md``). It raises, and the
        test doubles carry the method instead.
        """
        return self._require_dbm().update_file_metadata(
            user_id, file_name=file_name, description=description
        )

    def _emit_push_event(
        self, user_id: int, *, file_name: str, file_id: str, created: bool
    ) -> None:
        """רושם אירוע התראה על שמירת קובץ, לאיסוף על ידי שולח הפוש של ה-WebApp.

        **נקרא רק אחרי ששמירה הצליחה.** רשומה שמתארת כתיבה ונכתבת גם במסלול
        שבו הכתיבה נכשלה היא רשומה שמשקרת, ואין קוד שגיאה שיתפוס את הפער.

        השליחה עצמה אינה קורית בתהליך הזה. ה-WebApp מריץ שולח יחיד תחת נעילת
        ``flock`` ומחזיק את מפתחות ה-VAPID; שליחה מכאן הייתה עוקפת את שניהם.
        מה שנכתב כאן הוא **בקשה** בתור, ולכן הפער בין הרישום לשליחה הוא
        התכנון ולא באג.

        ``user_id`` מגיע מהטוקן המאומת של הקריאה (‏``current_user_id``) ולעולם
        לא מארגומנט של הכלי — הוא קובע למי תישלח ההתראה.

        כשל ברישום **אינו מפיל את השמירה**: הקובץ כבר נשמר, וההתראה היא תוצר
        לוואי שלה. אבל הוא גם אינו שקט — בלי שורת הלוג, תור שהפסיק להתמלא
        נראה בדיוק כמו סוכן שלא כתב כלום.
        """
        if not _push_events_enabled():
            return
        try:
            self._raw_mongo()["push_events"].insert_one(
                {
                    "user_id": int(user_id),
                    "kind": "file_saved",
                    "file_name": file_name,
                    # ‏file_id ו-created נגזרים משתי קריאות שעוטפות את השמירה
                    # ומאתרות את הקובץ **לפי שמו**, לא לפי המזהה שנכתב. בשתי
                    # שמירות מקבילות לאותו שם, ``file_id`` יכול להצביע על
                    # הגרסה של הכותב האחר, ו-``created`` יכול לדווח "חדש" על
                    # עדכון. שתיהן גרסאות של אותו קובץ ושל אותו משתמש, ולכן
                    # הקישור בהתראה עדיין נוחת במקום הנכון והנזק הוא בכותרת.
                    #
                    # אין לזה תיקון בשכבה הזו: ``save_code_snippet`` מחזיר
                    # ‏bool בלבד ואינו מוסר את המזהה שנכתב, כך שהאטומיות חייבת
                    # לבוא משכבת המסד. ‏``save_file`` כבר מחזיר את שני הערכים
                    # האלה ללקוח ה-MCP עם אותה חשיפה בדיוק — ההתראה אינה
                    # מוסיפה אותה, והתיקון שייך שם ולא כאן.
                    "file_id": file_id,
                    "created": bool(created),
                    "created_at": _dt.datetime.now(_dt.timezone.utc),
                    "needs_push": True,
                }
            )
        except Exception:
            logger.warning("push event insert failed", exc_info=True)

    # -- collections -------------------------------------------------------
    def list_collections(self, user_id: int, *, limit: int = 100) -> dict[str, Any]:
        return self._collections().list_collections(user_id, limit=limit)

    def get_collection(self, user_id: int, *, collection_id: str) -> dict[str, Any]:
        return self._collections().get_collection(user_id, collection_id)

    def get_collection_items(
        self,
        user_id: int,
        *,
        collection_id: str,
        page: int = 1,
        per_page: int = 50,
        folder: str | None = None,
    ) -> dict[str, Any]:
        result = self._collections().get_collection_items(
            user_id, collection_id, page=page, per_page=per_page, folder_filter=folder
        )
        # Defense-in-depth: collection items are file *references* (no code today),
        # but never let a heavy content field slip through if the manager changes.
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            result["items"] = [_strip_heavy(item) for item in result["items"]]
        return result

    # -- sticky notes ------------------------------------------------------
    def _raw_mongo(self) -> Any:
        mongo = self._mongo if self._mongo is not None else getattr(self._require_dbm(), "db", None)
        if mongo is None:
            raise RuntimeError("MongoDB handle unavailable for sticky notes")
        return mongo

    def _notes_coll(self) -> Any:
        coll = self._raw_mongo()["sticky_notes"]
        # **כל אינדקסי השאילתה, לא רק זה של ה-scope.** ה-MCP הוא כותב מלא
        # של פתקים — קובץ, לוח, וקובץ בריפו — ובנה עד היום אינדקס אחד.
        # פריסה שבה הוא רץ בלי הוובאפ הותירה כל שאילתת לוח וריפו בסריקת
        # אוסף.
        #
        # **המפרטים זהים בייט-לבייט לאלה שבוובאפ** (``_ensure_indexes``):
        # מונגו דוחה ב-code 85/86 אינדקס בשם קיים עם מפתחות אחרים, כלומר
        # סטייה של תו אחד הופכת את הבוטסטראפ השני לכשל שקט לצמיתות.
        # חד-פעמי, ולא מפיל כלי.
        # **הדגל נקבע אחרי הלולאה ותחת נעילה, ולא לפניה.** קודם הוא נקבע
        # ראשון, ולכן קורא מקביל שנכנס באמצע היה מדלג על הבנייה וממשיך
        # לשאילתה בלי שהאינדקס קיים — חלון שנפתח כשגופי הכלים ירדו מלולאת
        # האירועים ב-#3379, וקודם לכן הלולאה מנעה אותו. הנעילה מונעת גם את
        # הריצה הכפולה של ה-``create_index``.
        #
        # מה שלא השתנה, ובכוונה: כשל ביצירת אינדקס נרשם ואינו נבנה שוב
        # בתהליך הזה. זו התנהגות קיימת, ושינוי שלה הוא החלטה בפני עצמה.
        if not self._notes_idx_done:
            with self._lazy_lock:
                if not self._notes_idx_done:
                    for keys, name in (
                        ([("user_id", 1), ("scope_id", 1)], "user_scope_idx"),
                        ([("user_id", 1), ("board_id", 1)], "user_board_idx"),
                        ([("user_id", 1), ("repo_name", 1), ("repo_path", 1)], "user_repo_idx"),
                        # חיפוש לפי שם חוצה את שלושת היעדים, ולכן אינו יכול
                        # להישען על אף אחד משני האינדקסים הייחודיים:
                        # ה-``partialFilter`` שלהם דורש ``board_id``, או
                        # ``repo_name`` **וגם** ``repo_path`` — פרדיקטים
                        # שהחיפוש אינו נושא.
                        ([("user_id", 1), ("title", 1)], "user_title_idx"),
                        # **האינדקס שהחיפוש כאן באמת צריך.** ``search_notes``
                        # ממיין ב-``updated_at`` יורד, ו-``explain`` על
                        # השאילתה הזו הראה שמונגו בוחרת ב-``updated_desc``
                        # ולכן סורקת את הפתקים של **כל** המשתמשים. כאן ולא
                        # רק בוובאפ, כי זה החיפוש שרץ, ופריסה של ה-MCP בלי
                        # הוובאפ הייתה משאירה אותו בסריקה החוצה.
                        ([("user_id", 1), ("updated_at", -1)], "user_updated_idx"),
                    ):
                        try:
                            coll.create_index(keys, name=name)
                        except Exception:
                            logger.warning(
                                "sticky notes index %s creation failed (non-fatal)",
                                name,
                                exc_info=True,
                            )
                    self._notes_idx_done = True
        # ``create_board_note`` מחזיר ``duplicate_title`` על סמך דחייה של
        # המסד. אם האינדקס אינו שם — והוא נוצר עד היום רק בוובאפ — ההבטחה
        # ריקה. פריסה של ה-MCP בלי הוובאפ היא בדיוק המקרה הזה.
        #
        # **הבנייה אינה חד-פעמית כמו השכנה שמעל.** דגל "ניסינו" שנדלק לפני
        # הניסיון הופך כשל חולף אחד — נפילת רשת בעליית התהליך — לתהליך שלם
        # שרץ בלי אכיפה עד שיופעל מחדש. כאן מנסים שוב, עם השהיה, עד שהאינדקס
        # מאומת בקריאה חוזרת.
        self._ensure_title_index(coll)
        return coll

    #: כמה להמתין בין ניסיונות בנייה כושלים, בשניות
    _TITLE_INDEX_RETRY_SECONDS = 60.0

    def _ensure_note_index(
        self, coll: Any, which: _NoteIndex, builder: Callable[[Any], bool]
    ) -> bool:
        """המנוע המשותף לשני אינדקסי השם. מחזיר האם האילוץ **חי** כרגע.

        לכל אינדקס :class:`_IndexGate` משלו, כלומר זוג דגלים **עצמאי**. זה
        לא סגנון: דגל משותף היה נותן לכשל של האחד לחסום את הניסיון של
        השני, ולהצלחה של האחד להדליק אכיפה שלא אומתה עבור השני — כלומר
        ``duplicate_title`` שמובטח ולא קיים.

        **הזהות היא ``_NoteIndex`` והבנאי הוא פונקציה**, ולא שמות
        מחרוזתיים שנפתרים ב-``getattr``. ההבדל אינו קוסמטי: שם מוטעה של
        דגל היה נקרא כ-``False`` לתמיד, כלומר האינדקס היה נבנה מחדש בכל
        קירור — דרדור שקט לכל חיי התהליך במקום שגיאת תכנות. עכשיו טעות
        בשם היא ``NameError`` באתר הקריאה.
        """
        gates = self.__dict__.setdefault("_note_index_gates", {})
        gate = gates.get(which)
        if gate is None:
            gate = gates[which] = _IndexGate()

        if gate.ok:
            return True
        now = _time.monotonic()
        if now < gate.retry_at:
            return False
        gate.retry_at = now + self._TITLE_INDEX_RETRY_SECONDS
        try:
            gate.ok = bool(builder(coll))
        except Exception:
            gate.ok = False
            logger.error("%s index creation failed", which.value, exc_info=True)
        if not gate.ok:
            logger.error("%s index not confirmed — falling back to a code check", which.value)
        return gate.ok

    def _ensure_title_index(self, coll: Any) -> bool:
        """בונה ומאמת את אינדקס שם-פתק-בלוח. מחזיר האם האילוץ **חי** כרגע."""
        from sticky_notes_target import ensure_title_index

        return self._ensure_note_index(coll, _NoteIndex.BOARD_TITLE, ensure_title_index)

    def _ensure_repo_title_index(self, coll: Any) -> bool:
        """אח מקביל לפתקי ריפו — "שם אחד לכל קובץ בריפו".

        **אינו נקרא מ-**``_notes_coll``, אלא מ-``create_repo_note`` בלבד:
        ההבטחה ``duplicate_title`` נאמרת רק במסלול הכתיבה, ולכן רק הוא
        משלם על אימותה. אינדקס הלוח, לעומתו, עדיין נבנה מ-``_notes_coll``
        גם במסלולי קריאה — חוב קיים שקדם ל-PR הזה ולא נגרר לכאן.
        """
        from sticky_notes_target import ensure_repo_title_index

        return self._ensure_note_index(coll, _NoteIndex.REPO_TITLE, ensure_repo_title_index)

    # -- מסלול היצירה המשותף ---------------------------------------------
    #
    # שני החלקים שמתחת חולצו כי **סטייה בהם עולה באכיפה, לא בסגנון.** זה
    # בדיוק סוג הכשל שה-PR הזה תיקן במקום אחר: אכיפה שקיימת אצל כותב אחד
    # ולא אצל השני. תקרה שתשתנה במסלול הלוח ולא במסלול הריפו — או ברירת
    # מחדל ויזואלית שתיפרד — היא באג שאיש לא רואה.
    #
    # ``create_note`` (פתק על קובץ) **לא נגרר לכאן במכוון**: היעד שלו אינו
    # נבנה דרך ``build_note_target``, והתקרה שלו היא soft-cap שמעביר על
    # כשל ספירה — שתי החלטות שונות מהותית. איחוד היה מסתיר את ההבדל
    # במקום לתעד אותו.

    def _enforce_note_quotas(self, coll: Any, specs: Any) -> dict[str, Any] | None:
        """בודק את התקרות לפי הסדר. מחזיר מילון שגיאה, או ``None`` אם עברו.

        ``specs`` הוא רצף של ``(query, cap, exempt)``. **``exempt`` הוא
        פר-תקרה ולא פר-קריאה** — מדיניות הפטור אינה תכונה של הקורא אלא של
        התקרה עצמה, וכל מסלול יצירה מצהיר עליה בעצמו. הפונקציה הזו אינה
        קובעת אותה ואינה מניחה עליה דבר.

        (ולמה זה נדרש: התקרה ללוח פטורה לאדמין, והתקרה לקובץ בריפו נאכפת
        עליו — התקרה השנייה שומרת על צורת התוכן ולא על משאבים. שתי
        המדיניות חיות זו לצד זו, ולכן דגל יחיד לכל הקריאה לא היה מספיק.)

        **כשל ספירה דוחה.** תקרה שנפתחת לרווחה בדיוק כשהמסד מתקשה אינה
        תקרה. הקוד המוחזר נגזר מ**מצב הספירה** ולא מטקסט החריגה — טקסט של
        חריגה בתשובה הוא דלף ממתין.

        **ידוע ולא מטופל כאן:** בין הספירה ל-``insert_one`` יש חלון שבו שתי
        בקשות מקבילות עוברות.

        זו הכרעה, לא השמטה. ``webapp/sticky_notes_api`` אוכף את אותן תקרות
        באותו רצף ``count_documents`` → ``check_note_quota`` → ``insert_one``,
        ולכן אטומיות שתתווסף כאן בלבד תיצור **פער בין הכותבים** — בדיוק
        סוג הבאג שמנגנון האינדקסים המשותף נבנה כדי לסגור.

        ולמונגו אין דרך להביע "לכל היותר N מסמכים שתואמים לפילטר": תיקון
        אמיתי הוא מונה אטומי או reservation, כלומר **מצב חדש** — מסמך מונה
        לכל (משתמש, משטח), backfill לקיימים, הפחתה מפצה בכל מחיקת פתק,
        ויישוב כשהמונה נסחף. הריפו גם אינו משתמש בטרנזקציות בשום מקום, כך
        שהחלופה הטרנזקציונית מניחה replica set שלא אומת. זה שינוי חוצה-
        שירותים בפני עצמו, לא פרט מימוש של יעד פתק חדש.
        """
        from sticky_notes_target import NoteQuotaError, check_note_quota

        for query, cap, exempt in specs:
            try:
                existing: int | None = int(coll.count_documents(query))
            except Exception:
                existing = None  # ``None`` = "לא ידוע", ו-check_note_quota דוחה עליו
            try:
                check_note_quota(existing, cap, is_admin=exempt)
            except NoteQuotaError:
                code = "note_quota_unknown" if existing is None else "too_many_notes"
                return {"ok": False, "error": code, "max": cap, "count": existing}
        return None

    @staticmethod
    def _new_note_doc(
        user_id: int, *, target: dict[str, Any], content: str, color: str, mode: str, title: str
    ) -> dict[str, Any]:
        """שלד פתק חדש — ברירות המחדל הוויזואליות במקום אחד.

        ``target`` מגיע מ-``build_note_target``, שמריץ את האילוץ "בדיוק יעד
        אחד" **לפני** שהוא מחזיר; לכן אי אפשר להרכיב כאן מסמך לא חוקי.

        שם ריק ← השדה כלל אינו נכתב. זה לא קוסמטי: האינדקס הייחודי משתמש
        ב-``partialFilterExpression`` עם ``$exists``, ולכן שני פתקים עם
        ``title: ""`` היו מתנגשים זה בזה.
        """
        now = _dt.datetime.now(_dt.timezone.utc)
        return {
            "user_id": int(user_id),
            **target,
            "content": content,
            **({"title": title} if title else {}),
            # ברירות מחדל בפריטת הקליינט — פתק מה-MCP נראה כמו פתק שנוצר ביד
            "position_x": 120,
            "position_y": 120,
            "width": 260,
            "height": 200,
            "color": color,
            "is_minimized": False,
            "mode": mode,
            "created_at": now,
            "updated_at": now,
        }

    def _related_file_ids(self, user_id: int, file_name: str) -> list[str]:
        """כל מזהי הגרסאות של השם הזה — לפריטת שאילתת הוובאפ (פתקי legacy בלי scope_id)."""
        try:
            rows = self._raw_mongo()["code_snippets"].find(
                {"user_id": int(user_id), "file_name": file_name}, {"_id": 1}
            )
            return [str(r["_id"]) for r in rows if r and r.get("_id") is not None]
        except Exception:
            logger.warning("related file ids lookup failed", exc_info=True)
            return []

    def list_notes(
        self, user_id: int, *, file_name: str, include_content: bool = True
    ) -> dict[str, Any]:
        """List notes for a file (pure read — no backfill, unlike the webapp GET).

        ``include_content=False`` מחזיר את השורות דרך :func:`_as_note_summary`
        — בלי הגוף, עם גודלו. **השאילתה עצמה אינה משתנה:** הגוף עדיין נקרא
        מהמסד ורק אינו נשלח ללקוח. מה שהפרמטר מקטין הוא התשובה, שהיא מה
        שחסם בפועל (לוח שלם חרג ממה שלקוח מציג); היטלה בגבול המסד — כמו
        שהחיפוש עושה — היא שינוי נפרד, ומדידת הגודל הייתה דורשת אז ביטוי
        אגרגציה שסוויטת הסטאבים אינה מריצה.
        """
        from sticky_notes_scope import make_scope_id  # מודול טהור בשורש הריפו

        scope_id = make_scope_id(int(user_id), file_name)
        related = self._related_file_ids(user_id, file_name)
        query = _notes_scope_filter(user_id, scope_id, related)
        rows = list(self._notes_coll().find(query).sort("created_at", 1).limit(500))
        serialize = _as_note if include_content else _as_note_summary
        return {
            "ok": True,
            "file_name": file_name,
            "count": len(rows),
            "notes": [serialize(r) for r in rows],
        }

    def create_note(
        self,
        user_id: int,
        *,
        file_name: str,
        content: str,
        line: int | None,
        color: str,
        anchor_text: str | None,
        anchor_id: str | None,
    ) -> dict[str, Any]:
        """Insert a webapp-schema note attached to an existing file."""
        from .handlers import MAX_NOTES_PER_SCOPE
        from sticky_notes_scope import make_scope_id

        doc = self._require_dbm().get_latest_version(int(user_id), file_name)
        if not doc:
            return {
                "ok": False,
                "error": "file_not_found",
                "hint": "save the file first with codekeeper_save_file",
            }
        canonical_name = str(doc.get("file_name") or file_name)
        scope_id = make_scope_id(int(user_id), canonical_name)
        related = self._related_file_ids(user_id, canonical_name)

        coll = self._notes_coll()
        try:
            existing = int(coll.count_documents(_notes_scope_filter(user_id, scope_id, related)))
        except Exception:
            existing = 0  # המגן הוא soft-cap; כשל ספירה לא חוסם יצירה
        if existing >= MAX_NOTES_PER_SCOPE:
            return {
                "ok": False,
                "error": "too_many_notes",
                "max": MAX_NOTES_PER_SCOPE,
                "count": existing,
            }

        now = _dt.datetime.now(_dt.timezone.utc)
        note = {
            "user_id": int(user_id),
            "file_id": str(doc.get("_id") or ""),
            "content": content,
            # ברירות מחדל בפריטת הקליינט — פתק מה-MCP נראה כמו פתק שנוצר ביד
            "position_x": 120,
            "position_y": 120,
            "width": 260,
            "height": 200,
            "color": color,
            "is_minimized": False,
            "line_start": line,
            "line_end": None,
            "anchor_id": anchor_id,
            "anchor_text": anchor_text,
            "scope_id": scope_id,
            "file_name": canonical_name,
            "created_at": now,
            "updated_at": now,
        }
        res = coll.insert_one(note)
        note["_id"] = getattr(res, "inserted_id", None)
        return {"ok": True, "note": _as_note(note)}

    # -- note boards -------------------------------------------------------
    #
    # הלוחות הם משטח שני לאותם פתקים, ולכן כל מה שכאן נשען על אותם מודולים
    # טהורים שהוובאפ משתמש בהם — ``note_boards`` ו-``sticky_notes_target``.
    # אין כאן לוגיקה חדשה, רק חיווט: כלל שמופיע פעמיים מתפצל בסוף.

    def _boards_coll(self) -> Any:
        return self._raw_mongo()["note_boards"]

    def _owned_board(self, user_id: int, board_id: str) -> dict[str, Any] | None:
        """הלוח, אם הוא של המשתמש. אחרת ``None``.

        **בעלות נבדקת לפני כל נגיעה בפתקים.** בלי זה ``board_id`` שרירותי
        היה מחזיר את הפתקים של מישהו אחר — הפילטר על ``user_id`` בשאילתת
        הפתקים מגן, אבל הסתמכות על הגנה במורד הזרם היא בדיוק סוג ההנחה
        שנשברת כשמישהו משנה את השאילתה.
        """
        from bson import ObjectId  # lazy heavy import

        try:
            oid = ObjectId(str(board_id))
        except Exception:
            return None
        doc = self._boards_coll().find_one({"_id": oid, "user_id": int(user_id)})
        return doc if isinstance(doc, dict) else None

    @staticmethod
    def _canonical_board_id(board: dict[str, Any]) -> str:
        """המזהה **כפי שהמסד מחזיק אותו**, ולא כפי שהקורא הקליד.

        ``ObjectId`` מקבל גם הקסה גדולה, אבל ``str(ObjectId)`` תמיד קטנה —
        וזה מה שהוובאפ שומר ומחפש לפיו. פתק שנוצר עם ``6A88...`` נשמר
        באותיות גדולות ו**נעלם מהלוח**: הוובאפ מחפש ``6a88...`` ולא מוצא
        כלום. שוחזר מול מונגו אמיתי לפני התיקון.
        """
        return str(board.get("_id"))

    def list_boards(self, user_id: int) -> dict[str, Any]:
        """לוחות המשתמש, עם מונה פתקים. יוצר את לוח ברירת המחדל אם אין."""
        from note_boards import ensure_default_board, list_boards as _list

        db = self._raw_mongo()
        # רשימה חלקית עדיפה על כלי שנופל — אבל כשל שקט כאן פירושו שמשתמש
        # נשאר בלי לוח ברירת מחדל ואיש לא ידע. מדווחים ללוג וגם בתשובה.
        default_board_error: str | None = None
        try:
            ensure_default_board(db, int(user_id))
        except Exception as exc:
            default_board_error = type(exc).__name__
            logger.warning(
                "ensure_default_board failed for user %s: %s", user_id, type(exc).__name__
            )
        rows = _list(db, int(user_id))

        # ``None`` = הספירה נכשלה ואיננו יודעים. ``0`` = ידוע שהלוח ריק.
        # ערבוב השניים הוא בדיוק הכשל שנמנע בוובאפ: "לא זמין" שנראה כמו
        # "ריק" גורם למשתמש להאמין שאיבד פתקים.
        counts: dict[str, int] | None = {}
        try:
            for row in self._notes_coll().aggregate([
                {"$match": {"user_id": int(user_id), "board_id": {"$in": [str(r.get("_id")) for r in rows]}}},
                {"$group": {"_id": "$board_id", "n": {"$sum": 1}}},
            ]):
                counts[str(row.get("_id"))] = int(row.get("n") or 0)
        except Exception:
            counts = None  # לא ידוע — ולא אפס

        boards = [
            {
                "id": str(b.get("_id")),
                "name": str(b.get("name") or ""),
                "is_default": bool(b.get("is_default")),
                "note_count": None if counts is None else counts.get(str(b.get("_id")), 0),
            }
            for b in rows
        ]
        out: dict[str, Any] = {"ok": True, "count": len(boards), "boards": boards}
        if default_board_error:
            out["default_board_error"] = default_board_error
        return out

    def list_board_notes(
        self, user_id: int, *, board_id: str, include_content: bool = True
    ) -> dict[str, Any]:
        """פתקי לוח יחיד (קריאה טהורה).

        ``include_content=False`` — אותה הכרעה בדיוק כמו ב-:meth:`list_notes`:
        השורות עוברות דרך :func:`_as_note_summary`, והשאילתה אינה משתנה.
        """
        from sticky_notes_target import board_notes_filter

        board = self._owned_board(user_id, board_id)
        if board is None:
            return {"ok": False, "error": "board_not_found"}

        canonical = self._canonical_board_id(board)
        query = board_notes_filter(int(user_id), canonical)
        rows = list(self._notes_coll().find(query).sort("created_at", 1).limit(500))
        serialize = _as_note if include_content else _as_note_summary
        return {
            "ok": True,
            "board_id": canonical,
            "board_name": str(board.get("name") or ""),
            "count": len(rows),
            "notes": [serialize(r) for r in rows],
        }

    def create_board_note(
        self,
        user_id: int,
        *,
        board_id: str,
        content: str,
        color: str,
        mode: str,
        title: str = "",
    ) -> dict[str, Any]:
        """פתק חדש על לוח.

        התקרה נאכפת ב-``check_note_quota``, שדוחה גם כשהספירה **נכשלה**.
        זו סטייה מכוונת מ-``create_note`` של הקובץ, שם כשל ספירה מעביר את
        היצירה (soft-cap). תקרה שנפתחת לרווחה בדיוק כשהמסד מתקשה היא לא
        תקרה — והוובאפ כבר מתנהג כך בפתקי לוח.
        """
        from sticky_notes_target import (
            MAX_NOTES_PER_BOARD,
            MAX_NOTES_PER_USER,
            board_notes_filter,
            build_note_target,
        )

        board = self._owned_board(user_id, board_id)
        if board is None:
            return {"ok": False, "error": "board_not_found"}

        # פטור אדמין — אותה החלטה שכבר נאכפת בוובאפ. בלעדיו אותו משתמש
        # פטור דרך הדפדפן ונחסם דרך MCP, וזו הפתעה ולא מדיניות.
        try:
            from user_roles import is_admin
            is_admin_user = bool(is_admin(int(user_id)))
        except Exception:
            is_admin_user = False  # ספק ← לא פטור

        canonical = self._canonical_board_id(board)
        coll = self._notes_coll()
        # התקרה ללוח פטורה לאדמין, בדיוק כמו התקרה למשתמש — בשונה מהתקרה
        # לקובץ בריפו, שנאכפת על כולם.
        denied = self._enforce_note_quotas(coll, (
            (board_notes_filter(int(user_id), canonical), MAX_NOTES_PER_BOARD, is_admin_user),
            ({"user_id": int(user_id)}, MAX_NOTES_PER_USER, is_admin_user),
        ))
        if denied is not None:
            return denied

        note = self._new_note_doc(
            user_id,
            target=build_note_target(board_id=canonical),
            content=content,
            color=color,
            mode=mode,
            title=title,
        )
        # גיבוי לאכיפה כשהאינדקס לא אומת. במצב התקין ``_ensure_title_index``
        # מחזירה True מיד, ואין כאן שום שאילתה נוספת.
        if title and not self._ensure_title_index(coll):
            from sticky_notes_target import title_is_taken

            if title_is_taken(coll, user_id=int(user_id), board_id=canonical, title=title):
                return {"ok": False, "error": "duplicate_title"}

        try:
            res = coll.insert_one(note)
        except _DuplicateKeyError:
            # שם תפוס בלוח — התנגשות ולא תקלה. נתפס לפי **הטיפוס** ולא לפי
            # שם המחלקה: השוואת מחרוזת הייתה נשענת על שם שהדרייבר חופשי
            # לשנות, והייתה תופסת גם כל חריגה זרה שבמקרה נקראת כך. תפיסה
            # לפי טיפוס מכסה גם תת-מחלקות. (חריגה **עוטפת** — כזו שמחזיקה
            # DuplicateKeyError בתוכה — אינה נתפסת כאן בשום שיטה, וגם
            # ההשוואה לשם לא הייתה תופסת אותה.)
            return {"ok": False, "error": "duplicate_title"}
        note["_id"] = getattr(res, "inserted_id", None)
        return {"ok": True, "note": _as_note(note)}

    # -- פתקי ריפו: היעד השלישי ------------------------------------------
    def list_repo_notes(self, user_id: int, *, repo_name: str, repo_path: str) -> dict[str, Any]:
        """פתקים על קובץ בריפו ממורר (קריאה טהורה).

        **סימון היתומים נעשה בקריאה, ואינו מסתיר דבר.** ``orphaned`` נדלק
        **רק** כש-``repo_file_exists`` החזיר ``False`` מפורש; ``None``
        פירושו "השאילתה נכשלה", וקריאה כזו לעולם אינה מסמנת קובץ חי
        כמיותם. הפתקים עצמם מוחזרים בכל מקרה — קובץ שנמחק מהריפו אינו
        סיבה להעלים את מה שנכתב עליו.

        **בלי ``try/except`` סביב השאילתה**, בדיוק כמו ב-``list_board_notes``:
        רשימה ריקה על שאילתה שנכשלה נראית כמו "אין פתקים", וזה בדיוק הכשל
        שדורס קאש ומוליך את הקורא למסקנה הפוכה.
        """
        from sticky_notes_target import normalize_repo_path, repo_notes_filter

        clean_repo = str(repo_name or "")
        clean_path = normalize_repo_path(repo_path)
        query = repo_notes_filter(int(user_id), clean_repo, clean_path)
        rows = list(self._notes_coll().find(query).sort("created_at", 1).limit(500))

        out: dict[str, Any] = {
            "ok": True,
            "repo_name": clean_repo,
            "repo_path": clean_path,
            "count": len(rows),
            "notes": [_as_note(r) for r in rows],
        }
        if self.repo_path_orphaned(repo_name=clean_repo, repo_path=clean_path):
            out["orphaned"] = True
        return out

    def repo_path_orphaned(self, *, repo_name: str, repo_path: str) -> bool:
        """האם נתיב של פתק ריפו כבר אינו בעץ המשוקף — הכלל היחיד של "מיותם".

        ``True`` **רק** כש-``repo_file_exists`` החזיר ``False`` מפורש. ``None``
        פירושו "השאילתה נכשלה", וקריאה כזו לעולם אינה מסמנת קובץ חי כמיותם.
        משותף ל-:meth:`list_repo_notes` ול-``get_note``, כדי ששני הכלים לא
        יגזרו שני מושגים של יתמות מאותו מניפסט.
        """
        from sticky_notes_target import repo_file_exists

        exists = repo_file_exists(self._raw_mongo(), str(repo_name or ""), str(repo_path or ""))
        return exists is False

    def create_repo_note(
        self,
        user_id: int,
        *,
        repo_name: str,
        repo_path: str,
        content: str,
        color: str,
        mode: str,
        title: str = "",
    ) -> dict[str, Any]:
        """פתק חדש על קובץ בריפו ממורר.

        **שני השערים לפני התקרות הם fail-closed:** מניפסט שלא נענה מחזיר
        ``repo_list_unavailable``/``repo_file_unavailable`` ולא "לא קיים".
        ההבדל אינו סמנטי בלבד — "לא קיים" מזמין את הקורא לתקן את הנתיב,
        וזו עצה שגויה כשהמסד פשוט לא ענה.
        """
        from sticky_notes_target import (
            MAX_NOTES_PER_REPO_FILE,
            MAX_NOTES_PER_USER,
            build_note_target,
            mirrored_repo_names,
            normalize_repo_path,
            repo_file_exists,
            repo_notes_filter,
        )

        clean_repo = str(repo_name or "")
        clean_path = normalize_repo_path(repo_path)
        db = self._raw_mongo()

        known = mirrored_repo_names(db)
        if known is None:
            return {"ok": False, "error": "repo_list_unavailable"}
        if clean_repo not in known:
            return {"ok": False, "error": "repo_not_found", "repo_name": clean_repo}

        exists = repo_file_exists(db, clean_repo, clean_path)
        if exists is None:
            return {"ok": False, "error": "repo_file_unavailable"}
        if exists is False:
            return {"ok": False, "error": "repo_file_not_found", "repo_path": clean_path}

        try:
            from user_roles import is_admin
            is_admin_user = bool(is_admin(int(user_id)))
        except Exception:
            is_admin_user = False  # ספק ← לא פטור

        coll = self._notes_coll()
        # ה-``False`` בתקרה-לקובץ אינו שריד לניקוי:
        # :data:`MAX_NOTES_PER_REPO_FILE` נאכפת **גם על אדמין** (ראו
        # הדוקסטרינג שלה), וכל הקוראים למשטח הזה הם אדמינים — כלומר
        # "תיקון" ל-``is_admin_user`` היה הופך אותה לתקרה שאינה נאכפת על
        # איש. זה ההבדל היחיד מהמסלול של הלוח.
        denied = self._enforce_note_quotas(coll, (
            (repo_notes_filter(int(user_id), clean_repo, clean_path), MAX_NOTES_PER_REPO_FILE, False),
            ({"user_id": int(user_id)}, MAX_NOTES_PER_USER, is_admin_user),
        ))
        if denied is not None:
            return denied

        note = self._new_note_doc(
            user_id,
            target=build_note_target(repo_name=clean_repo, repo_path=clean_path),
            content=content,
            color=color,
            mode=mode,
            title=title,
        )
        # גיבוי לאכיפה כשהאינדקס לא אומת — אח מדויק לזה שב-``create_board_note``.
        #
        # **ולמה גיבוי ולא דחייה.** ההצעה החוזרת היא לדחות
        # ב-``title_index_unavailable`` כשהאינדקס אינו מאומת, כי בין
        # הבדיקה ל-``insert_one`` יש חלון TOCTOU. החלון אמיתי — אבל:
        #
        # 1. ``webapp/sticky_notes_api._repo_title_conflict`` עושה בדיוק את
        #    אותו גיבוי. דחייה כאן בלבד הייתה יוצרת פער בין הכותבים, וזה
        #    סוג הבאג שכל היעד הזה נבנה כדי לסגור.
        # 2. ``repo_title_is_taken`` מחזירה ``True`` על כשל שאילתה, ולכן
        #    בתקלת מסד היא כבר דוחה. מה שנשאר: אינדקס באמת חסר **וגם** שתי
        #    בקשות מקבילות עם אותו שם — והמחיר שני פתקים עם אותו שם.
        # 3. דחייה הופכת תקלת אינדקס חולפת להשבתה מלאה של פתקים עם שם.
        #
        # תיקון אמיתי הוא אכיפה אטומית, והיא חייבת לחול על **כל** הכותבים
        # במנגנון אחד. ראו ``_enforce_note_quotas`` לאותה הכרעה בתקרות.
        if title and not self._ensure_repo_title_index(coll):
            from sticky_notes_target import repo_title_is_taken

            if repo_title_is_taken(
                coll, user_id=int(user_id), repo_name=clean_repo,
                repo_path=clean_path, title=title,
            ):
                return {"ok": False, "error": "duplicate_title"}

        try:
            res = coll.insert_one(note)
        except _DuplicateKeyError:
            return {"ok": False, "error": "duplicate_title"}
        note["_id"] = getattr(res, "inserted_id", None)
        return {"ok": True, "note": _as_note(note)}

    def get_note(self, user_id: int, *, note_id: str) -> dict[str, Any]:
        """פתק בודד לפי מזהה, תחום לבעלות — **הקריאה-לפי-מזהה היחידה** של פתק.

        שני קוראים, ומסלול קריאה אחד: ``note_str_replace`` (עריכת מצא-והחלף
        היא read-modify-write, וכלי הרשימה מחייבים לדעת **איפה** הפתק יושב —
        בדיוק מה שהקורא אינו יודע כשיש בידו ``note_id`` בלבד), והכלי
        ``codekeeper_get_note``. הבעלות יושבת **במסנן** ולא בבדיקה אחריו,
        ולכן פתק של משתמש אחר הוא ``not_found`` — אותה תשובה כמו למזהה
        שאינו קיים, כדי שהסירוב לא יגלה שהמזהה תפוס.

        התשובה נושאת, לצד ``note`` (הסריאליזציה של :func:`_as_note`, שבה
        ``content`` עבר ``html.unescape`` כמו בכלי הרשימה), שני דברים שאין
        ב-``_as_note``:

        - **היעד**, בצורה של :func:`sticky_notes_target.note_target_ref` —
          ``target`` ואיתו בדיוק הארגומנטים של כלי הרשימה המתאים, אותה
          מוסכמה של פגיעת חיפוש. פתק קובץ ישן שנושא ``file_id`` בלבד מקבל
          ``file_name`` דרך :meth:`_backfill_file_names`, מאותה סיבה שהחיפוש
          עושה זאת: פגיעה בלי ``file_name`` היא מבוי סתום.
        - ``stored_content`` — הגוף **בדיוק כפי שהוא מאוחסן**, בלי פענוח
          ישויות. ``codekeeper_get_note`` מחזיר את זה ולא את הגוף המפוענח:
          ``get_note_version`` מחזיר גרסאות קודמות בצורה המאוחסנת, ורק כך
          "הגוף של גרסה N" ו"הגוף הנוכחי" ניתנים להשוואה בית-בית.
          ``note_str_replace`` ממשיך לעבוד על ``note["content"]`` המפוענח,
          כי הוא מפענח גם את ``old_string`` (``_sanitize_note_text``) ומשווה
          במרחב אחד — שתי הצורות מגיעות אליו ותופסות.
        """
        from bson import ObjectId  # lazy heavy import
        from sticky_notes_target import note_target_ref

        try:
            oid = ObjectId(str(note_id))
        except Exception:
            return {"ok": False, "error": "invalid_note_id"}
        row = self._notes_coll().find_one({"_id": oid, "user_id": int(user_id)})
        if not row:
            return {"ok": False, "error": "not_found"}
        self._backfill_file_names(int(user_id), [row])
        return {
            "ok": True,
            "note": _as_note(row),
            "stored_content": _json_safe(row.get("content")),
            **_json_safe(note_target_ref(row)),
        }

    def current_note_version(self, user_id: int, *, note_id: str) -> int:
        """מספר הגרסה של הגוף **הנוכחי** — המספר שהוא יקבל בהיסטוריה כשיידרס.

        אותו חישוב בדיוק שבו :meth:`_snapshot_note` בוחר מספר לגוף שהוא
        מצלם (:meth:`_next_note_version`), ולא עותק שלו: לכן
        ``get_note_version`` עם המספר הזה יחזיר, אחרי הדריסה הבאה, בדיוק את
        מה ש-``get_note`` מחזיר עכשיו. ``1`` לפתק שמעולם לא נדרס דרך השרת
        הזה. ההיסטוריה נכתבת רק ב-:meth:`update_note`, כלומר עריכה מהוובאפ
        אינה מזיזה את המספר — הוא סופר דריסות דרך ה-MCP.

        כשל שאילתה עולה הלאה, כמו בכל קריאה כאן: ``None`` שנראה כמו "אין
        היסטוריה" הוא בדיוק המסלול החלופי השקט שאסור לפתוח.
        """
        return self._next_note_version(self._note_versions_coll(), int(user_id), str(note_id))

    @staticmethod
    def _next_note_version(coll: Any, user_id: int, note_id: str) -> int:
        """המספר שהצילום הבא של הפתק יקבל: הגרסה החדשה ביותר ועוד אחת.

        המקור היחיד לחשבון הזה. :meth:`_snapshot_note` מצלם איתו,
        ו-:meth:`current_note_version` מדווח איתו — עותק שני היה נסחף בדיוק
        ביום שבו אחד מהם ישתנה.
        """
        prev = coll.find_one(
            {"user_id": int(user_id), "note_id": str(note_id)},
            {"version": 1},
            sort=[("version", -1)],
        )
        return int((prev or {}).get("version") or 0) + 1

    #: כמה גרסאות קודמות נשמרות לכל פתק.
    #:
    #: **מספר חדש שאין לו תקדים בריפו** — קבצים אינם חסומים בכלל. פתק הוא
    #: עד 20K תווים, ועד 1000 פתקים למשתמש; בלי תקרה, עריכה חוזרת של פתק
    #: אחד הייתה מייצרת צמיחה בלתי חסומה באוסף שנועד להיות רשת ביטחון.
    #: **ומכאן גם המגבלה שחייבת להיאמר:** אחרי 20 עריכות המקור נדחף
    #: החוצה, ולכן ``destructiveHint`` נשאר ``True``.
    NOTE_VERSION_RETENTION = 20

    def _ensure_versions_index(self, coll: Any) -> bool:
        """בונה ומאמת את האינדקס הייחודי של גרסאות הפתקים.

        ההחזרה היא **אימות בקריאה חוזרת**, לא ערך ההחזרה של הבנייה:
        ``create_index`` על אינדקס קיים בשם זהה מחזיר בשקט, ולכן רק
        ``index_information`` מעיד שהאילוץ באמת חי וייחודי.
        """
        coll.create_index(
            [("user_id", 1), ("note_id", 1), ("version", -1)],
            name="note_version_idx",
            unique=True,
        )
        spec = (coll.index_information() or {}).get("note_version_idx") or {}
        return bool(spec.get("unique"))

    def _note_versions_coll(self) -> Any:
        """אוסף גרסאות הפתקים, עם אכיפת אינדקס דרך מנוע ה-gate המשותף.

        **אוסף נפרד, ולא מערך מוטבע במסמך הפתק.** שלוש פונקציות הרשימה —
        ``list_notes``, ``list_board_notes`` ו-``list_repo_notes`` — עושות
        ``find(query)`` **בלי פרויקציה**, ולכן מערך היסטוריה מוטבע היה
        נגרר לתוך כל רשימת פתקים. זו הפרה של חוק ה-Smart Projection בשלושה
        מסלולים חמים בבת אחת, ובגודל שגדל עם כל עריכה.

        האינדקס הייחודי אינו קוסמטי: הוא מה שהופך מספר גרסה כפול משתי
        כתיבות מקבילות לשגיאה שנתפסת — ו-``_snapshot_note`` מתרגם אותה
        לניסיון חוזר עם המספר הבא. ולכן הבנייה עוברת דרך
        ``_ensure_note_index``, **לא** דרך דגל "ניסינו" חד-פעמי: דגל
        שנדלק לפני הניסיון הופך כשל רשת חולף אחד בעליית התהליך לתהליך
        שלם שכותב גרסאות בלי האילוץ שההבטחה נשענת עליו.
        """
        coll = self._raw_mongo()["sticky_note_versions"]
        self._ensure_note_index(coll, _NoteIndex.NOTE_VERSIONS, self._ensure_versions_index)
        return coll

    #: כמה פעמים לנסות שוב כששני צילומים מקבילים התנגשו על אותו מספר גרסה
    _SNAPSHOT_RETRIES = 3

    def _snapshot_note(
        self, user_id: int, note: dict[str, Any]
    ) -> tuple[bool, dict[str, Any] | None]:
        """שומר את התוכן הנוכחי של הפתק כגרסה קודמת.

        מחזיר ``(הצליח, ייחוס)``: הייחוס — ``{user_id, note_id, version}``
        — הוא מה שמאפשר לקורא **לפצות**: הצילום נכתב לפני הדריסה, ואם
        הדריסה אחריו לא קרתה (מחיקה מקבילה, קונפליקט, כשל כתיבה), גרסה
        שמתארת החלפה שלא התרחשה חייבת להימחק — אחרת ההיסטוריה מעידה על
        אירוע שלא היה, וכל ניסיון חוזר מוסיף כפילות.

        **ערך ההצלחה נבדק אצל הקורא, והוא אינו קישוט.** ``update_note``
        דורס במקום; אם הצילום נכשל ובכל זאת נדרוס, איבדנו את הפתק בשקט
        בדיוק כמו לפני התיקון — רק שהפעם הבטחנו למשתמש שיש רשת. לכן כשל
        כאן עוצר את העדכון.

        **התנגשות מספר גרסה אינה כשל.** שני צילומים מקבילים קוראים את
        אותו מקסימום ומנסים את אותו ``nxt``; האינדקס הייחודי דוחה את
        השני, וכאן זה מתורגם לקריאה חוזרת של המקסימום וניסיון עם המספר
        הבא — לא לדחיית העריכה כולה.
        """
        content = note.get("content")
        if not isinstance(content, str) or not content:
            # אין מה לצלם. זו הצלחה, לא כשל: פתק ריק אינו מידע שאפשר לאבד.
            return True, None
        coll = self._raw_mongo()["sticky_note_versions"]
        # **בלי אינדקס מאומת — אין צילום, ולכן אין עדכון.** כל ההבטחה
        # ("כפילות נתפסת ומתורגמת לניסיון חוזר") נשענת על האילוץ הייחודי;
        # צילום בלעדיו יכול לייצר שתי גרסאות עם אותו מספר, בשקט — היסטוריה
        # שקרית שמתחזה לרשת ביטחון. עצירה עד שה-gate מאשר (עם הניסיון
        # החוזר וההשהיה שלו) היא fail-closed, באותו היגיון שבו כשל צילום
        # עוצר את הדריסה. קריאות (רשימה/שליפה/גיזום) אינן חסומות — הן
        # אינן זקוקות לאילוץ.
        if not self._ensure_note_index(coll, _NoteIndex.NOTE_VERSIONS, self._ensure_versions_index):
            logger.error("note snapshot refused: unique version index unconfirmed")
            return False, None
        nid = str(note.get("_id"))
        for _attempt in range(self._SNAPSHOT_RETRIES):
            try:
                nxt = self._next_note_version(coll, int(user_id), nid)
                coll.insert_one(
                    {
                        "user_id": int(user_id),
                        "note_id": nid,
                        "version": nxt,
                        "content": content,
                        # האורך נשמר בכתיבה כדי שרשימת הגרסאות לא תצטרך
                        # לקרוא את הגוף (עד 20K תווים) רק כדי למדוד אותו.
                        "length": len(content),
                        "saved_at": _dt.datetime.now(_dt.timezone.utc),
                    }
                )
            except _DuplicateKeyError:
                continue  # צילום מקביל תפס את המספר — ננסה עם הבא
            except Exception:
                logger.error("note snapshot failed for %s", nid, exc_info=True)
                return False, None
            self._prune_note_versions(int(user_id), nid)
            return True, {"user_id": int(user_id), "note_id": nid, "version": nxt}
        logger.error("note snapshot for %s kept colliding on version numbers", nid)
        return False, None

    def _discard_snapshot(self, ref: dict[str, Any] | None) -> None:
        """מפצה על צילום שהדריסה אחריו לא קרתה. Best-effort.

        כשל כאן משאיר גרסה עודפת — עדות כוזבת קלה בהרבה מאובדן תוכן,
        ולכן אינו משנה את תשובת הקורא.
        """
        if not ref:
            return
        try:
            self._note_versions_coll().delete_one(dict(ref))
        except Exception:
            logger.warning("orphan snapshot cleanup failed: %s", ref, exc_info=True)

    def _prune_note_versions(self, user_id: int, note_id: str) -> None:
        """מוחק גרסאות מעבר ל-:data:`NOTE_VERSION_RETENTION` האחרונות.

        כשל בגיזום אינו מפיל את העדכון: התוצאה היא היסטוריה ארוכה מהתקרה,
        שהיא **עודף** מידע ולא חוסר. הכיוון ההפוך היה מצדיק עצירה.
        """
        try:
            coll = self._note_versions_coll()
            keep = list(
                coll.find({"user_id": int(user_id), "note_id": note_id}, {"version": 1})
                .sort("version", -1)
                .limit(int(self.NOTE_VERSION_RETENTION))
            )
            if len(keep) < int(self.NOTE_VERSION_RETENTION):
                return
            floor = int(keep[-1].get("version") or 0)
            coll.delete_many(
                {"user_id": int(user_id), "note_id": note_id, "version": {"$lt": floor}}
            )
        except Exception:
            logger.warning("note version prune failed for %s", note_id, exc_info=True)

    def list_note_versions(self, user_id: int, *, note_id: str) -> dict[str, Any]:
        """מטא-דאטה של הגרסאות הקודמות — **בלי תוכן**, כמו ``list_versions``.

        אינו נשען על קיום הפתק: היסטוריה של פתק שנמחק עדיין שייכת
        למשתמש, והבעלות נשמרת במסמך הגרסה עצמו.
        """
        # ``length`` נשמר בזמן הצילום בדיוק בשביל השורה הזו: פרויקציה בלי
        # ``content``, כדי שרשימת מטא-דאטה לא תגרור עד 20 גופים מלאים.
        rows = list(
            self._note_versions_coll()
            .find(
                {"user_id": int(user_id), "note_id": str(note_id)},
                {"version": 1, "saved_at": 1, "length": 1},
            )
            .sort("version", -1)
            .limit(int(self.NOTE_VERSION_RETENTION))
        )
        return {
            "ok": True,
            "note_id": str(note_id),
            "count": len(rows),
            "versions": [
                {
                    "version": int(r.get("version") or 0),
                    "saved_at": _json_safe(r.get("saved_at")),
                    "length": int(r.get("length") or 0),
                }
                for r in rows
            ],
        }

    def get_note_version(self, user_id: int, *, note_id: str, version: int) -> dict[str, Any]:
        """תוכן של גרסה קודמת אחת — המקבילה ל-``get_file(version=)``."""
        row = self._note_versions_coll().find_one(
            {"user_id": int(user_id), "note_id": str(note_id), "version": int(version)}
        )
        if not row:
            return {"ok": False, "error": "version_not_found"}
        return {
            "ok": True,
            "note_id": str(note_id),
            "version": int(row.get("version") or 0),
            "saved_at": _json_safe(row.get("saved_at")),
            "content": str(row.get("content") or ""),
        }

    def list_repo_note_paths(self, user_id: int, *, repo_name: str) -> dict[str, Any]:
        """הנתיבים בריפו שיש עליהם פתקים, עם ספירה — מפת גילוי.

        בלי זה ``list_repo_notes`` דורש לדעת את הנתיב המדויק מראש, כלומר
        צריך לדעת איפה הפתק כדי למצוא אותו.
        """
        from sticky_notes_target import repo_note_paths_pipeline

        rows = list(self._notes_coll().aggregate(repo_note_paths_pipeline(int(user_id), repo_name)))
        paths = [
            {"repo_path": str(r.get("_id") or ""), "note_count": int(r.get("count") or 0)}
            for r in rows
            if r.get("_id")
        ]
        return {
            "ok": True,
            "repo_name": str(repo_name or ""),
            "count": len(paths),
            "paths": paths,
        }

    def add_to_collection(
        self,
        user_id: int,
        *,
        collection_id: str,
        file_name: str,
        folder: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """משייך קובץ קיים לאוסף קיים.

        **שלושה שערים, ושלושתם נדרשים בגלל אותו כשל.**
        ``CollectionsManager.add_items`` אינה מאמתת שהאוסף קיים או שייך
        לקורא: היא כותבת את הפריט עם ה-``collection_id`` שקיבלה, ורק עדכון
        המונים בסוף תחום לבעלות — ונכשל בשקט. כלומר היא מחזירה
        ``{"ok": True, "added": 1}`` על אוסף שאינו קיים, ומשאירה פריט יתום.
        זהו בדיוק K11: ערך חזרה חיובי על כשל, שמסתיים בהודעת ✅.

        לכן: בעלות **לפני**, קיום הקובץ **לפני**, וספירת מה שנכתב **אחרי**.
        """
        cm = self._collections()
        owned = cm.get_collection(int(user_id), str(collection_id))
        if not isinstance(owned, dict) or not owned.get("ok"):
            return {"ok": False, "error": "collection_not_found"}

        name = str(file_name or "").strip()
        doc = _latest_fresh(self._require_dbm(), int(user_id), name)
        if not doc:
            return {"ok": False, "error": "file_not_found"}

        item: dict[str, Any] = {"file_name": name, "source": "regular"}
        if folder is not None:
            item["folder"] = folder
        if note is not None:
            item["note"] = note
        res = cm.add_items(int(user_id), str(collection_id), [item])
        if not isinstance(res, dict) or not res.get("ok"):
            # ``res`` שאינו dict (True, מחרוזת) הוא כשל חוזה — אין ממנו
            # ``error`` לחלץ, וניסיון ``.get`` עליו היה מפיל את הכלי.
            err = res.get("error") if isinstance(res, dict) else None
            return {"ok": False, "error": str(err or "add_failed")}
        added = int(res.get("added") or 0)
        updated = int(res.get("updated") or 0)
        if added == 0 and updated == 0:
            # ``add_items`` מדלגת בשקט על פריט בעייתי ועדיין מחזירה ok.
            return {"ok": False, "error": "not_added"}
        return {
            "ok": True,
            "collection_id": str(collection_id),
            "file_name": name,
            "added": added,
            "updated": updated,
        }

    def search_notes(
        self,
        user_id: int,
        *,
        query: str,
        limit: int,
        search_content: bool = False,
        content_query: str | None = None,
    ) -> dict[str, Any]:
        """חיפוש פתקים חוצה את שלושת היעדים — שם, ואופציונלית גם גוף.

        ``query`` הוא מחט **השם** (קנונית) ו-``content_query`` מחט
        **התוכן** (משמרת רווחים ושורות) — שתי מחטים כי שני היעדים נשמרו
        אחרת; ההסבר המלא ב-:func:`sticky_notes_target.note_search_filter`.

        **הפרויקציה נושאת משקל ואינה קוסמטיקה:** היא אוכפת "בלי תוכן"
        בגבול המסד ולא בסמך הסריאלייזר, ובכך גם מנתקת את עלות ההעברה
        מגודל גוף הפתק (עד 20K תווים למסמך) וגם מקטינה את קלט המיון.

        **התקרה נאכפת עם שורת סנטינל** — ``limit(want + 1)`` — כדי
        שה-``truncated`` יהיה עובדה ולא ניחוש: שורה נוספת שחזרה היא ראיה
        שיש עוד, ולא הערכה מתוך ספירה שווה לתקרה.
        """
        from sticky_notes_target import note_search_filter

        want = int(limit)
        projection = {key: 1 for key in _NOTE_REF_FIELDS}
        rows = list(
            self._notes_coll()
            .find(
                note_search_filter(
                    int(user_id),
                    query,
                    search_content=bool(search_content),
                    content_needle=content_query,
                ),
                projection,
            )
            .sort("updated_at", -1)
            .limit(want + 1)
        )
        truncated = len(rows) > want
        if truncated:
            rows = rows[:want]
        self._backfill_file_names(int(user_id), rows)
        out: dict[str, Any] = {
            "ok": True,
            "query": str(query or ""),
            "searched_content": bool(search_content),
            "count": len(rows),
            "truncated": truncated,
            "notes": [_as_note_ref(r) for r in rows],
        }
        if content_query is not None:
            out["content_query"] = str(content_query)
        return out

    def _backfill_file_names(self, user_id: int, rows: list[dict[str, Any]]) -> None:
        """משלים ``file_name`` לפגיעות חיפוש שנשמרו לפני שהשדה היה קיים.

        **בלי זה האינווריאנטה של תוצאת החיפוש שקרית.** ההבטחה היא ששדות
        הזיהוי של פגיעה הם בדיוק הארגומנטים של כלי הרשימה המתאים, אבל
        ``codekeeper_list_notes`` מקבל ``file_name`` בלבד — ופתק legacy
        נושא ``file_id`` בלבד. פגיעה כזו הייתה מבוי סתום: הסוכן רואה שהפתק
        קיים ואין לו דרך לקרוא אותו.

        **שאילתה אחת ל-``$in``, ורק כשיש חסרים.** לא לולאה פר-פגיעה: N+1
        על מסלול חיפוש הוא בדיוק מה שחוק ה-Smart Projection נועד למנוע.

        כשל שליפה אינו מפיל את החיפוש — הפגיעה פשוט נשארת עם ``file_id``
        בלבד, כפי שהייתה בלעדי המילוי.
        """
        # **רשימה לכל מזהה, לא שורה אחת.** כמה פתקים על אותו קובץ הם המקרה
        # הרגיל, לא הקצה; מילון ``{file_id: row}`` היה שומר רק את האחרון
        # ומשאיר את כל השאר בלי נתיב ניווט — כלומר בדיוק המבוי הסתום
        # שהמילוי הזה נועד לסגור, רק בשקט יותר.
        missing: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            if isinstance(r, dict) and r.get("file_id") and not r.get("file_name"):
                missing.setdefault(str(r["file_id"]), []).append(r)
        if not missing:
            return
        try:
            from bson import ObjectId  # lazy heavy import

            oids = []
            for raw in missing:
                try:
                    oids.append(ObjectId(raw))
                except Exception:
                    continue  # מזהה פגום — פגיעה אחת פחות, לא חיפוש שנפל
            if not oids:
                return
            found = self._raw_mongo()["code_snippets"].find(
                {"_id": {"$in": oids}, "user_id": int(user_id)}, {"file_name": 1}
            )
            for doc in found:
                name = doc.get("file_name")
                if not name:
                    continue
                for row in missing.get(str(doc.get("_id")), ()):
                    row["file_name"] = name
        except Exception:
            logger.warning("file name backfill for search hits failed", exc_info=True)

    def update_note(
        self,
        user_id: int,
        *,
        note_id: str,
        fields: dict[str, Any],
        expected_content: str | None = None,
    ) -> dict[str, Any]:
        """Partial in-place update by ObjectId, ownership enforced in the filter.

        ``expected_content`` הוא שער אופטימי למסלולי read-modify-write:
        כשהוא נתון, הדריסה מותנית בכך שהגוף במסד עדיין שווה למה שהקורא
        קרא. בלעדיו שתי עריכות ``str_replace`` חופפות קוראות את אותו גוף,
        כל אחת מחשבת החלפה משלה, והאחרונה דורסת את הראשונה — שתיהן
        מדווחות הצלחה ועריכה אחת נעלמת. עם השער, המפסידה מקבלת
        ``conflict`` מפורש במקום ניצחון שקרי. ``update_note`` הכללי
        (עדכון-שדות, לא read-modify-write) אינו משתמש בו בכוונה.
        """
        from bson import ObjectId  # lazy heavy import

        try:
            oid = ObjectId(str(note_id))
        except Exception:
            return {"ok": False, "error": "invalid_note_id"}

        coll = self._notes_coll()
        note = coll.find_one({"_id": oid, "user_id": int(user_id)})
        if not note:
            return {"ok": False, "error": "not_found"}

        # **ההשוואה במרחב של הקורא; המסנן במרחב של המסד.** הגוף שהקורא
        # קיבל עבר ``html.unescape`` ב-``_as_note`` (פתקי legacy נשמרו עם
        # ישויות HTML), ולכן ``expected_content`` מושווה גם מול הערך
        # הגולמי וגם מול פענוחו — השוואה מול הגולמי בלבד הייתה נועלת כל
        # פתק legacy ב-``conflict`` נצחי. מסנן הכתיבה, לעומת זאת, נושא את
        # הערך **הגולמי** שנשלף הרגע: זה מה שבאמת יושב במסד, וזה מה שסוגר
        # את חלון המרוץ שבין הקריאה לכתיבה.
        raw_stored = note.get("content")
        if expected_content is not None:
            decoded = html.unescape(raw_stored) if isinstance(raw_stored, str) else raw_stored
            if expected_content != raw_stored and expected_content != decoded:
                # הפתק כבר השתנה מאז שהקורא קרא אותו — עוד לפני שצילמנו.
                return {"ok": False, "error": "conflict"}

        # **הצילום לפני הדריסה, וכשל בו עוצר אותה.** זו הנקודה שאכלה פתק
        # בפועל: העדכון מחליף את התוכן כולו, ועד היום לא היה ממה לשחזר.
        # אם הצילום נכשל ובכל זאת נדרוס — איבדנו את הפתק בשקט, רק שהפעם
        # אחרי שהבטחנו רשת ביטחון. כל כלי שעובר כאן יורש את ההגנה.
        #
        # **ורק כשהתוכן באמת משתנה.** צילום על עדכון-זהה אינו רשת אלא
        # רעש: הוא מכפיל את אותו גוף בהיסטוריה, וכשהתקרה מלאה — דוחף
        # החוצה גרסה ישנה שעוד אפשר היה לשחזר, בתמורה לעותק של מה שכבר
        # יש. שינוי צבע/שורה בלבד ממילא אינו נוגע בגוף.
        snap_ref: dict[str, Any] | None = None
        content_changes = "content" in fields and fields.get("content") != note.get("content")
        if content_changes:
            ok, snap_ref = self._snapshot_note(int(user_id), note)
            if not ok:
                return {"ok": False, "error": "snapshot_failed"}

        updates = dict(fields)
        # backfill לפתק legacy בלי scope_id — רק במסלול הכתיבה (list נשאר קריאה טהורה)
        if not note.get("scope_id"):
            fname = note.get("file_name")
            if not fname and note.get("file_id"):
                try:
                    ref = self._raw_mongo()["code_snippets"].find_one(
                        {"_id": ObjectId(str(note["file_id"])), "user_id": int(user_id)},
                        {"file_name": 1},
                    )
                    fname = (ref or {}).get("file_name")
                except Exception:
                    fname = None
            if fname:
                from sticky_notes_scope import make_scope_id

                sid = make_scope_id(int(user_id), str(fname))
                if sid:
                    updates["scope_id"] = sid
                    updates["file_name"] = str(fname)

        updates["updated_at"] = _dt.datetime.now(_dt.timezone.utc)
        # **אסימון כתיבה ייחודי, ולא חותמת זמן.** ``updated_at`` נראה כמו
        # אסימון פעולה אבל אינו כזה: מונגו קוטם ל-מילישניות — נמדד, שתי
        # כתיבות במרחק 3 מיקרו-שניות חוזרות **זהות** — ולכן שתי עריכות
        # באותה מילישנייה נושאות את אותה חותמת. ``write_id`` נכתב פעם
        # אחת לקריאה הזו ולעולם אינו חוזר על עצמו; רק הוא מבדיל בוודאות
        # בין "הכתיבה שלנו נגעה במסמך" לבין "אף אחד לא נגע".
        #
        # נכתב רק כשיש צילום להגן עליו — זה המסלול היחיד שקורא אותו.
        our_write_id = _uuid.uuid4().hex if snap_ref is not None else None
        if our_write_id is not None:
            updates["write_id"] = our_write_id
        write_filter: dict[str, Any] = {"_id": oid, "user_id": int(user_id)}
        if expected_content is not None:
            write_filter["content"] = raw_stored
        try:
            res = coll.update_one(write_filter, {"$set": updates})
            matched = int(getattr(res, "matched_count", 0) or 0)
        except Exception:
            # **חריגה אינה ראיה שהכתיבה לא קרתה.** כשל רשת יכול ליפול אחרי
            # שהשרת כבר כתב — ומחיקת הצילום אז משאירה תוכן חדש בלי גרסה
            # לשחזור, בדיוק האובדן שהמנגנון קיים למנוע. מוחקים רק כשקריאה
            # חוזרת **מוכיחה** ששום כתיבה לא נגעה במסמך; בכל ספק — הצילום
            # נשאר, כי גרסה עודפת קלה מאובדן.
            #
            # **שוויון-תוכן לבדו אינו הוכחה — ABA.** אם הכתיבה שלנו כן
            # קרתה וכותב מקביל החזיר את הגוף ל-``raw_stored``, קריאת התוכן
            # לבדה הייתה "מוכיחה" שדבר לא קרה.
            #
            # **וגם חותמת הזמן אינה מספיקה,** כי היא אינה ייחודית: מונגו
            # קוטם ל-מילישניות, ולכן שחזור מקביל באותה מילישנייה מחזיר
            # גם את התוכן וגם את החותמת לערכיהם המקוריים. לכן ההוכחה
            # נשענת על ``write_id`` — אסימון שנוצר לקריאה הזו בלבד:
            #
            # * הכתיבה שלנו נגעה במסמך  ⇒ ``write_id`` הוא **שלנו**, שונה
            #   מזה שקראנו ⇒ הצילום נשמר.
            # * כותב אחר נגע במסמך      ⇒ הוא החליף ``write_id`` (מסלול
            #   ה-MCP) או את התוכן/החותמת (הוובאפ) ⇒ מצב עמום, נשמר.
            # * שלושתם זהים למה שקראנו ⇒ **דבר לא נגע במסמך**, כלומר
            #   הכתיבה שלנו לא קרתה ⇒ הצילום מפוצה.
            #
            # אף מסלול בקוד אינו כותב ``write_id`` ישן בחזרה, ולכן אין
            # דרך לזייף את הענף השלישי.
            try:
                after = coll.find_one(
                    {"_id": oid, "user_id": int(user_id)},
                    {"content": 1, "updated_at": 1, "write_id": 1},
                )
                untouched = after is not None and all(
                    after.get(k) == note.get(k) for k in ("content", "updated_at", "write_id")
                )
                if untouched:
                    self._discard_snapshot(snap_ref)
            except Exception:
                logger.warning("post-failure note verification failed; keeping snapshot")
            raise
        if matched == 0:
            # הפתק השתנה או נעלם בין הקריאה לכתיבה. בלי הבדיקה הזו היינו
            # מחזירים ``ok`` על כתיבה שלא כתבה דבר, ומשאירים גרסה יתומה.
            self._discard_snapshot(snap_ref)
            return {
                "ok": False,
                "error": "conflict" if expected_content is not None else "not_found",
            }
        return {"ok": True, "note": _as_note({**note, **updates})}

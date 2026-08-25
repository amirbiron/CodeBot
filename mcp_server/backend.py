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
import time as _time
import logging
from typing import Any, Callable

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

_HEAVY_FIELDS = ("code", "content", "raw_data", "raw_content")

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
    """Serialize a file document. Drops heavy fields unless ``include_code``."""
    out: dict[str, Any] = {}
    for key, val in (doc or {}).items():
        if key == "_id":
            out["id"] = str(val)
            continue
        if not include_code and key in _HEAVY_FIELDS:
            continue
        out[key] = _json_safe(val)
    # Friendlier alias without dropping the original field.
    if "programming_language" in out:
        out.setdefault("language", out["programming_language"])
    return out


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

    def __init__(
        self, db_manager: Any = None, mongo_db: Any = None, collections_manager: Any = None
    ) -> None:
        self._dbm = db_manager
        self._mongo = mongo_db
        self._cm = collections_manager
        self._notes_idx_done = False

    # -- lazy wiring -------------------------------------------------------
    def _require_dbm(self) -> Any:
        if self._dbm is None:
            from database import db as _db  # lazy heavy import

            self._dbm = _db
        return self._dbm

    def _collections(self) -> Any:
        if self._cm is None:
            from database.collections_manager import CollectionsManager  # lazy

            mongo = (
                self._mongo if self._mongo is not None else getattr(self._require_dbm(), "db", None)
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
    ) -> dict[str, Any] | None:
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
        return _full(doc) if doc else None

    def list_versions(self, user_id: int, *, file_name: str) -> list[dict[str, Any]]:
        return [_clean(v) for v in (self._require_dbm().get_all_versions(user_id, file_name) or [])]

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
        return {"ok": True, "created": prev is None, "file": _clean(saved)}

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
        # **ארבעת האינדקסים, לא רק זה של ה-scope.** ה-MCP הוא כותב מלא של
        # פתקים — קובץ, לוח, וקובץ בריפו — ובנה עד היום אינדקס אחד. פריסה
        # שבה הוא רץ בלי הוובאפ הותירה כל שאילתת לוח וריפו בסריקת אוסף.
        #
        # **המפרטים זהים בייט-לבייט לאלה שבוובאפ** (``_ensure_indexes``):
        # מונגו דוחה ב-code 85/86 אינדקס בשם קיים עם מפתחות אחרים, כלומר
        # סטייה של תו אחד הופכת את הבוטסטראפ השני לכשל שקט לצמיתות.
        # חד-פעמי, ולא מפיל כלי.
        if not self._notes_idx_done:
            self._notes_idx_done = True
            for keys, name in (
                ([("user_id", 1), ("scope_id", 1)], "user_scope_idx"),
                ([("user_id", 1), ("board_id", 1)], "user_board_idx"),
                ([("user_id", 1), ("repo_name", 1), ("repo_path", 1)], "user_repo_idx"),
                # חיפוש לפי שם חוצה את שלושת היעדים, ולכן אינו יכול להישען
                # על אף אחד משני האינדקסים הייחודיים: ה-``partialFilter``
                # שלהם דורש ``board_id``, או ``repo_name`` **וגם**
                # ``repo_path`` — פרדיקטים שהחיפוש אינו נושא.
                ([("user_id", 1), ("title", 1)], "user_title_idx"),
            ):
                try:
                    coll.create_index(keys, name=name)
                except Exception:
                    logger.warning(
                        "sticky notes index %s creation failed (non-fatal)", name, exc_info=True
                    )
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

        ``specs`` הוא רצף של ``(query, cap, exempt)``. ``exempt`` הוא פר-תקרה
        ולא פר-קריאה, כי שתי התקרות נבדלות בפטור: התקרה-למשטח נאכפת גם על
        אדמין, והתקרה-למשתמש פטורה לו.

        **כשל ספירה דוחה.** תקרה שנפתחת לרווחה בדיוק כשהמסד מתקשה אינה
        תקרה. הקוד המוחזר נגזר מ**מצב הספירה** ולא מטקסט החריגה — טקסט של
        חריגה בתשובה הוא דלף ממתין.

        **ידוע ולא מטופל כאן:** בין הספירה ל-``insert_one`` יש חלון שבו שתי
        בקשות מקבילות עוברות. תיקון אמיתי הוא מונה אטומי או reservation,
        והוא חייב לחול על שלוש התקרות במנגנון אחד — לא על אחת מהן.
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

    def list_notes(self, user_id: int, *, file_name: str) -> dict[str, Any]:
        """List notes for a file (pure read — no backfill, unlike the webapp GET)."""
        from sticky_notes_scope import make_scope_id  # מודול טהור בשורש הריפו

        scope_id = make_scope_id(int(user_id), file_name)
        related = self._related_file_ids(user_id, file_name)
        query = _notes_scope_filter(user_id, scope_id, related)
        rows = list(self._notes_coll().find(query).sort("created_at", 1).limit(500))
        return {
            "ok": True,
            "file_name": file_name,
            "count": len(rows),
            "notes": [_as_note(r) for r in rows],
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

    def list_board_notes(self, user_id: int, *, board_id: str) -> dict[str, Any]:
        """פתקי לוח יחיד (קריאה טהורה)."""
        from sticky_notes_target import board_notes_filter

        board = self._owned_board(user_id, board_id)
        if board is None:
            return {"ok": False, "error": "board_not_found"}

        canonical = self._canonical_board_id(board)
        query = board_notes_filter(int(user_id), canonical)
        rows = list(self._notes_coll().find(query).sort("created_at", 1).limit(500))
        return {
            "ok": True,
            "board_id": canonical,
            "board_name": str(board.get("name") or ""),
            "count": len(rows),
            "notes": [_as_note(r) for r in rows],
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
        from sticky_notes_target import normalize_repo_path, repo_file_exists, repo_notes_filter

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
        if repo_file_exists(self._raw_mongo(), clean_repo, clean_path) is False:
            out["orphaned"] = True
        return out

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

    def search_notes(self, user_id: int, *, query: str, limit: int) -> dict[str, Any]:
        """חיפוש פתקים **לפי שם**, חוצה את שלושת היעדים.

        **הפרויקציה נושאת משקל ואינה קוסמטיקה:** היא אוכפת "שם בלבד, בלי
        תוכן" בגבול המסד ולא בסמך הסריאלייזר, ובכך גם מנתקת את עלות
        החיפוש מגודל גוף הפתק (עד 20K תווים למסמך) וגם מקטינה את קלט
        המיון.

        **התקרה נאכפת עם שורת סנטינל** — ``limit(want + 1)`` — כדי
        שה-``truncated`` יהיה עובדה ולא ניחוש: שורה נוספת שחזרה היא ראיה
        שיש עוד, ולא הערכה מתוך ספירה שווה לתקרה.
        """
        from sticky_notes_target import title_search_filter

        want = int(limit)
        projection = {key: 1 for key in _NOTE_REF_FIELDS}
        rows = list(
            self._notes_coll()
            .find(title_search_filter(int(user_id), query), projection)
            .sort("updated_at", -1)
            .limit(want + 1)
        )
        truncated = len(rows) > want
        if truncated:
            rows = rows[:want]
        self._backfill_file_names(int(user_id), rows)
        return {
            "ok": True,
            "query": str(query or ""),
            "count": len(rows),
            "truncated": truncated,
            "notes": [_as_note_ref(r) for r in rows],
        }

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
        missing = {
            str(r["file_id"]): r
            for r in rows
            if isinstance(r, dict) and r.get("file_id") and not r.get("file_name")
        }
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
                row = missing.get(str(doc.get("_id")))
                if row is not None and doc.get("file_name"):
                    row["file_name"] = doc["file_name"]
        except Exception:
            logger.warning("file name backfill for search hits failed", exc_info=True)

    def update_note(self, user_id: int, *, note_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Partial in-place update by ObjectId, ownership enforced in the filter."""
        from bson import ObjectId  # lazy heavy import

        try:
            oid = ObjectId(str(note_id))
        except Exception:
            return {"ok": False, "error": "invalid_note_id"}

        coll = self._notes_coll()
        note = coll.find_one({"_id": oid, "user_id": int(user_id)})
        if not note:
            return {"ok": False, "error": "not_found"}

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
        coll.update_one({"_id": oid, "user_id": int(user_id)}, {"$set": updates})
        return {"ok": True, "note": _as_note({**note, **updates})}

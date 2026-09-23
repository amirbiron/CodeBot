"""Read-only data access for the repo-browser tools (Phase D, admin-only).

Wraps the existing Repo Sync Engine in-process (``GitMirrorService`` +
``RepoSearchService`` + the ``repo_metadata``/``sync_jobs`` collections) —
no new persistence logic. Keyed by logical ``repo_name``, not ``user_id``.

Resilience contract: the sync worker may run ``git fetch``/``gc`` concurrently
(there are no read locks), so a failed read checks for a *running* sync job and
returns ``{"error": "sync_in_progress", "retry_after": N}`` — telling the
calling model to retry shortly instead of concluding the repo/file is missing.

The secrets policy (``repo_policy``) is applied on every surface: tree omits,
search skips, get blocks. Heavy content is returned only by ``get_file``
(Smart Projection).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .backend import _json_safe
from .repo_handlers import (
    OUTLINE_PER_PAGE_DEFAULT,
    OUTLINE_PER_PAGE_MAX,
    OUTPUT_BYTE_BUDGET,
    TREE_PER_PAGE_MAX,
)
from .handlers import apply_line_range, normalize_line_range
from .outline import extract_outline
from .repo_policy import denylist_patterns, is_denied

#: תקרת גודל נפרדת לקריאת טווח שורות.
#:
#: התקרה הרגילה של ``get_file_at_commit`` היא 500KB, והיא נבדקת **לפני**
#: הפענוח והחיתוך — ולכן ``lines`` לא עזר לקובץ גדול: הוא הוחזר כ-
#: ``too_large`` עם הפרמטר בדיוק כמו בלעדיו (#3317). ``webapp/app.py`` בן
#: 805,594 הבייטים, הקובץ שהכי הרבה עובדים עליו, היה בלתי קריא דרך הכלי.
#:
#: **למה תקרה אחרת ולא ביטול.** בלוב שמתחת לתקרה נקרא ומפוענח במלואו לפני
#: החיתוך, אז "בלי תקרה" פירושו שקובץ פתולוגי בריפו יגיע ל-RAM כמו שהוא.
#: נמדד: קריאה ופענוח צורכים כפי שלושה מגודל הקובץ — 6.6MB הגיעו ל-35.7MB
#: שיא. תקרה של 10MB חוסמת את זה בערך ב-30MB, ונותנת פי 12 מרווח מעל
#: הקובץ הגדול ביותר שבאמת קוראים. ומאז #3433 התקרה נבדקת מול גודל
#: האובייקט במאגר **לפני** ``git show``, ולכן קובץ שמעליה אינו נטען כלל —
#: החסם הוא על מה שנקרא, לא בדיקה בדיעבד.
#:
#: זו החלטת מדיניות של שכבת ה-MCP, לא של שירות המראה — ולכן היא כאן ולא
#: שם, ואינה מייתרת את 500KB שממשיכה לחול על קריאה מלאה ועל הוובאפ.
RANGE_READ_MAX_BYTES = 10 * 1024 * 1024

logger = logging.getLogger(__name__)

SYNC_RETRY_AFTER_SECONDS = 30


def _safe_int(value: Any, default: int) -> int:
    """Best-effort int conversion; invalid input ⇒ default (clamp policy, 13.4)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


_REPOS_PROJECTION = {
    "_id": 0,
    "repo_name": 1,
    "repo_url": 1,
    "default_branch": 1,
    "last_sync_time": 1,
    "last_synced_sha": 1,
    "total_files": 1,
    "sync_status": 1,
}


def _outline_response(
    file_meta: dict[str, Any],
    content: str,
    path: str,
    symbol: str | None,
    page: Any,
    per_page: Any,
) -> dict[str, Any]:
    """עוטף את ``extract_outline`` בעימוד ובמעטפת התשובה של הכלי.

    **``status`` ולא ``error``.** קובץ שאין לו אאוטליין הוא בדיוק המקרה של
    ``binary``: הקריאה הצליחה, פשוט אין תוכן מהסוג שביקשו. ``error`` שמור
    ל-``ok: false``, לפי אוצר המילים שכבר קיים בכלים כאן.
    """
    result = extract_outline(content, path, symbol=symbol)
    if result.get("status") != "ok":
        # ערוץ הכשל של ``extract_outline`` הוא ערך ההחזרה ולא חריגה, ולכן
        # נבדק כאן במפורש. בדיקה של "לא נזרקה חריגה" בלבד הייתה מציגה
        # קובץ שבור כקובץ בלי סימבולים.
        return {"ok": True, "file": file_meta, **result}

    # אותה הגנה שהשכן ``list_tree`` עושה בכוונה ועם נימוק כתוב: המטפל כבר
    # מהדק, אבל המתודה הזו היא API ציבורי, וקורא ישיר לא יחתוך עם start
    # שלילי ולא יקרוס על ערך לא-מספרי.
    page_i = max(1, _safe_int(page, 1))
    per_page_i = min(max(1, _safe_int(per_page, OUTLINE_PER_PAGE_DEFAULT)),
                     OUTLINE_PER_PAGE_MAX)

    symbols = result["symbols"]
    window = symbols[(page_i - 1) * per_page_i :][:per_page_i]

    # **מדידה בבתים, על הסריאליזציה האמיתית.** גרסה קודמת ניסתה להוכיח
    # שהעמוד נכנס בתקציב על ידי חסימת אורך השם ב-200 **תווים** — וזה נשבר
    # בשני מקומות: שם ב-CJK הוא שלושה בתים לתו, כך שעמוד מקסימלי הגיע
    # ל-323,000 בתים מול תקציב של 256,000; והקיצוץ הרס את הזהות, כך
    # ש-``symbol=`` עם השם המלא לא מצא את הסימבול. חסימת תווים אינה
    # בטיחות בתים, וקיצוץ מזהה אינו אופציה.
    #
    # **וכשהעמוד לא נכנס — דוחים אותו, לא חותכים.** חיתוך בתוך עמוד יחד עם
    # עימוד אריתמטי מאבד סימבולים: העמוד נעצר באמצע והבא מתחיל אחרי
    # ``per_page`` המלא. דחייה מפורשת עם ``max`` היא חסרת אובדן, דטרמיניסטית,
    # ואומרת לקורא בדיוק מה לעשות — במקום להחזיר תשובה שנראית שלמה.
    payload_bytes = len(json.dumps(window, ensure_ascii=False).encode("utf-8"))
    if payload_bytes > OUTPUT_BYTE_BUDGET:
        return {
            "ok": False,
            "error": "page_too_large",
            "bytes": payload_bytes,
            "max": OUTPUT_BYTE_BUDGET,
            "per_page": per_page_i,
        }

    return {
        "ok": True,
        "status": "outline",
        "file": file_meta,
        "symbols": window,
        "total": result["total"],
        "page": page_i,
        "per_page": per_page_i,
    }


#: קודי הכשל של קיבוע commit שאומרים "לא עכשיו" ולא "אין כזה". רק עליהם
#: ``ReadSnapshot`` מתריע: ``invalid_ref``, ``repo_not_found`` ו-
#: ``invalid_repo_name`` הם תשובות רגילות שהקריאה עצמה תחזיר לקורא בשמן
#: (``not_found``, ``repo_not_mirrored``, ``invalid_input``), וסירוב רגיל אינו
#: נרשם בלוג (SUGG-022).
_TRANSIENT_PIN_ERRORS = frozenset({"timeout", "internal_error"})


class ReadSnapshot:
    """תמונת מצב אחת של המראות, לקריאה אחת של ``codekeeper_read_batch``.

    **שלוש שאלות, כל אחת פעם אחת לכל ריפו:** מה הענף הראשי (``repo_metadata``
    במונגו), לאיזה commit הוא מצביע עכשיו (``GitMirrorService.resolve_commit``),
    והאם סנכרון רץ (``sync_jobs``, רק במסלול הכשל). בלי האובייקט הזה כל פריט
    בבאץ' היה שואל את שלושתן מחדש — ``find_one`` בתוך לולאה (R8) — ו-autosync
    שמושך באמצע הבאץ' היה מפצל את התשובה בין שני commits.

    **קורא מה-SHA ומדווח את ה-ref.** :meth:`RepoBackend.get_file` מעביר למראה
    את ה-commit המקובע, אבל ``file.ref`` בתשובה נשאר ה-ref שהתבקש — אותה
    מחרוזת שהכלי הבודד היה כותב. כך תשובה של פריט זהה בית-בית לתשובת הכלי
    הבודד, כל עוד הענף לא זז.

    **כשהקיבוע נכשל, הקריאה ממשיכה בשם הענף — והכשל גלוי.** קוד שאומר "אין
    כזה" (``invalid_ref``, ``repo_not_found``, ``invalid_repo_name``) יחזור
    מהקריאה עצמה בשמו, בדיוק כמו בכלי הבודד, ולכן אין מה לרשום. קוד שאומר
    "לא עכשיו" (``timeout``, ``internal_error``) נרשם כ-WARNING, פעם אחת לכל
    ריפו: הפריטים של אותו ריפו נקראים אז לפי שם הענף, וכל אחד פותר אותו
    בנפרד, כך שהם **יכולים** להגיע מ-commits שונים. זו נפילה-לאחור למסלול
    גרוע (``silent-fallback-to-worse-path``), ולכן היא לא שקטה: הלוג אומר
    שהיא קרתה, ו-``resolved_commit`` של כל פריט אומר מאיזה commit הוא בא.
    הכשל נשמר ואינו מנוסה שוב בפריט הבא, כי ניסיון חוזר על timeout היה עולה
    לכל פריט את כל ה-``timeout`` של ``GitMirrorService._validate_ref_with_git``.

    **חוט אחד, קריאה אחת.** האובייקט נבנה בתחילת הקריאה ונזרק בסופה, ורק
    החוט שמריץ את הבאץ' נוגע בו — ולכן אין בו מנעול. הוא אינו משותף בין
    קריאות, ואינו מטמון: שום דבר ממנו אינו שורד את הקריאה שבנתה אותו.
    """

    def __init__(self, backend: "RepoBackend") -> None:
        self._backend = backend
        self._refs: dict[str, str] = {}
        self._commits: dict[tuple[str, str], str] = {}
        self._syncing: dict[str, bool] = {}

    def default_ref(self, repo: str) -> str:
        """הענף הראשי של ``repo`` — שאילתה אחת לכל ריפו, לא לכל פריט."""
        ref = self._refs.get(repo)
        if ref is None:
            ref = self._backend._default_ref(repo)
            self._refs[repo] = ref
        return ref

    def commit(self, repo: str, ref: str) -> str:
        """ה-commit לקרוא ממנו את ``ref``: ה-SHA המקובע, או ``ref`` עצמו כשהקיבוע נכשל."""
        key = (repo, ref)
        read_at = self._commits.get(key)
        if read_at is None:
            read_at = self._pin(repo, ref)
            self._commits[key] = read_at
        return read_at

    def _pin(self, repo: str, ref: str) -> str:
        try:
            pinned = self._backend._require_mirror().resolve_commit(repo, ref)
        except Exception:
            # ``resolve_commit`` אינו זורק לפי החוזה שלו; חריגה כאן היא באג
            # או תלות שבורה, ולכן ``exception`` עם traceback ולא אזהרה. הקריאה
            # עצמה תנסה את אותה מראה ותחזיר את הכשל בשמו.
            logger.exception("read snapshot: pinning %s at %s raised; reading at the ref", repo, ref)
            return ref
        if pinned.get("ok"):
            return str(pinned["commit"])
        error = pinned.get("error")
        if error in _TRANSIENT_PIN_ERRORS:
            logger.warning(
                "read snapshot: could not pin %s at %s (%s); its items are read at the ref "
                "and may come from different commits",
                repo, ref, error,
            )
        return ref

    def sync_running(self, repo: str) -> bool:
        """האם סנכרון רץ על ``repo`` — שאלה אחת לכל ריפו, במסלול הכשל בלבד."""
        running = self._syncing.get(repo)
        if running is None:
            running = self._backend._sync_running(repo)
            self._syncing[repo] = running
        return running


class RepoBackend:
    """Duck-typed backend over a pymongo handle + the mirror/search services.

    ``mirror`` / ``search_service`` are injectable for tests and lazily resolved
    in production (importing the services stack only when a repo tool runs).
    """

    def __init__(
        self,
        db: Any = None,
        mirror: Any = None,
        search_service: Any = None,
        db_manager: Any = None,
    ) -> None:
        self._db = db
        self._mirror = mirror
        self._search = search_service
        # ``db_manager`` נדרש **רק** ליצירת האינדקסים, דרך
        # ``DatabaseManager.safe_create_index``. הוא מוזרק ולא מיובא, כדי
        # לשמור על הכלל שבראש החבילה: מודול כאן אינו מייבא תלות כבדה
        # ברמת המודול.
        self._db_manager = db_manager
        self._ensure_indexes()

    # -- wiring ------------------------------------------------------------
    def _require_mirror(self) -> Any:
        """The mirror service, on first use. Unlocked on purpose.

        Tool bodies run on worker threads since #3379, so two reads really can
        arrive here together — the question is what that costs, and here it
        costs nothing. The guard is the value, assigned only after the call
        returns, so there is no window where one is set and the other is not.
        And the construction is safe to repeat: ``GitMirrorService.__init__``
        assigns paths and compiled patterns, and its one side effect is
        ``mkdir(parents=True, exist_ok=True)`` — idempotent, and it raises
        before any assignment if the path is not writable, so a failure leaves
        the field unset and the next call retries for real.

        The loser of a race is discarded while its caller may still hold it.
        That is fine because the object carries no per-instance state beyond
        those paths: either instance answers identically.
        """
        if self._mirror is None:
            from services.git_mirror_service import get_mirror_service  # lazy heavy import

            self._mirror = get_mirror_service()
        return self._mirror

    def _require_search(self) -> Any:
        """The search service, on first use. Unlocked, for the same reason.

        ``RepoSearchService.__init__`` stores the db handle and calls
        ``get_mirror_service()`` — so it inherits the paragraph above rather
        than adding anything of its own.
        """
        if self._search is None:
            from services.repo_search_service import create_search_service  # lazy

            self._search = create_search_service(self._db)
        return self._search

    def _ensure_indexes(self) -> None:
        """יצירת האינדקסים שהשירות הזה נשען עליהם, דרך המנגנון הקנוני.

        **``DatabaseManager.safe_create_index`` ולא יצירה ישירה.** גרסה קודמת
        כאן שכפלה את מדיניות ההתנגשות שלו — וקיבלה אותה שגויה: היא זיהתה את
        הקודים ``85``/``86`` והחשיבה אותם להצלחה, בזמן שהמנגנון האמיתי
        **קורא את האינדקסים בפועל אחרי ההתנגשות** ומאשר רק אם המפתחות *ו*-
        ``unique`` תואמים (``_index_matches``). קוד ``86`` פירושו "אותו שם,
        מפתחות אחרים" — כלומר בדיוק לא כיסוי, והשכפול שלי היה מכריז הצלחה
        ומשאיר את השליפות ב-COLLSCAN.

        **``unique=True`` בשניהם.** גרסה קודמת ביקשה אינדקס לא-ייחודי בטענה
        שכל הצורך הוא חיפוש. זה החמיץ שהאינדקס הלא-ייחודי **חוסם** את
        הייחודי: ``scripts/create_repo_indexes.py`` היה מקבל
        ``IndexOptionsConflict`` ונופל, כלומר מסד חדש היה נשאר בלי אילוץ
        הזהות שה-upsert של האינדקסר מניח.

        ללא ``db_manager`` לא נוצרים אינדקסים — עדיף לא ליצור מאשר לשכפל שוב
        את המדיניות.
        """
        create = getattr(self._db_manager, "safe_create_index", None)
        if self._db is None or not callable(create):
            # אותו דפוס ``getattr`` כמו ב-``DatabaseManager._create_indexes``,
            # שנועד שם בדיוק לדמויות בדיקה בלי המתודה.
            logger.debug("no db_manager.safe_create_index; skipping index setup")
            return

        wanted = (
            # list_repos runs on repo_metadata on every call, and the collection
            # had no index at all — closing that gap is part of this phase.
            ("repo_metadata", [("repo_name", 1)]),
            # ``repo_files`` נשלף לפי ``(repo_name, path)`` בכל מקום: ספירת
            # השורות של ``list_tree``, ההעשרה של ``search_repo`` בכל חיפוש,
            # דפדפן הריפו בוובאפ, וה-upsert של האינדקסר לכל קובץ בכל סנכרון.
            # את האינדקס הצהיר ``scripts/create_repo_indexes.py``, אבל שום דבר
            # לא מריץ את הסקריפט, ולכן בפועל הוא היה קיים רק אם מישהו הריץ
            # אותו ידנית.
            ("repo_files", [("repo_name", 1), ("path", 1)]),
        )
        for collection, keys in wanted:
            # כל אחד בנפרד: כשל באחד אינו מדלג על השני, ו**שום** כשל כאן אינו
            # מפיל את בניית השרת — אינדקס חסר פוגע בביצועים, לא בנכונות.
            try:
                create(collection, keys, unique=True)
            except Exception:
                logger.warning(
                    "%s index setup raised (non-fatal); lookups may scan",
                    collection,
                    exc_info=True,
                )

    # -- helpers -----------------------------------------------------------
    def _sync_running(self, repo_name: str) -> bool:
        # Local autosync (this service cloning/fetching right now) …
        try:
            from .repo_autosync import is_refreshing

            if is_refreshing(repo_name):
                return True
        except Exception:
            pass
        # … or the webapp's webhook-driven sync worker (shared job queue).
        try:
            if self._db is None:
                return False
            doc = self._db["sync_jobs"].find_one({"repo_name": repo_name, "status": "running"})
            return doc is not None
        except Exception:
            return False

    def _transient_error(
        self, repo_name: str, fallback: str, snapshot: ReadSnapshot | None = None
    ) -> dict[str, Any]:
        """Map a failed read to sync_in_progress (retryable) when a sync runs.

        With a ``snapshot`` the sync status is asked once per repo for the whole
        call (:meth:`ReadSnapshot.sync_running`); without one, every failure
        asks again, as it always has.
        """
        running = (
            snapshot.sync_running(repo_name)
            if snapshot is not None
            else self._sync_running(repo_name)
        )
        if running:
            return {
                "ok": False,
                "error": "sync_in_progress",
                "retry_after": SYNC_RETRY_AFTER_SECONDS,
                "message": (
                    "A sync is running for this repo right now; the repo/file may "
                    "exist — retry after a short wait instead of assuming absence."
                ),
            }
        return {"ok": False, "error": fallback}

    def _default_ref(self, repo_name: str) -> str:
        try:
            meta = (
                self._db["repo_metadata"].find_one({"repo_name": repo_name})
                if self._db is not None
                else None
            )
        except Exception:
            meta = None
        branch = (meta or {}).get("default_branch")
        return f"refs/heads/{branch}" if branch else "HEAD"

    def snapshot(self) -> ReadSnapshot:
        """תמונת מצב חדשה לקריאה אחת — ראו :class:`ReadSnapshot`."""
        return ReadSnapshot(self)

    # -- tools -------------------------------------------------------------
    def list_repos(self, *, limit: int = 50) -> dict[str, Any]:
        try:
            cursor = (
                self._db["repo_metadata"]
                .find({}, _REPOS_PROJECTION)
                .sort("repo_name", 1)
                .limit(int(limit))
            )
            repos = [_json_safe(dict(doc)) for doc in cursor]
        except Exception:
            logger.warning("list_repos query failed", exc_info=True)
            return {"ok": False, "error": "db_error"}
        return {"ok": True, "count": len(repos), "repos": repos}

    def list_tree(
        self,
        *,
        repo: str,
        path: str | None = None,
        ref: str | None = None,
        page: int = 1,
        per_page: int = 200,
        byte_budget: int = 256_000,
        include_stats: bool = False,
    ) -> dict[str, Any]:
        use_ref = ref or self._default_ref(repo)
        sizes: dict[str, int | None] = {}
        try:
            mirror = self._require_mirror()
            if include_stats:
                # ``-l`` באותה קריאת ``ls-tree`` — הגודל מגיע בחינם.
                entries = mirror.list_all_files_with_sizes(repo, use_ref)
                if entries is None:
                    files = None
                else:
                    files = [e["path"] for e in entries]
                    sizes = {e["path"]: e["size"] for e in entries}
            else:
                files = mirror.list_all_files(repo, use_ref)
        except Exception:
            logger.warning("list_tree read failed", exc_info=True)
            files = None
        if files is None:
            return self._transient_error(repo, "repo_or_ref_not_found")

        prefix = (path or "").strip().strip("/")
        if prefix:
            files = [f for f in files if f == prefix or f.startswith(prefix + "/")]
        files = [f for f in files if not is_denied(f)]  # policy: omit
        total = len(files)

        # Defense-in-depth: the handler already clamps, but this method is a
        # public API — normalize again so a direct caller can't slice with a
        # negative start or crash on a non-numeric value.
        page_i = max(1, _safe_int(page, 1))
        per_page_i = min(max(1, _safe_int(per_page, 200)), TREE_PER_PAGE_MAX)

        start = (page_i - 1) * per_page_i
        page_items = files[start : start + per_page_i]

        # ההעשרה כולה במקום אחד: השליפה, ההרכבה והמיפוי לנתיב. הלולאה למטה
        # מקבלת רשומה מוכנה או ``None``, ולא מסתעפת בגוף שלה.
        stats = self._stats_for_page(repo, page_items, sizes) if include_stats else {}

        # Output byte budget: never let one page blow up the response.
        out: list[str] = []
        entries_out: list[dict[str, Any]] = []
        used = 0
        truncated = False
        for item in page_items:
            entry = stats.get(item)
            cost = len(item.encode("utf-8")) + 8
            if entry is not None:
                # רשומה מועשרת שוקלת הרבה יותר מנתיב, ולכן היא נספרת כפי
                # שהיא — אחרת העמוד היה חורג מהתקציב בלי שאיש ידע.
                cost += len(str(entry).encode("utf-8"))
            used += cost
            if used > byte_budget:
                truncated = True
                break
            out.append(item)
            if entry is not None:
                entries_out.append(entry)
        result: dict[str, Any] = {
            "ok": True,
            "repo": repo,
            "ref": use_ref,
            "path": prefix or None,
            "total": total,
            "page": page_i,
            "per_page": per_page_i,
            "paths": out,
            "truncated": truncated,
        }
        if include_stats:
            # נגזר מאותה לולאה ומאותה נקודת חיתוך כמו ``paths``, ולכן שתי
            # הרשימות תמיד באותו אורך ובאותו סדר. ``tests`` אוכפים את זה.
            result["entries"] = entries_out
        return result

    def _stats_for_page(
        self, repo: str, paths: list[str], sizes: dict[str, int | None]
    ) -> dict[str, dict[str, Any]]:
        """רשומת ``entries`` מוכנה לכל נתיב בעמוד, ממופה לפי נתיב.

        מרכז את כל ההעשרה: הגודל מגיע כבר מ-``list_all_files_with_sizes``,
        ספירת השורות נשלפת כאן, וההרכבה נעשית במקום אחד. ``list_tree`` רק
        שואל ומקבל — הוא לא בונה רשומות בעצמו.
        """
        counts = self._line_counts(repo, paths)
        return {
            path: {
                "path": path,
                "size": sizes.get(path),
                "lines": (counts.get(path) or {}).get("lines"),
                "lines_commit_sha": (counts.get(path) or {}).get("commit_sha"),
            }
            for path in paths
        }

    def _line_counts(self, repo: str, paths: list[str]) -> dict[str, dict[str, Any]]:
        """ספירות שורות מ-``repo_files``, לנתיבי עמוד אחד בלבד.

        git לא נותן ספירת שורות בלי לקרוא כל בלוב, ולכן המקור הוא האינדקסר
        (``services/code_indexer.py``), שכותב ``lines`` לצד ``commit_sha``.
        השאילתה נשענת על האינדקס הייחודי ``(repo_name, path)`` וחסומה בגודל
        העמוד, לא בגודל הריפו.

        ``commit_sha`` מוחזר יחד עם הספירה **בכוונה**: האינדוקס נעשה על ידי
        הסנכרון של הוובאפ, לא על ידי ה-autosync של שירות ה-MCP, ולכן ספירה
        יכולה להיות של גרסה קודמת של הקובץ. ערך מיושן שנראה תקין גרוע מערך
        חסר, ולכן המקור נשלח יחד איתו במקום להסתיר אותו.
        """
        if self._db is None or not paths:
            return {}
        try:
            cursor = self._db["repo_files"].find(
                {"repo_name": repo, "path": {"$in": list(paths)}},
                {"path": 1, "lines": 1, "commit_sha": 1},
            )
            out: dict[str, dict[str, Any]] = {}
            for doc in cursor:
                key = doc.get("path")
                if isinstance(key, str):
                    out[key] = {
                        "lines": doc.get("lines"),
                        "commit_sha": doc.get("commit_sha"),
                    }
            return out
        except Exception:
            # מדד נלווה בלבד: כשל כאן משאיר ``lines`` ריק ולא מפיל את הרשימה.
            logger.warning("repo_files line-count lookup failed", exc_info=True)
            return {}

    def get_file(
        self,
        *,
        repo: str,
        path: str,
        ref: str | None = None,
        lines: Any = None,
        outline: bool = False,
        symbol: str | None = None,
        page: int = 1,
        per_page: int = 100,
        snapshot: ReadSnapshot | None = None,
    ) -> dict[str, Any]:
        """Read one file from a mirror — the path every repo and docs read goes through.

        ``snapshot`` is passed only by ``codekeeper_read_batch``: the default
        branch, the commit the file is read at, and the sync status then come
        from the one :class:`ReadSnapshot` of that call instead of being looked
        up again per file. The answer names ``ref`` exactly as it would without
        it; what changes is only which commit the mirror is asked for. Without a
        snapshot this method does precisely what it did before the parameter
        existed.
        """
        if is_denied(path):  # policy: block, before touching the mirror
            return {"ok": False, "error": "path_denied"}
        # הטווח נבדק **לפני** הקריאה. כשהתקרה הייתה 500KB זה לא היה משנה,
        # כי קובץ גדול נפסל ממילא; עכשיו טווח פגום כמו ``[9, 2]`` היה גורם
        # לקריאה ולפענוח של עד 10MB רק כדי להיפסל בסוף. הבדיקה טהורה וזולה,
        # ואין סיבה שתרוץ אחרי העבודה היקרה.
        # שני מצבי קריאה שאינם מצטברים. התעלמות שקטה מאחד מהם היא בדיוק
        # הכשל שהפרויקט הזה רודף אחריו: הקורא טרח להעביר פרמטר, קיבל
        # תשובה תקינה, ואין שום סימן שמה שביקש לא קרה.
        if outline and lines is not None:
            return {"ok": False, "error": "outline_and_lines"}

        bounds: Any = None
        if lines is not None:
            # אותו עוזר משותף שמשרת גם את ``codekeeper_get_file``, כדי
            # ששני הכלים לא יסטו זה מזה בסמנטיקה.
            bounds = normalize_line_range(lines)
            if isinstance(bounds, str):
                return {"ok": False, "error": bounds}

        use_ref = ref or (
            snapshot.default_ref(repo) if snapshot is not None else self._default_ref(repo)
        )
        # רק לקריאת טווח. בלי ``lines`` לא מועבר ``max_size`` כלל, כך
        # שברירת המחדל של שירות המראה נשארת מקור האמת היחיד ל-500KB —
        # ושתי ההתנהגויות לא נפרדות לשני מספרים שצריך לסנכרן.
        # אאוטליין נשפט כמו קריאת טווח: הוא קורא את הקובץ כולו אבל מחזיר
        # פלט זעיר, ולכן אין סיבה שתקרת התצוגה של 500KB תחסום אותו.
        wants_slice = lines is not None or outline
        size_kwargs = {"max_size": RANGE_READ_MAX_BYTES} if wants_slice else {}
        try:
            # עם תמונת מצב — ה-SHA שהריפו קובע אליו בתחילת הקריאה; בלעדיה —
            # ה-ref כמו שהוא, כמו תמיד. ``file.ref`` בתשובה הוא ``use_ref`` בשני
            # המקרים (ראו :class:`ReadSnapshot`, "קורא מה-SHA ומדווח את ה-ref").
            read_at = snapshot.commit(repo, use_ref) if snapshot is not None else use_ref
            res = self._require_mirror().get_file_at_commit(
                repo, path, read_at, **size_kwargs
            )
        except Exception:
            logger.warning("get_file read failed", exc_info=True)
            res = {"error": "internal_error"}

        if res.get("success"):
            file_meta: dict[str, Any] = {
                "path": res.get("file_path", path),
                "ref": use_ref,
                "resolved_commit": res.get("resolved_commit"),
                "size": res.get("size"),
            }
            if res.get("is_binary"):
                return {"ok": True, "status": "binary", "file": file_meta}
            file_meta["lines"] = res.get("lines")
            file_meta["encoding"] = res.get("encoding")
            content = res.get("content")
            if outline:
                return _outline_response(file_meta, content or "", path,
                                         symbol, page, per_page)
            if bounds is not None:
                sliced = apply_line_range(content or "", *bounds)
                if isinstance(sliced, str):
                    return {"ok": False, "error": sliced}
                return {
                    "ok": True,
                    "status": "ok",
                    "file": file_meta,
                    "content": sliced["text"],
                    "range": sliced["range"],
                }
            return {"ok": True, "status": "ok", "file": file_meta, "content": content}

        err = str(res.get("error") or "internal_error")
        if err == "file_too_large":
            return {
                "ok": True,
                "status": "too_large",
                "file": {"path": path, "ref": use_ref, "size": res.get("size")},
                "max": res.get("max_size"),
            }
        if err == "file_not_in_commit":
            return {"ok": False, "error": "not_found"}
        if err in ("invalid_repo_name", "invalid_file_path"):
            return {"ok": False, "error": "invalid_input"}
        # repo_not_found / invalid_commit / git_error / timeout / internal_error:
        # possibly a transient race with a running sync — say so if it is.
        #
        # A mirror the host does not have is its own code (#3432, SUGG-011):
        # ``not_found`` invites the agent to try another file name, when what
        # is missing is the whole repository — an operator's matter, not the
        # caller's. ``invalid_commit`` stays ``not_found``: the repo is there,
        # and the ref is what the caller can change.
        if err == "repo_not_found":
            return self._transient_error(repo, "repo_not_mirrored", snapshot=snapshot)
        fallback = "not_found" if err == "invalid_commit" else "read_failed"
        return self._transient_error(repo, fallback, snapshot=snapshot)

    def search(
        self,
        *,
        repo: str,
        query: str,
        file_pattern: str | None = None,
        max_results: int = 50,
        byte_budget: int = 256_000,
        context_lines: int = 0,
        regex: bool = False,
        case_sensitive: bool = False,
        include_vendored: bool = False,
    ) -> dict[str, Any]:
        """Search the mirror, with a count that means what it says.

        ``total`` is the number of matches in the repo, not the number of rows
        in this answer — and it is present **only when it is exact**. When the
        count itself was cut short (ceiling, timeout) the field is absent and
        ``total_at_least`` carries the lower bound instead, because a number
        that looks exact and is not is worse than no number at all.

        The secrets policy travels **down** to the engine as patterns
        (:func:`denylist_patterns`), so a denied file is skipped before it is
        ever scanned — which is what makes the count and the cut agree on the
        same set of files. :func:`is_denied` still filters the rows that come
        back: one source, two layers, no second list.
        """
        try:
            res = self._require_search().search(
                repo,
                query,
                search_type="content",
                file_pattern=(file_pattern or None),
                max_results=int(max_results),
                context_lines=int(context_lines),
                regex=bool(regex),
                # Passed explicitly, never left to a default: the two layers
                # below declare **opposite** ones (``RepoSearchService.search``
                # is False, ``search_with_git_grep`` is True). Until now this
                # call omitted the argument entirely, so the False won and the
                # tool was always case-insensitive with no way to say otherwise.
                case_sensitive=bool(case_sensitive),
                include_vendored=bool(include_vendored),
                exclude_paths=list(denylist_patterns()),
            )
        except Exception:
            logger.warning("search failed", exc_info=True)
            return self._transient_error(repo, "search_failed")
        engine_error = res.get("error")
        partial_failure = False
        if engine_error:
            # ``invalid_pattern`` הוא באשמת הדפוס שהקורא שלח, ולעולם אינו חולף.
            # ‏``_transient_error`` היה הופך אותו ל-``sync_in_progress`` עם
            # ‏``retry_after`` — כלומר מבקש מהקורא לנסות שוב דפוס שייכשל זהה
            # לנצח. לכן הוא מנותב **לפני** הקריאה אליו, והיא עצמה לא משתנה:
            # יש לה עוד קוראים שהמיפוי הזה נכון עבורם.
            if engine_error == "invalid_pattern":
                return {
                    "ok": False,
                    "error": "invalid_pattern",
                    "query": query,
                    "message": str(res.get("message") or "")[:200],
                }
            if not res.get("results"):
                return self._transient_error(repo, "search_failed")
            # **כשל באמצע הזרם, אחרי שכבר נאספו שורות.** המנוע מחזיר אותן
            # יחד עם ``error`` כדי לא לזרוק התאמות אמיתיות — ועד היום השומר
            # שמעל בדק ``error and not results``, כלומר את המקרה הזה בדיוק
            # הוא הניח לעבור הלאה כתשובה **תקינה**: ``ok: true``,
            # ``truncated: false``, ובלי ``total`` ובלי ``total_at_least``.
            # ההשמטה השקטה שה-PR הזה בא לסלק, בתוך ה-PR עצמו.
            #
            # אם sync רץ, התוצאות החלקיות הן כנראה מעץ שזז מתחת לרגליים,
            # ו"נסה שוב מיד" עדיף על עמוד חלקי — אותה הכרעה כמו בשאר
            # המסלולים. אחרת מגישים את מה שיש, ואומרים בדיוק מה זה.
            if self._sync_running(repo):
                return self._transient_error(repo, "search_failed")
            logger.warning(
                "search served partial results after engine error %s: %s",
                engine_error, str(res.get("message") or "")[:200],
            )
            partial_failure = True

        # Last layer of the secrets policy. The engine already excluded these
        # paths from the scan (and therefore from the count), so this normally
        # removes nothing — it stays because a pattern the pathspec cannot
        # express must still not be served.
        rows = res.get("results") or []
        filtered = [r for r in rows if not is_denied(r.get("path", ""))]
        # Did this last layer actually remove something? It decides whether the
        # engine's count can still be called exact — see the total block below.
        policy_removed = len(filtered) != len(rows)
        # The cap is the engine's; slicing here is belt-and-braces on a list
        # that is already at most ``max_results`` long. The old
        # ``cap_truncated = total > len(capped)`` that sat here was dead code:
        # ``total`` was ``len(filtered)``, so it could never be true.
        capped = filtered[: max(0, _safe_int(max_results, 50))]

        out: list[dict[str, Any]] = []
        used = 0
        budget_truncated = False
        for r in capped:
            row = {
                "path": r.get("path"),
                "line": r.get("line"),
                "snippet": str(r.get("content") or "")[:500],
            }
            # שני המפתחות מתווספים אך ורק כשביקשו הקשר, כדי שתשובה ללא
            # ``context_lines`` תישאר זהה בדיוק לזו של היום.
            if context_lines > 0:
                row["context_before"] = [str(x)[:500] for x in (r.get("context_before") or [])]
                row["context_after"] = [str(x)[:500] for x in (r.get("context_after") or [])]
            used += len(str(row).encode("utf-8"))
            if used > byte_budget:
                budget_truncated = True
                break
            out.append(row)
        payload: dict[str, Any] = {
            "ok": True,
            "repo": repo,
            "query": query,
            "count": len(out),
            "results": out,
        }
        # Exactly one of the two, and never both: if ``total`` is there, it is
        # exact. ``total_at_least`` is the honest form of "we stopped counting".
        #
        # **And a row removed here costs us the exact number.** The engine
        # counted every file it scanned; a path it could not express as an
        # exclude pathspec was therefore scanned *and counted*, and only this
        # layer refused to serve it. Reporting that count as ``total`` would
        # claim a number that includes matches nobody can get — and would say
        # out loud how many matches sit inside a blocked file. What is left
        # that is certainly true is the rows we did serve, so that is the
        # bound we give.
        if policy_removed or partial_failure:
            # ``len(filtered)`` ולא ``count``: השורות שנאספו ועברו את המדיניות
            # קיימות בריפו גם אם תקציב הבתים לא הכניס את כולן לעמוד, ולכן
            # זה החסם התחתון הגדול ביותר שידוע בוודאות.
            payload["total_at_least"] = len(filtered)
        elif "total" in res:
            payload["total"] = res["total"]
        elif "total_at_least" in res:
            payload["total_at_least"] = res["total_at_least"]

        # An invariant of the answer, stated once here: if fewer rows came back
        # than exist, this answer is not everything — whatever the engine
        # flagged. ``count`` below the count next to ``truncated: false`` would
        # contradict itself.
        known = payload.get("total", payload.get("total_at_least"))
        truncated = bool(
            budget_truncated
            # A row removed here is a row the caller asked for and did not get.
            # Without this term the answer could carry ``truncated: false``
            # while the page is short — the silent omission this server refuses
            # everywhere else.
            or policy_removed
            # An engine that died mid-stream did not finish the scan, whatever
            # it managed to hand back first.
            or partial_failure
            or res.get("truncated")
            or (isinstance(known, int) and known > payload["count"])
        )
        payload["truncated"] = truncated

        # A reason only when something was in fact cut — a ``null`` on every
        # complete search would be noise in every answer. And **always** one
        # when it was: a flag without a reason sends the caller looking.
        if truncated:
            reason = res.get("truncation_reason")
            if policy_removed:
                # Stated over any upstream reason: it is the one that explains
                # why an exact ``total`` is missing from an answer whose count
                # finished normally.
                reason = "policy_filtered"
            elif partial_failure:
                # The engine's own error code, so the caller sees the same word
                # a full failure would have carried.
                reason = str(engine_error)
            elif not reason:
                # Nothing upstream was cut, so what shortened the page is local.
                reason = "byte_budget"
            payload["truncation_reason"] = reason
        return payload

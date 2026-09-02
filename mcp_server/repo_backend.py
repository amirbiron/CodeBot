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

import logging
from typing import Any

from .backend import _json_safe
from .repo_handlers import TREE_PER_PAGE_MAX
from .handlers import apply_line_range, normalize_line_range
from .repo_policy import is_denied

#: תקרת גודל נפרדת לקריאת טווח שורות.
#:
#: התקרה הרגילה של ``get_file_at_commit`` היא 500KB, והיא נבדקת **לפני**
#: הפענוח והחיתוך — ולכן ``lines`` לא עזר לקובץ גדול: הוא הוחזר כ-
#: ``too_large`` עם הפרמטר בדיוק כמו בלעדיו (#3317). ``webapp/app.py`` בן
#: 805,594 הבייטים, הקובץ שהכי הרבה עובדים עליו, היה בלתי קריא דרך הכלי.
#:
#: **למה תקרה אחרת ולא ביטול.** הבלוב עדיין נקרא ומפוענח במלואו לפני
#: החיתוך, אז "בלי תקרה" פירושו שקובץ פתולוגי בריפו יגיע ל-RAM כמו שהוא.
#: נמדד: קריאה ופענוח צורכים כפי שלושה מגודל הקובץ — 6.6MB הגיעו ל-35.7MB
#: שיא. תקרה של 10MB חוסמת את זה בערך ב-30MB, ונותנת פי 12 מרווח מעל
#: הקובץ הגדול ביותר שבאמת קוראים.
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
        if self._mirror is None:
            from services.git_mirror_service import get_mirror_service  # lazy heavy import

            self._mirror = get_mirror_service()
        return self._mirror

    def _require_search(self) -> Any:
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

    def _transient_error(self, repo_name: str, fallback: str) -> dict[str, Any]:
        """Map a failed read to sync_in_progress (retryable) when a sync runs."""
        if self._sync_running(repo_name):
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
    ) -> dict[str, Any]:
        if is_denied(path):  # policy: block, before touching the mirror
            return {"ok": False, "error": "path_denied"}
        # הטווח נבדק **לפני** הקריאה. כשהתקרה הייתה 500KB זה לא היה משנה,
        # כי קובץ גדול נפסל ממילא; עכשיו טווח פגום כמו ``[9, 2]`` היה גורם
        # לקריאה ולפענוח של עד 10MB רק כדי להיפסל בסוף. הבדיקה טהורה וזולה,
        # ואין סיבה שתרוץ אחרי העבודה היקרה.
        bounds: Any = None
        if lines is not None:
            # אותו עוזר משותף שמשרת גם את ``codekeeper_get_file``, כדי
            # ששני הכלים לא יסטו זה מזה בסמנטיקה.
            bounds = normalize_line_range(lines)
            if isinstance(bounds, str):
                return {"ok": False, "error": bounds}

        use_ref = ref or self._default_ref(repo)
        # רק לקריאת טווח. בלי ``lines`` לא מועבר ``max_size`` כלל, כך
        # שברירת המחדל של שירות המראה נשארת מקור האמת היחיד ל-500KB —
        # ושתי ההתנהגויות לא נפרדות לשני מספרים שצריך לסנכרן.
        size_kwargs = {"max_size": RANGE_READ_MAX_BYTES} if lines is not None else {}
        try:
            res = self._require_mirror().get_file_at_commit(
                repo, path, use_ref, **size_kwargs
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
        fallback = "not_found" if err in ("repo_not_found", "invalid_commit") else "read_failed"
        return self._transient_error(repo, fallback)

    def search(
        self,
        *,
        repo: str,
        query: str,
        file_pattern: str | None = None,
        max_results: int = 50,
        byte_budget: int = 256_000,
        context_lines: int = 0,
    ) -> dict[str, Any]:
        try:
            res = self._require_search().search(
                repo,
                query,
                search_type="content",
                file_pattern=(file_pattern or None),
                max_results=int(max_results),
                context_lines=int(context_lines),
            )
        except Exception:
            logger.warning("search failed", exc_info=True)
            return self._transient_error(repo, "search_failed")
        if res.get("error") and not res.get("results"):
            return self._transient_error(repo, "search_failed")

        # total reflects what we can actually serve: the policy-filtered matches
        # (NOT the engine's raw total, which may count denied paths).
        filtered = [r for r in (res.get("results") or []) if not is_denied(r.get("path", ""))]
        total = len(filtered)
        capped = filtered[: max(0, _safe_int(max_results, 50))]  # cap TOTAL matches
        cap_truncated = total > len(capped)

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
        return {
            "ok": True,
            "repo": repo,
            "query": query,
            "count": len(out),
            "total": total,
            "results": out,
            "truncated": bool(cap_truncated or budget_truncated or res.get("truncated")),
        }

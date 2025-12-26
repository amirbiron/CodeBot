"""
MongoDB-backed alerts storage with TTL and simple counters.

Design goals:
- Fail-open: never throw from public APIs
- Lazy init: connect to Mongo only on first use
- Config via env only (avoid importing global config to prevent cycles)
- TTL-based retention (default 30 days) to keep the collection bounded

Environment variables:
- ALERTS_DB_ENABLED: "true/1/yes" to enable writes (fallback to METRICS_DB_ENABLED)
- MONGODB_URL: required when enabled
- DATABASE_NAME: DB name (default: code_keeper_bot)
- ALERTS_COLLECTION: Collection name (default: alerts_log)
- ALERTS_TTL_DAYS: TTL for documents (default: 30)

Public API:
- record_alert(alert_id, name, severity, summary, source) -> None
- count_alerts_since(since_dt) -> tuple[int, int]
- count_alerts_last_hours(hours=24) -> tuple[int, int]
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import os
import re


def _is_true(val: Optional[str]) -> bool:
    return str(val or "").lower() in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    # Explicit opt-in wins over global disable to support tests and targeted writes
    if _is_true(os.getenv("ALERTS_DB_ENABLED")):
        return True
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    # Fall back to metrics DB flag when explicit alerts flag is not set
    return _is_true(os.getenv("METRICS_DB_ENABLED"))


_client = None  # type: ignore
_collection = None  # type: ignore
_catalog_collection = None  # type: ignore
_init_failed = False

_SENSITIVE_DETAIL_KEYS = {
    "token",
    "password",
    "secret",
    "authorization",
    "auth",
    "email",
    "phone",
    "session",
    "cookie",
}
_ENDPOINT_HINT_KEYS = ("endpoint", "path", "route", "url", "request_path")
_ALERT_TYPE_HINT_KEYS = ("alert_type", "type", "category", "kind")
_DETAIL_TEXT_LIMIT = 512


def _safe_str(value: Any, *, limit: int = 256) -> str:
    try:
        # חשוב: לא להשתמש ב-`value or ""` כי ערכים "שקריים" (כמו 0, False, [], {})
        # יהפכו בטעות למחרוזת ריקה ויגרמו לאיבוד מידע בלוח ה-Observability.
        if value is None:
            text = ""
        else:
            text = str(value).strip()
    except Exception:
        text = ""
    if limit and len(text) > limit:
        return text[:limit]
    return text


def _sanitize_details(details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    שמירה "Fail-open" של details עבור DB/UI, בלי למחוק שדות.

    עקרונות:
    - לא מוחקים מפתחות (כולל sentry_issue_id/labels/slow_endpoints וכו').
    - מפתחות רגישים נשמרים אבל הערך שלהם נכתב כ-<REDACTED> במקום להיעלם.
    - שומרים טיפוסים של dict/list כדי לא להפוך אותם למחרוזות ריקות (למשל []/{}).
    - מגבילים רק מחרוזות ארוכות, ובמקרים חריגים ממירים לאובייקט ניתן-ייצוג.
    """
    if not isinstance(details, dict):
        return {}

    seen: set[int] = set()

    def _sanitize_value(key_hint: str, value: Any, *, depth: int) -> Any:
        # Redact by key name (case-insensitive) but do not drop the key
        try:
            lk = str(key_hint).lower()
        except Exception:
            lk = ""
        if lk in _SENSITIVE_DETAIL_KEYS:
            return "<REDACTED>"

        # Preserve explicit None (do not delete keys)
        if value is None:
            return None

        # Keep primitives as-is (Mongo-friendly)
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            return _safe_str(value, limit=_DETAIL_TEXT_LIMIT)

        # Preserve dict/list structures (and sanitize recursively).
        # חשוב: לא לקרוא ל-_safe_str על dict/list/tuple גם במצב depth limit,
        # כדי לא להפוך אובייקטים מורכבים למחרוזות "שבורות" ב-UI.
        if isinstance(value, (dict, list, tuple)):
            if depth <= 0:
                # שומרים טיפוס ומחזירים עותק שטוח (בלי רקורסיה נוספת)
                # כדי למנוע Data Corruption: לא "לאפס" ל-{} / [] ולא להמיר ל-str().
                try:
                    if isinstance(value, dict):
                        # חשוב: גם בקצה העומק חייבים לבצע Redaction שטחי למפתחות רגישים,
                        # אחרת סודות (password/token/secret וכו') יכולים לדלוף.
                        out: Dict[str, Any] = {}
                        for k, v in value.items():
                            try:
                                sk = str(k)
                            except Exception:
                                sk = "<unprintable-key>"
                            try:
                                lk = sk.lower()
                            except Exception:
                                lk = ""
                            if lk in _SENSITIVE_DETAIL_KEYS:
                                out[sk] = "<REDACTED>"
                            else:
                                out[sk] = v
                        return out
                    if isinstance(value, list):
                        return list(value)
                    # tuple -> list (Mongo-friendly)
                    return list(value)
                except Exception:
                    # Fail-open: אם אפילו העתקה שטוחה נכשלת, נחזיר מבנה ריק בטוח
                    return {} if isinstance(value, dict) else []

            try:
                obj_id = id(value)
            except Exception:
                obj_id = 0
            if obj_id and obj_id in seen:
                return "<CYCLE>"
            if obj_id:
                seen.add(obj_id)
            try:
                if isinstance(value, dict):
                    out: Dict[str, Any] = {}
                    for k2, v2 in value.items():
                        out[str(k2)] = _sanitize_value(str(k2), v2, depth=depth - 1)
                    return out
                if isinstance(value, list):
                    return [_sanitize_value(key_hint, v2, depth=depth - 1) for v2 in value]
                # tuple -> list (Mongo-friendly)
                return [_sanitize_value(key_hint, v2, depth=depth - 1) for v2 in list(value)]
            finally:
                # Do not try to remove from seen; cycle protection is best-effort.
                pass

        if depth <= 0:
            return _safe_str(value, limit=_DETAIL_TEXT_LIMIT)

        # Fallback: safe string representation
        return _safe_str(value, limit=_DETAIL_TEXT_LIMIT)

    clean: Dict[str, Any] = {}
    for key, value in details.items():
        # Never drop keys – stringify key best-effort
        try:
            sk = str(key)
        except Exception:
            sk = "<unprintable-key>"
        clean[sk] = _sanitize_value(sk, value, depth=6)
    return clean


def _extract_endpoint(details: Dict[str, Any]) -> Optional[str]:
    for key in _ENDPOINT_HINT_KEYS:
        try:
            value = details.get(key)
        except Exception:
            continue
        if value not in (None, ""):
            text = _safe_str(value, limit=256)
            if text:
                return text
    return None


def _extract_alert_type(name: str, details: Dict[str, Any]) -> Optional[str]:
    for key in _ALERT_TYPE_HINT_KEYS:
        try:
            value = details.get(key)
        except Exception:
            continue
        if value not in (None, ""):
            return _safe_str(value, limit=128).lower()
    if name and name.lower() == "deployment_event":
        return "deployment_event"
    return None


def _extract_duration(details: Dict[str, Any]) -> Optional[float]:
    for key in ("duration_seconds", "duration", "duration_secs", "duration_ms"):
        try:
            value = details.get(key)
        except Exception:
            continue
        if value in (None, ""):
            continue
        try:
            num = float(value)
        except Exception:
            continue
        if key.endswith("_ms"):
            num = num / 1000.0
        if num >= 0:
            return num
    return None


def _build_search_blob(name: str, summary: str, details: Dict[str, Any]) -> str:
    parts = [name or "", summary or ""]
    if details:
        for key, value in details.items():
            try:
                parts.append(f"{key}:{value}")
            except Exception:
                continue
    text = " | ".join(part for part in parts if part)
    return _safe_str(text, limit=2048)


def _build_time_filter(start_dt: Optional[datetime], end_dt: Optional[datetime]) -> Dict[str, Any]:
    if not start_dt and not end_dt:
        return {}
    match: Dict[str, Any] = {}
    window: Dict[str, Any] = {}
    if start_dt:
        window["$gte"] = start_dt
    if end_dt:
        window["$lte"] = end_dt
    if window:
        match["ts_dt"] = window
    return match


def _get_collection():  # pragma: no cover - exercised indirectly
    global _client, _collection, _init_failed
    if _collection is not None or _init_failed:
        return _collection

    if not _enabled():
        _init_failed = True
        return None

    try:
        try:
            from pymongo import MongoClient  # type: ignore
            from pymongo import ASCENDING  # type: ignore
        except Exception:
            _init_failed = True
            return None

        # Allow tests/environments without explicit URL to fall back to localhost.
        # This keeps public APIs fail-open and enables unit-test fakes for pymongo.
        mongo_url = os.getenv("MONGODB_URL") or "mongodb://localhost:27017"

        db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
        coll_name = os.getenv("ALERTS_COLLECTION") or "alerts_log"

        _client = MongoClient(
            mongo_url,
            maxPoolSize=20,
            minPoolSize=0,
            serverSelectionTimeoutMS=2000,
            socketTimeoutMS=5000,
            connectTimeoutMS=2000,
            retryWrites=True,
            retryReads=True,
        )
        db = _client[db_name]
        _collection = db[coll_name]
        # Best-effort ping
        try:
            _client.admin.command("ping")
        except Exception:
            pass

        # Ensure indexes (best-effort). TTL requires a Date field.
        try:
            try:
                ttl_days = int(os.getenv("ALERTS_TTL_DAYS", "30") or "30")
            except Exception:
                ttl_days = 30
            # TTL cannot be updated in-place; ignore errors if it already exists differently.
            if ttl_days > 0:
                _collection.create_index([("ts_dt", ASCENDING)], expireAfterSeconds=ttl_days * 24 * 3600)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            _collection.create_index([("_key", ASCENDING)], unique=True, sparse=True)  # type: ignore[attr-defined]
        except Exception:
            pass

        return _collection
    except Exception:
        _init_failed = True
        return None


def _get_catalog_collection():  # pragma: no cover - exercised indirectly
    """Return (and lazily create) the alert types catalog collection."""
    global _catalog_collection
    if _catalog_collection is not None or _init_failed:
        return _catalog_collection
    # Ensure base client is initialized (same DB/cluster settings)
    try:
        coll = _get_collection()
        if coll is None:
            return None
    except Exception:
        return None
    try:
        # Reuse the same client/db, create a separate collection
        db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
        catalog_name = os.getenv("ALERT_TYPES_CATALOG_COLLECTION") or "alert_types_catalog"
        db = _client[db_name]  # type: ignore[index]
        _catalog_collection = db[catalog_name]
        # Best-effort indexes
        try:
            from pymongo import ASCENDING  # type: ignore

            _catalog_collection.create_index([("alert_type", ASCENDING)], unique=True)  # type: ignore[attr-defined]
            _catalog_collection.create_index([("last_seen_dt", ASCENDING)])  # type: ignore[attr-defined]
        except Exception:
            pass
        return _catalog_collection
    except Exception:
        return None


def _isoformat_utc(value: Optional[datetime]) -> Optional[str]:
    """Return ISO string with UTC tzinfo for Mongo datetimes."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        dt = value.replace(tzinfo=timezone.utc)
    else:
        try:
            dt = value.astimezone(timezone.utc)
        except Exception:
            dt = value.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _build_key(alert_id: Optional[str], name: str, severity: str, summary: str, ts_dt: datetime) -> str:
    if alert_id:
        return f"id:{alert_id}"
    # Fallback: stable hash by minute bucket
    minute_bucket = ts_dt.replace(second=0, microsecond=0).isoformat()
    raw = "|".join([name.strip(), severity.strip().lower(), summary.strip(), minute_bucket])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"h:{digest}"


def compute_error_signature(error_data: Dict[str, Any]) -> str:
    """
    מחשב חתימה ייחודית לשגיאה.

    החתימה מבוססת על:
    - סוג השגיאה
    - שם הקובץ והשורה (אם יש)
    - 3 השורות הראשונות של ה-stack trace
    """
    try:
        def _deep_find_first_string(
            d: Any,
            keys: Tuple[str, ...],
            *,
            max_depth: int = 10,
            max_nodes: int = 2000,
        ) -> str:
            """
            Best-effort deep search for a string-like value by keys.

            Important: used to find sentry_issue_id even when nested under error_data/details/metadata.
            """
            if max_depth < 0 or max_nodes <= 0:
                return ""

            keys_lower = {(_safe_str(k, limit=128) or "").lower() for k in keys if k}
            if not keys_lower:
                return ""

            visited: set[int] = set()
            stack: List[Tuple[Any, int]] = [(d, 0)]
            nodes = 0

            while stack:
                current, depth = stack.pop()
                nodes += 1
                if nodes > max_nodes:
                    break

                # Cycle protection for containers
                if isinstance(current, (dict, list, tuple)):
                    try:
                        oid = id(current)
                    except Exception:
                        oid = 0
                    if oid and oid in visited:
                        continue
                    if oid:
                        visited.add(oid)

                if isinstance(current, dict):
                    # 1) Check direct keys
                    try:
                        items = list(current.items())
                    except Exception:
                        items = []
                    for k, v in items:
                        try:
                            k_norm = str(k).lower()
                        except Exception:
                            continue
                        if k_norm in keys_lower and v not in (None, ""):
                            # חשוב: אל תהפוך dict/list ל-str כאן; אנחנו מחפשים מזהה יציב (string/int).
                            if isinstance(v, (dict, list, tuple)):
                                # נמשיך לחיפוש פנימה במקום להמיר ל-str
                                pass
                            else:
                                try:
                                    stripped = str(v).strip()
                                except Exception:
                                    stripped = ""
                                if stripped:
                                    return stripped

                        # 2) Recurse into nested payloads (generic, not allowlist בלבד)
                        if depth < max_depth and isinstance(v, (dict, list, tuple)):
                            stack.append((v, depth + 1))

                elif isinstance(current, (list, tuple)):
                    if depth >= max_depth:
                        continue
                    try:
                        seq = list(current)
                    except Exception:
                        seq = []
                    for v in seq:
                        if isinstance(v, (dict, list, tuple)):
                            stack.append((v, depth + 1))
                else:
                    continue

            return ""

        def _normalize_error_text(text: Any) -> str:
            """
            Normalize error/trace text before hashing to keep signatures stable across:
            - dynamic hex memory addresses (0x7f...)
            - absolute file paths that differ between environments
            - noisy line numbers (optional)
            """
            if text in (None, ""):
                return ""
            try:
                s = str(text)
            except Exception:
                return ""

            # Normalize line endings
            s = s.replace("\r\n", "\n").replace("\r", "\n")

            # Replace hex memory addresses (0x7f..., 0x0000...)
            s = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", s)

            def _normalize_inline_absolute_paths(value: str) -> str:
                """
                Replace absolute path tokens inside free-form text with their basename.

                Implemented as a linear scan (no regex) to avoid ReDoS/CodeQL warnings.
                """
                exts = (".py", ".js", ".ts", ".tsx", ".java", ".go", ".rb")
                start_delims = set(" \t\r\n\"'([{<,;=|")
                # Stop token at whitespace, quotes, and common punctuation around paths in tracebacks/logs
                stop_chars = set(" \t\r\n\"'([{<,;|)]}>")

                def _has_known_ext(filename: str) -> bool:
                    try:
                        low = filename.lower()
                    except Exception:
                        return False
                    return any(low.endswith(ext) for ext in exts)

                def _basename(path_like: str) -> str:
                    # Keep only the last path segment (works for both / and \)
                    if "/" in path_like:
                        path_like = path_like.rsplit("/", 1)[-1]
                    if "\\" in path_like:
                        path_like = path_like.rsplit("\\", 1)[-1]
                    return path_like

                out: List[str] = []
                i = 0
                n = len(value)
                while i < n:
                    ch = value[i]

                    # Detect start of absolute path token
                    start = None
                    if ch == "/" and (i == 0 or value[i - 1] in start_delims):
                        start = i
                    elif (
                        ch.isalpha()
                        and i + 2 < n
                        and value[i + 1] == ":"
                        and value[i + 2] == "\\"
                        and (i == 0 or value[i - 1] in start_delims)
                    ):
                        start = i

                    if start is None:
                        out.append(ch)
                        i += 1
                        continue

                    j = start
                    while j < n and value[j] not in stop_chars:
                        j += 1
                    token = value[start:j]

                    # Handle optional trailing :<digits> (line numbers), normalize digits to <LINE>
                    line_suffix = ""
                    k = token.rfind(":")
                    if k != -1 and k + 1 < len(token):
                        tail = token[k + 1 :]
                        if tail.isdigit():
                            token_base = token[:k]
                            line_suffix = ":<LINE>"
                        else:
                            token_base = token
                    else:
                        token_base = token

                    candidate = _basename(token_base)
                    if _has_known_ext(candidate):
                        out.append(candidate + line_suffix)
                    else:
                        # Not a filename token we recognize; keep original
                        out.append(value[start:j])
                    i = j

                return "".join(out)

            # Normalize inline absolute paths without regex (safe for untrusted input)
            try:
                s = _normalize_inline_absolute_paths(s)
            except Exception:
                pass

            # Normalize common traceback patterns: `File "...", line 123`
            s = re.sub(r"\bline\s+\d+\b", "line <LINE>", s)

            # Normalize file:line patterns for Python files
            s = re.sub(r"(\b[\w.\-]+\.py):\d+\b", r"\1:<LINE>", s)

            # Collapse excessive spaces/tabs (keep newlines)
            s = re.sub(r"[ \t]+", " ", s).strip()
            return s

        def _normalize_file_name(value: Any) -> str:
            if value in (None, ""):
                return ""
            try:
                s = str(value).strip()
            except Exception:
                return ""
            if not s:
                return ""
            # Keep only basename for stability across environments
            if "/" in s:
                s = s.rsplit("/", 1)[-1]
            if "\\" in s:
                s = s.rsplit("\\", 1)[-1]
            return s

        # --- Sentry-first: כשמדובר בשגיאת Sentry, יש לנו מזהה יציב (Issue ID) ---
        # זה מונע יצירת חתימות ריקות ומאפשר עקביות גם כשאין stack/file.
        sentry_issue_id_raw = _deep_find_first_string(
            error_data or {},
            (
                "sentry_issue_id",
                "sentryIssueId",
                "issue_id",
                "issueId",
                "sentry_issue",
            ),
            max_depth=10,
        )
        sentry_issue_id = _normalize_error_text(sentry_issue_id_raw or "")
        if sentry_issue_id:
            signature_input = f"sentry_issue_id:{sentry_issue_id}"
            return hashlib.sha256(signature_input.encode()).hexdigest()[:16]

        # --- Generic error signature (code/runtime errors) ---
        components = [
            str((error_data or {}).get("error_type", "") or ""),
            _normalize_file_name((error_data or {}).get("file", "") or ""),
            str((error_data or {}).get("line", "") or ""),
        ]

        # Include summary/title when present (useful for Sentry-like alerts that don't carry stack)
        summary = _normalize_error_text(
            (error_data or {}).get("summary")
            or (error_data or {}).get("title")
            or (error_data or {}).get("message")
            or ""
        )
        if summary:
            components.append(summary)

        # Include normalized message when present (improves signal when stack/file info is missing)
        error_message = _normalize_error_text((error_data or {}).get("error_message", "") or "")
        if error_message:
            components.append(error_message)

        # הוספת stack trace מנורמל
        stack = _normalize_error_text((error_data or {}).get("stack_trace", "") or "")
        if stack:
            # לקיחת 3 שורות ראשונות
            lines = [l.strip() for l in str(stack).split("\n") if l.strip()][:3]
            components.extend(lines)

        signature_input = "|".join(components)
        # אם אין לנו שום מידע יציב (כל הערכים ריקים) — לא נחשב חתימה, כדי לא לייצר hash קבוע
        # שיגרום לכל ההתראות "לחלוק" אותה חתימה ולשבור is_new_error.
        try:
            has_signal = any(bool(str(c).strip()) for c in components)
        except Exception:
            has_signal = False
        if not has_signal:
            return ""
        return hashlib.sha256(signature_input.encode()).hexdigest()[:16]
    except Exception:
        # Fail-open: return a stable fallback
        try:
            return hashlib.sha256(str(error_data).encode()).hexdigest()[:16]
        except Exception:
            return "0" * 16


def is_new_error(signature: str) -> bool:
    """בודק אם השגיאה חדשה (לא נראתה ב-30 יום האחרונים)."""
    if not signature:
        return False
    if not _enabled() or _init_failed:
        return False
    try:
        # ודא שהלקוח מאותחל (best-effort)
        _ = _get_collection()
        if _client is None:
            return False
        db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
        collection = _client[db_name]["error_signatures"]

        # best-effort indexes
        try:
            from pymongo import ASCENDING  # type: ignore
            collection.create_index([("signature", ASCENDING)], unique=True, background=True)
            collection.create_index([("last_seen", ASCENDING)], background=True)
        except Exception:
            pass

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)

        existing = collection.find_one({"signature": signature, "last_seen": {"$gte": cutoff}})

        # עדכון/הוספת הרשומה
        collection.update_one(
            {"signature": signature},
            {
                "$set": {"last_seen": datetime.now(timezone.utc)},
                "$inc": {"count": 1},
                "$setOnInsert": {"first_seen": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

        return existing is None
    except Exception:
        return False


def enrich_alert_with_signature(alert_data: Dict[str, Any]) -> Dict[str, Any]:
    """מעשיר את נתוני ההתראה עם חתימה ומידע על חדשות."""
    # חשוב: בפרויקט כבר ייתכן שדה error_signature עם מזהה "טקסונומי" (למשל OOM_KILLED).
    # אסור לדרוס אותו. את ה-fingerprint (hash) נשמור בשדה נפרד.
    # קריאה בטוחה לשדות קיימים (לא להניח dict "נקי")
    try:
        existing_is_new = alert_data.get("is_new_error")
    except Exception:
        existing_is_new = None
    try:
        existing_hash = alert_data.get("error_signature_hash")
    except Exception:
        existing_hash = None

    # השתמש ב-hash קיים רק אם הוא באמת מכיל תוכן (מניעת שדות ריקים שנוצרו בעבר)
    signature_hash_existing = _safe_str(existing_hash, limit=128)
    signature_hash = signature_hash_existing
    if not signature_hash:
        signature_hash = _safe_str(compute_error_signature(alert_data or {}), limit=128)

    # אם אין חתימה אמיתית – לא מוסיפים שדות Signature כלל (וגם מנקים שדות ריקים אם קיימים)
    if not signature_hash:
        try:
            if not _safe_str(alert_data.get("error_signature_hash"), limit=128):
                alert_data.pop("error_signature_hash", None)
        except Exception:
            pass
        try:
            # אל תדרוס error_signature "טקסונומי", אבל אם הוא ריק – ננקה אותו
            if not _safe_str(alert_data.get("error_signature"), limit=128):
                alert_data.pop("error_signature", None)
        except Exception:
            pass
        try:
            # אם הוסיפו בעבר is_new_error=False בלי חתימה, עדיף לא לשמור אותו בכלל
            if alert_data.get("is_new_error") in (False, None, ""):
                alert_data.pop("is_new_error", None)
        except Exception:
            pass
        return alert_data

    # Idempotency: רק אם היה כבר hash קיים וגם is_new_error קיים, לא ניגשים שוב ל-DB.
    # אם מישהו הגיע עם is_new_error=True אבל בלי hash (למשל sentry_polling), אסור "לסמוך" על זה.
    if existing_is_new in (True, False) and bool(signature_hash_existing):
        is_new = bool(existing_is_new)
    else:
        is_new = is_new_error(signature_hash)

    # הוספה בלבד: לא יוצרים dict חדש, לא דורסים Metadata קיים
    alert_data["error_signature_hash"] = signature_hash
    alert_data["is_new_error"] = is_new

    # תאימות: אם אין error_signature קיים (או שהוא ריק) נשתמש ב-hash כברירת מחדל.
    # אם קיים מזהה טקסונומי (למשל OOM_KILLED) – לא נוגעים.
    try:
        existing = alert_data.get("error_signature")
    except Exception:
        existing = None
    if existing in (None, "", False):
        alert_data["error_signature"] = signature_hash

    return alert_data


def record_alert(
    *,
    alert_id: Optional[str],
    name: str,
    severity: str,
    summary: str = "",
    source: str = "",
    silenced: bool = False,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert (or upsert via unique key) a single alert record.

    - When alert_id is provided, use it for de-duplication via a unique key.
    - Otherwise use a stable hash based on name/severity/summary/minute.
    """
    if not _enabled() or _init_failed:
        return
    try:
        coll = _get_collection()
        if coll is None:
            return
        now = datetime.now(timezone.utc)
        key = _build_key(alert_id, name or "", severity or "", summary or "", now)
        # חשוב: קודם enrich על המטען הגולמי, ורק אחר כך sanitize ל-DB.
        # זה מונע מצב שבו dict/list נהרסים לפני חישוב החתימה (למשל sentry_issue_id שנמצא במבנה מקונן).
        details_payload: Dict[str, Any] = dict(details or {}) if isinstance(details, dict) else {}
        try:
            enrich_alert_with_signature(details_payload)
        except Exception:
            pass
        clean_details = _sanitize_details(details_payload)
        endpoint = _extract_endpoint(clean_details) if clean_details else None
        alert_type = _extract_alert_type(str(name or ""), clean_details)
        duration_seconds = _extract_duration(clean_details)
        search_blob = _build_search_blob(str(name or ""), str(summary or ""), clean_details)

        doc = {
            "ts_dt": now,
            "name": str(name or "alert"),
            "severity": str(severity or "info").lower(),
            "summary": str(summary or ""),
            "source": str(source or ""),
            "_key": key,
            "search_blob": search_blob,
        }
        # Transparency: mark whether this alert was silenced at dispatch time
        try:
            doc["silenced"] = bool(silenced)
        except Exception:
            doc["silenced"] = False
        if clean_details:
            doc["details"] = clean_details
        if endpoint:
            doc["endpoint"] = endpoint
        if alert_type:
            doc["alert_type"] = alert_type
        if duration_seconds is not None:
            doc["duration_seconds"] = float(duration_seconds)
        if alert_id:
            doc["alert_id"] = str(alert_id)
        try:
            # Upsert by key (idempotent). Using update_one for better semantics with unique key.
            coll.update_one({"_key": key}, {"$setOnInsert": doc}, upsert=True)  # type: ignore[attr-defined]
        except Exception:
            # Fall back to insert (ignore dup errors silently)
            try:
                coll.insert_one(doc)  # type: ignore[attr-defined]
            except Exception:
                pass

        # --- Catalog (Registry): persist observed alert_type forever (best-effort) ---
        try:
            # Do not pollute catalog with drills
            if clean_details and bool(clean_details.get("is_drill")):
                return
        except Exception:
            pass
        try:
            if alert_type:
                _upsert_alert_type_catalog(
                    alert_type=alert_type,
                    name=str(name or "alert"),
                    summary=str(summary or ""),
                    seen_dt=now,
                )
        except Exception:
            pass
    except Exception:
        return


def _upsert_alert_type_catalog(
    *,
    alert_type: str,
    name: str,
    summary: str,
    seen_dt: datetime,
) -> None:
    coll = _get_catalog_collection()
    if coll is None:
        return
    key = _safe_str(alert_type, limit=128).lower()
    if not key:
        return
    now = seen_dt if isinstance(seen_dt, datetime) else datetime.now(timezone.utc)
    payload = {
        "alert_type": key,
        "last_seen_dt": now,
        "last_seen_name": _safe_str(name, limit=128),
        "last_seen_summary": _safe_str(summary, limit=256),
        "updated_at": now,
    }
    try:
        coll.update_one(
            {"alert_type": key},
            {
                "$setOnInsert": {"first_seen_dt": now, "created_at": now},
                "$set": payload,
                "$inc": {"total_count": 1},
            },
            upsert=True,
        )  # type: ignore[attr-defined]
    except Exception:
        return


def fetch_alert_type_catalog(
    *,
    min_total_count: int = 1,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    """Return catalog of all observed alert types (fail-open).

    Each row includes:
      alert_type, total_count, first_seen_dt, last_seen_dt, sample_name, sample_title
    """
    coll = _get_catalog_collection()
    if coll is None:
        return []
    try:
        min_total = int(min_total_count)
    except Exception:
        min_total = 1
    min_total = max(1, min_total)
    try:
        lim = int(limit)
    except Exception:
        lim = 5000
    lim = max(1, min(50_000, lim))
    try:
        match: Dict[str, Any] = {"total_count": {"$gte": min_total}}
        cursor = (
            coll.find(
                match,
                {
                    "_id": 0,
                    "alert_type": 1,
                    "total_count": 1,
                    "first_seen_dt": 1,
                    "last_seen_dt": 1,
                    "last_seen_name": 1,
                    "last_seen_summary": 1,
                },
            )  # type: ignore[attr-defined]
            .sort([("last_seen_dt", -1)])  # type: ignore[attr-defined]
            .limit(lim)  # type: ignore[attr-defined]
        )
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    try:
        for doc in cursor:
            try:
                a_type = _safe_str(doc.get("alert_type"), limit=128).lower()
                if not a_type:
                    continue
                out.append(
                    {
                        "alert_type": a_type,
                        "count": int(doc.get("total_count", 0) or 0),
                        "first_seen_dt": doc.get("first_seen_dt"),
                        "last_seen_dt": doc.get("last_seen_dt"),
                        "sample_name": _safe_str(doc.get("last_seen_name"), limit=128),
                        "sample_title": _safe_str(doc.get("last_seen_summary"), limit=256),
                    }
                )
            except Exception:
                continue
    except Exception:
        return []
    return out


def fetch_alerts_by_type(
    *,
    alert_type: str,
    limit: int = 100,
    include_details: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch recent alerts of a specific type with Sentry details.

    Returns a list of dicts, for example::

        {
          "alert_id": str,
          "ts_dt": datetime,
          "name": str,
          "summary": str,
          "sentry_issue_id": Optional[str],
          "sentry_permalink": Optional[str],
          "sentry_short_id": Optional[str],
        }
    """
    coll = _get_collection()
    if coll is None:
        return []

    normalized_type = _safe_str(alert_type, limit=128).lower()
    if not normalized_type:
        return []

    try:
        limit_int = max(1, min(500, int(limit)))
    except Exception:
        limit_int = 100

    safe_pattern = re.escape(normalized_type)
    match = {
        "alert_type": {"$regex": f"^{safe_pattern}$", "$options": "i"},
        "details.is_drill": {"$ne": True},
    }

    projection = {
        "_id": 0,
        "alert_id": 1,
        "ts_dt": 1,
        "name": 1,
        "summary": 1,
    }

    if include_details:
        projection["details.sentry_issue_id"] = 1
        projection["details.sentry_permalink"] = 1
        projection["details.sentry_short_id"] = 1
        projection["details.error_signature"] = 1

    try:
        cursor = coll.find(match, projection).sort([("ts_dt", -1)]).limit(limit_int)  # type: ignore[attr-defined]
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for doc in cursor:
        try:
            details = doc.get("details") or {}
            out.append(
                {
                    "alert_id": str(doc.get("alert_id") or ""),
                    "ts_dt": doc.get("ts_dt"),
                    "name": _safe_str(doc.get("name"), limit=128),
                    "summary": _safe_str(doc.get("summary"), limit=256),
                    "sentry_issue_id": _safe_str(details.get("sentry_issue_id"), limit=64),
                    "sentry_permalink": _safe_str(details.get("sentry_permalink"), limit=512),
                    "sentry_short_id": _safe_str(details.get("sentry_short_id"), limit=32),
                    "error_signature": _safe_str(details.get("error_signature"), limit=128),
                }
            )
        except Exception:
            continue
    return out


def count_alerts_since(since_dt: datetime) -> tuple[int, int]:
    """Return (total, critical) counts since the given datetime (UTC recommended)."""
    if not _enabled() or _init_failed:
        return 0, 0
    try:
        coll = _get_collection()
        if coll is None:
            return 0, 0
        match: Dict[str, Any] = {"ts_dt": {"$gte": since_dt}}
        # Default: exclude Drill alerts from stats to prevent metric pollution
        match["details.is_drill"] = {"$ne": True}
        total = int(coll.count_documents(match))  # type: ignore[attr-defined]
        critical = int(
            coll.count_documents(
                {
                    **match,
                    "severity": {"$regex": "^critical$", "$options": "i"},
                }
            )  # type: ignore[attr-defined]
        )
        return total, critical
    except Exception:
        return 0, 0


def count_alerts_last_hours(hours: int = 24) -> tuple[int, int]:
    if hours <= 0:
        return 0, 0
    since = datetime.now(timezone.utc) - timedelta(hours=int(hours))
    return count_alerts_since(since)


def list_recent_alert_ids(limit: int = 10) -> List[str]:
    """Return recent alert identifiers from the DB (fail-open).

    Preference order: document ``alert_id`` when present, otherwise the
    stable unique ``_key`` used for de-duplication. Results are ordered by
    ``ts_dt`` descending and truncated to ``limit``.
    """
    if not _enabled() or _init_failed:
        return []
    try:
        coll = _get_collection()
        if coll is None:
            return []
        try:
            # Projection keeps payload small; sorting by time desc
            cursor = (
                coll.find({}, {"alert_id": 1, "_key": 1, "ts_dt": 1})  # type: ignore[attr-defined]
                .sort([("ts_dt", -1)])  # type: ignore[attr-defined]
                .limit(max(1, min(200, int(limit or 10))))  # type: ignore[attr-defined]
            )
        except Exception:
            return []
        out: List[str] = []
        try:
            for doc in cursor:  # type: ignore[assignment]
                try:
                    ident = doc.get("alert_id") or doc.get("_key")
                    if ident:
                        out.append(str(ident))
                except Exception:
                    continue
        except Exception:
            return []
        return out
    except Exception:
        return []


def fetch_alerts(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    severity: Optional[str] = None,
    alert_type: Optional[str] = None,
    endpoint: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return paginated alert documents filtered by the provided criteria."""
    coll = _get_collection()
    if coll is None:
        return [], 0

    try:
        per_page = max(1, min(200, int(per_page)))
    except Exception:
        per_page = 50
    try:
        page = max(1, int(page))
    except Exception:
        page = 1
    skip = (page - 1) * per_page

    match = _build_time_filter(start_dt, end_dt)
    if severity:
        match["severity"] = str(severity).lower()
    if alert_type:
        match["alert_type"] = str(alert_type).lower()
    if endpoint:
        match["endpoint"] = str(endpoint)
    if search:
        pattern = _safe_str(search, limit=256)
        if pattern:
            match["$or"] = [
                {"name": {"$regex": pattern, "$options": "i"}},
                {"summary": {"$regex": pattern, "$options": "i"}},
                {"search_blob": {"$regex": pattern, "$options": "i"}},
            ]

    projection = {
        "_id": 0,
        "ts_dt": 1,
        "name": 1,
        "severity": 1,
        "summary": 1,
        "details": 1,
        "duration_seconds": 1,
        "alert_type": 1,
        "endpoint": 1,
        "source": 1,
        "silenced": 1,
    }

    try:
        cursor = (
            coll.find(match, projection)  # type: ignore[attr-defined]
            .sort("ts_dt", -1)  # type: ignore[attr-defined]
            .skip(skip)  # type: ignore[attr-defined]
            .limit(per_page)  # type: ignore[attr-defined]
        )
    except Exception:
        return [], 0

    alerts: List[Dict[str, Any]] = []
    for doc in cursor:
        ts = doc.get("ts_dt")
        ts_iso = _isoformat_utc(ts)
        alerts.append(
            {
                "timestamp": ts_iso,
                "name": doc.get("name"),
                "severity": doc.get("severity"),
                "summary": doc.get("summary"),
                "metadata": doc.get("details") or {},
                "duration_seconds": doc.get("duration_seconds"),
                "alert_type": doc.get("alert_type"),
                "endpoint": doc.get("endpoint"),
                "source": doc.get("source"),
                "silenced": bool(doc.get("silenced", False)),
            }
        )

    try:
        total = int(coll.count_documents(match))  # type: ignore[attr-defined]
    except Exception:
        total = len(alerts)
    return alerts, total


def aggregate_alert_type_stats(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    min_count: int = 1,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Aggregate active alert_types with counts and last_seen (exclude drills).

    Returns a list of dicts:
      { "alert_type": str, "count": int, "last_seen_dt": datetime, "sample_title": str, "sample_name": str }

    Fail-open: returns [] on any error / when storage is unavailable.
    """
    coll = _get_collection()
    if coll is None:
        return []

    try:
        min_count_int = int(min_count)
    except Exception:
        min_count_int = 1
    min_count_int = max(1, min_count_int)

    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 500
    limit_int = max(1, min(2000, limit_int))

    match = _build_time_filter(start_dt, end_dt)
    # Default: exclude Drill alerts from analytics helpers
    match["details.is_drill"] = {"$ne": True}
    # Only consider documents with a real alert_type (avoid grouping null/empty)
    match["alert_type"] = {"$type": "string", "$ne": ""}

    pipeline = [
        {"$match": match},
        {"$sort": {"ts_dt": -1}},
        {
            "$group": {
                "_id": {"$toLower": "$alert_type"},
                "count": {"$sum": 1},
                "last_seen_dt": {"$first": "$ts_dt"},
                "sample_title": {"$first": "$summary"},
                "sample_name": {"$first": "$name"},
            }
        },
        {"$match": {"count": {"$gte": min_count_int}}},
        {"$sort": {"count": -1, "last_seen_dt": -1}},
        {"$limit": limit_int},
    ]

    try:
        rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            alert_type = _safe_str(row.get("_id"), limit=128).lower()
            if not alert_type:
                continue
            last_seen_dt = row.get("last_seen_dt")
            if not isinstance(last_seen_dt, datetime):
                continue
            out.append(
                {
                    "alert_type": alert_type,
                    "count": int(row.get("count", 0) or 0),
                    "last_seen_dt": last_seen_dt,
                    "sample_title": _safe_str(row.get("sample_title"), limit=256),
                    "sample_name": _safe_str(row.get("sample_name"), limit=128),
                }
            )
        except Exception:
            continue
    return out


def aggregate_alert_summary(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
) -> Dict[str, int]:
    """Aggregate alert counts by severity and deployment flag."""
    coll = _get_collection()
    if coll is None:
        return {"total": 0, "critical": 0, "anomaly": 0, "deployment": 0}
    match = _build_time_filter(start_dt, end_dt)
    # Default: exclude Drill alerts from summary/analytics
    match["details.is_drill"] = {"$ne": True}
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": None,
                "total": {"$sum": 1},
                "critical": {
                    "$sum": {
                        "$cond": [{"$eq": ["$severity", "critical"]}, 1, 0],
                    }
                },
                "anomaly": {
                    "$sum": {
                        "$cond": [{"$eq": ["$severity", "anomaly"]}, 1, 0],
                    }
                },
                "deployment": {
                    "$sum": {
                        "$cond": [
                            {
                                "$or": [
                                    {"$eq": ["$alert_type", "deployment_event"]},
                                    {"$eq": ["$name", "deployment_event"]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]
    try:
        result = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
        if not result:
            return {"total": 0, "critical": 0, "anomaly": 0, "deployment": 0}
        doc = result[0]
        return {
            "total": int(doc.get("total", 0)),
            "critical": int(doc.get("critical", 0)),
            "anomaly": int(doc.get("anomaly", 0)),
            "deployment": int(doc.get("deployment", 0)),
        }
    except Exception:
        return {"total": 0, "critical": 0, "anomaly": 0, "deployment": 0}


def fetch_alert_timestamps(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    severity: Optional[str] = None,
    alert_type: Optional[str] = None,
    limit: int = 500,
) -> List[datetime]:
    """Return recent alert timestamps matching the given filters."""
    coll = _get_collection()
    if coll is None:
        return []
    match = _build_time_filter(start_dt, end_dt)
    # Default: exclude Drill alerts from analytics helpers
    match["details.is_drill"] = {"$ne": True}
    if severity:
        match["severity"] = str(severity).lower()
    if alert_type:
        match["alert_type"] = str(alert_type).lower()
    try:
        cursor = (
            coll.find(match, {"ts_dt": 1})  # type: ignore[attr-defined]
            .sort("ts_dt", -1)  # type: ignore[attr-defined]
            .limit(max(1, limit))  # type: ignore[attr-defined]
        )
    except Exception:
        return []
    out: List[datetime] = []
    for doc in cursor:
        ts = doc.get("ts_dt")
        if isinstance(ts, datetime):
            out.append(ts)
    return out


def aggregate_alert_timeseries(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    granularity_seconds: int,
) -> List[Dict[str, Any]]:
    """Aggregate alert counts per severity over time buckets."""
    coll = _get_collection()
    if coll is None:
        return []
    try:
        bucket_seconds = max(1, int(granularity_seconds or 60))
    except Exception:
        bucket_seconds = 3600
    bucket_ms = bucket_seconds * 1000
    match = _build_time_filter(start_dt, end_dt)
    # Default: exclude Drill alerts from timeseries to prevent metric pollution
    match["details.is_drill"] = {"$ne": True}
    pipeline = [
        {"$match": match},
        {
            "$project": {
                "bucket": {
                    "$toDate": {
                        "$subtract": [
                            {"$toLong": "$ts_dt"},
                            {"$mod": [{"$toLong": "$ts_dt"}, bucket_ms]},
                        ]
                    }
                },
                "severity": {
                    "$toLower": {"$ifNull": ["$severity", "info"]},
                },
            }
        },
        {
            "$group": {
                "_id": {"bucket": "$bucket", "severity": "$severity"},
                "count": {"$sum": 1},
            }
        },
        {
            "$group": {
                "_id": "$_id.bucket",
                "counts": {
                    "$push": {
                        "severity": "$_id.severity",
                        "count": "$count",
                    }
                },
                "total": {"$sum": "$count"},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    try:
        rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
    except Exception:
        return []

    result: List[Dict[str, Any]] = []
    for row in rows:
        bucket = row.get("_id")
        ts_iso = _isoformat_utc(bucket)
        counts = {"critical": 0, "anomaly": 0, "warning": 0, "info": 0}
        for entry in row.get("counts", []):
            severity = str(entry.get("severity") or "info").lower()
            if severity not in counts:
                if severity.startswith("crit"):
                    severity = "critical"
                elif severity.startswith("warn"):
                    severity = "warning"
                elif severity.startswith("anom"):
                    severity = "anomaly"
                else:
                    severity = "info"
            counts[severity] += int(entry.get("count", 0))
        counts["total"] = int(row.get("total", 0))
        counts["timestamp"] = ts_iso
        result.append(counts)
    return result

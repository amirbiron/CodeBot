"""
Sticky Notes API for Markdown preview
- Stores user-specific notes per file in MongoDB
- Endpoints: list, create, update, delete
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, session
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, cast
from datetime import datetime, timezone, timedelta
import time
import html
import re
import base64
import hashlib
import threading
import asyncio
# Robust ObjectId/InvalidId import with fallbacks for stub environments
try:  # type: ignore
    from bson import ObjectId  # type: ignore
    from bson.errors import InvalidId  # type: ignore
except Exception:  # pragma: no cover
    class InvalidId(Exception):
        pass
    def ObjectId(x):  # type: ignore
        # Minimal fallback that accepts hex-like strings; raises on others
        s = str(x or "")
        if len(s) != 24:
            raise InvalidId("malformed ObjectId")
        return s

# Fail-open observability and tracing
try:  # type: ignore
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None
try:  # type: ignore
    from observability_instrumentation import traced  # type: ignore
except Exception:  # pragma: no cover
    def traced(*_a, **_k):  # type: ignore
        def _inner(f):
            return f
        return _inner

# Access to Mongo client via app helper
def get_db():
    from webapp.app import get_db as _get_db  # local import to avoid circulars
    return _get_db()

# Blueprint
sticky_notes_bp = Blueprint("sticky_notes", __name__, url_prefix="/api/sticky-notes")

try:
    from cache_manager import cache  # type: ignore
except Exception:
    cache = None  # type: ignore

# Module-level guard to ensure indexes only once per process
_INDEX_READY = False
_INDEX_READY_LOCK = threading.Lock()
_INDEX_READY_CACHE_KEY = "sticky_notes_indexes_ready_v1"
_INDEX_READY_CACHE_TTL_SECONDS = 24 * 3600
_INDEX_CACHE_LAST_CHECK = 0.0
_WARMUP_TRIGGERED = threading.Event()


def _emit_index_event(stage: str, duration_ms: Optional[int] = None, error: Optional[str] = None) -> None:
    """Emit lightweight observability events without failing the request."""
    try:
        severity = "info" if not error else "error"
        emit_event(
            "sticky_indexes_warmup",
            severity=severity,
            stage=stage,
            duration_ms=duration_ms,
            error=error,
        )
    except Exception:
        pass


def _cache_flag_ready() -> bool:
    """Check shared cache flag (best-effort) to avoid duplicate index builds."""
    global _INDEX_READY, _INDEX_CACHE_LAST_CHECK
    if _INDEX_READY:
        return True
    cache_obj = cache if 'cache' in globals() else None
    if cache_obj is None or not getattr(cache_obj, "is_enabled", False):
        return False
    now = time.time()
    if now - _INDEX_CACHE_LAST_CHECK < 30.0:
        return False
    _INDEX_CACHE_LAST_CHECK = now
    try:
        flag = cache_obj.get(_INDEX_READY_CACHE_KEY)
    except Exception:
        flag = None
    if flag:
        _INDEX_READY = True
        return True
    return False


def _mark_cache_flag() -> None:
    cache_obj = cache if 'cache' in globals() else None
    if cache_obj is None or not getattr(cache_obj, "is_enabled", False):
        return
    try:
        cache_obj.set(
            _INDEX_READY_CACHE_KEY,
            {"ready": True, "ts": int(time.time())},
            _INDEX_READY_CACHE_TTL_SECONDS,
        )
    except Exception:
        pass


def _mark_indexes_ready(duration_ms: Optional[int] = None) -> None:
    global _INDEX_READY
    _INDEX_READY = True
    _mark_cache_flag()
    _emit_index_event("done", duration_ms=duration_ms)


def kickoff_index_warmup(*, background: bool = True, delay_seconds: float = 0.0) -> None:
    """Run index warmup once during startup so requests won't block on it."""
    if _INDEX_READY or _cache_flag_ready() or _WARMUP_TRIGGERED.is_set():
        return
    _WARMUP_TRIGGERED.set()

    def _job():
        if delay_seconds > 0:
            try:
                time.sleep(delay_seconds)
            except Exception:
                pass
        _ensure_indexes()

    if background:
        try:
            # אם אנחנו בתוך event loop (למשל שירות aiohttp) – עדיף להעיף ל-executor כדי לא לחסום.
            # ב-Flask/Wsgi (ללא לולאה רצה) ניפול חזרה ל-thread דמון.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None:
                loop.run_in_executor(None, _job)
            else:
                threading.Thread(target=_job, name="sticky-index-warmup", daemon=True).start()
        except Exception:
            _job()
    else:
        _job()

def _ensure_indexes() -> None:
    if _INDEX_READY or _cache_flag_ready():
        return
    try:
        with _INDEX_READY_LOCK:
            if _INDEX_READY or _cache_flag_ready():
                return
            started = time.perf_counter()
            db = get_db()
            coll = db.sticky_notes
            try:
                from pymongo import ASCENDING, DESCENDING, IndexModel  # type: ignore
                indexes = [
                    IndexModel([("user_id", ASCENDING), ("file_id", ASCENDING)], name="user_file_idx"),
                    IndexModel([("user_id", ASCENDING), ("file_id", ASCENDING), ("created_at", ASCENDING)], name="user_file_created"),
                    IndexModel([("updated_at", DESCENDING)], name="updated_desc"),
                    # שאילתת ה-list הראשית היא ``$or`` על scope_id/file_id, אבל
                    # ענף ה-scope לא היה מכוסה כאן כלל — האינדקס נוצר רק
                    # אגב-אורחא ב-``mcp_server/backend``.
                    IndexModel([("user_id", ASCENDING), ("scope_id", ASCENDING)], name="user_scope_idx"),
                    # פתקי לוח: שאילתה ישירה, בלי ``$or`` ובלי code_snippets.
                    IndexModel([("user_id", ASCENDING), ("board_id", ASCENDING)], name="user_board_idx"),
                ]
                coll.create_indexes(indexes)
            except Exception:
                # Best-effort: if pymongo typings not available or running in stub env
                try:
                    coll.create_index([("user_id", 1), ("file_id", 1)], name="user_file_idx")
                    coll.create_index([("user_id", 1), ("file_id", 1), ("created_at", 1)], name="user_file_created")
                    coll.create_index([("updated_at", -1)], name="updated_desc")
                    coll.create_index([("user_id", 1), ("scope_id", 1)], name="user_scope_idx")
                    coll.create_index([("user_id", 1), ("board_id", 1)], name="user_board_idx")
                except Exception:
                    pass
            # אינדקסים ללוחות הפתקים (best-effort)
            try:
                nb = db.note_boards
                # ``one_default_per_user`` ייחודי-חלקי: הוא מה שסוגר את המרוץ
                # שבו שתי בקשות מקבילות מגלות שאין לוח ברירת מחדל ושתיהן
                # יוצרות. הגנת קוד לבדה לא מספיקה שם — המסד חייב לדחות.
                try:
                    from pymongo import ASCENDING, IndexModel  # type: ignore
                    nb.create_indexes([
                        IndexModel([("user_id", ASCENDING), ("order", ASCENDING)], name="user_order_idx"),
                        IndexModel(
                            [("user_id", ASCENDING)],
                            name="one_default_per_user",
                            unique=True,
                            partialFilterExpression={"is_default": True},
                        ),
                    ])
                except Exception:
                    try:
                        nb.create_index([("user_id", 1), ("order", 1)], name="user_order_idx")
                    except Exception:
                        pass
                    try:
                        nb.create_index(
                            [("user_id", 1)],
                            name="one_default_per_user",
                            unique=True,
                            partialFilterExpression={"is_default": True},
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            # Ensure note reminders collection indexes (best-effort)
            try:
                nr = db.note_reminders
                try:
                    from pymongo import ASCENDING, DESCENDING, IndexModel  # type: ignore
                    nr.create_indexes([
                        IndexModel([("user_id", ASCENDING), ("note_id", ASCENDING)], name="user_note_idx"),
                        IndexModel([("user_id", ASCENDING), ("status", ASCENDING), ("remind_at", ASCENDING)], name="user_status_time_idx"),
                        IndexModel([("remind_at", ASCENDING)], name="remind_at_idx"),
                    ])
                except Exception:
                    try:
                        nr.create_index([("user_id", 1), ("note_id", 1)], name="user_note_idx")
                    except Exception:
                        pass
                    try:
                        nr.create_index([("user_id", 1), ("status", 1), ("remind_at", 1)], name="user_status_time_idx")
                    except Exception:
                        pass
                    try:
                        nr.create_index([("remind_at", 1)], name="remind_at_idx")
                    except Exception:
                        pass
            except Exception:
                # Never fail request because of index creation
                pass
            duration_ms = int(max(0.0, (time.perf_counter() - started) * 1000.0))
            _mark_indexes_ready(duration_ms=duration_ms)
    except Exception as exc:
        _emit_index_event("failed", error=str(exc))

# --- Helpers ---

def require_auth(f):
    @wraps(f)
    def _inner(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return _inner
# Simple in-memory rate limiter per user and endpoint key
_RATE_LOG: Dict[tuple, list] = {}


def _rate_limit_check(user_id: int, key: str, max_per_minute: int) -> tuple[bool, int]:
    now = time.time()
    window_start = now - 60.0
    bucket_key = (int(user_id or 0), str(key or ""))
    try:
        entries = _RATE_LOG.get(bucket_key, [])
        # drop old timestamps
        i = 0
        for i, ts in enumerate(entries):
            if ts > window_start:
                break
        if entries:
            if entries[0] <= window_start:
                # remove all up to i (inclusive if still old)
                cutoff = i if entries[i] > window_start else (i + 1)
                entries = entries[cutoff:]
        # allow?
        allowed = len(entries) < max(1, int(max_per_minute or 1))
        if allowed:
            entries.append(now)
            _RATE_LOG[bucket_key] = entries
            return True, 0
        else:
            # estimate retry-after (rough)
            retry_after = int(max(1.0, 60.0 - (now - (entries[0] if entries else window_start))))
            return False, retry_after
    except Exception:
        return True, 0


def notes_rate_limit(key: str, max_per_minute: int):
    def _decorator(f):
        @wraps(f)
        def _inner(*args, **kwargs):
            try:
                uid = int(session.get('user_id') or 0)
            except Exception:
                uid = 0
            if uid:
                allowed, retry_after = _rate_limit_check(uid, key, max_per_minute)
                if not allowed:
                    resp = jsonify({'ok': False, 'error': 'Rate limited'})
                    try:
                        resp.headers['Retry-After'] = str(int(retry_after))
                    except Exception:
                        pass
                    return resp, 429
            return f(*args, **kwargs)
        return _inner
    return _decorator



_CONTROL_CHARS_RE = re.compile(r"[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]")


def _sanitize_text(text: Any, max_length: int = 20000) -> str:
    """Normalize user text without HTML escaping.

    שומר על טקסט כפי שהמשתמש הזין (כולל מרכאות וסימנים אחרים) תוך הסרת תווים לא
    מודפסים והגבלת אורך סבירה כדי למנוע פגיעה בבסיס הנתונים.
    """
    if text is None:
        return ""
    try:
        s = str(text)
    except Exception:
        s = ""
    # החזרת מחרוזות שהשתמרו כ-html entities (כמו &quot;)
    s = html.unescape(s)
    # נרמול קפיצות שורה והסרת תווים שאינם מודפסים
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _CONTROL_CHARS_RE.sub("", s)
    if max_length and max_length > 0:
        s = s[:max_length]
    return s


def _decode_content_b64(value: Any, *, max_decoded_chars: int = 5000, max_b64_len: int = 120000) -> str:
    """Decode Base64 UTF-8 content safely.

    מיועד ל-`content_b64` כדי למנוע חסימות/פילטרים על מילים "חשודות" בזמן העברה.
    הטקסט שנשמר ב-DB הוא תמיד טקסט רגיל אחרי sanitize.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("content_b64 must be a string")
    s = value.strip()
    if not s:
        return ""
    # Best-effort safety: avoid decoding extremely large blobs.
    # Note: Base64 is ~4/3 expansion. UTF-8 can be up to 4 bytes per char.
    # We keep this limit comfortably above the 5k-char sticky-note cap to avoid
    # rejecting valid UTF-8 (e.g., emoji-heavy notes).
    if max_b64_len and len(s) > int(max_b64_len):
        raise ValueError("content_b64 too large")
    # Remove whitespace and normalize urlsafe variants
    try:
        s = "".join(s.split())
    except Exception:
        s = s.replace(" ", "")
    s = s.replace("-", "+").replace("_", "/")
    # Fix missing padding (common in transport layers)
    pad = (-len(s)) % 4
    if pad:
        s = s + ("=" * pad)
    try:
        raw = base64.b64decode(s, validate=True)
    except Exception as exc:
        raise ValueError("invalid base64") from exc
    try:
        text = raw.decode("utf-8", errors="strict")
    except Exception as exc:
        raise ValueError("invalid utf-8") from exc
    return _sanitize_text(text, int(max_decoded_chars or 5000))


def _coerce_int(value: Any, default: int, min_v: Optional[int] = None, max_v: Optional[int] = None) -> int:
    try:
        x = int(value)
    except Exception:
        x = int(default)
    if min_v is not None and x < min_v:
        x = min_v
    if max_v is not None and x > max_v:
        x = max_v
    return x


def _make_scope_id(user_id: int, file_name: Optional[str]) -> Optional[str]:
    # פונקציה קנונית (ללא תלות ב-Flask) כדי למנוע סטיות בין שירותים.
    from sticky_notes_scope import make_scope_id
    return make_scope_id(int(user_id), file_name)


def _resolve_scope(db, user_id: int, file_id: Any) -> Tuple[Optional[str], Optional[str], List[str]]:
    normalized_id = str(file_id or '').strip()
    related_ids: List[str] = []
    if normalized_id:
        related_ids.append(normalized_id)
    file_name: Optional[str] = None
    scope_id: Optional[str] = None
    if db is None:
        return scope_id, file_name, related_ids
    oid = None
    try:
        oid = ObjectId(str(file_id))
    except Exception:
        oid = None
    doc = None
    if oid is not None:
        try:
            doc = db.code_snippets.find_one({'_id': oid, 'user_id': user_id}, {'file_name': 1})
        except Exception:
            doc = None
        if doc and isinstance(doc, dict):
            file_name = doc.get('file_name')
    if file_name:
        scope_id = _make_scope_id(user_id, file_name)
        try:
            cursor = db.code_snippets.find({'user_id': user_id, 'file_name': file_name}, {'_id': 1})
        except Exception:
            cursor = None
        if cursor is not None:
            for entry in cursor:
                try:
                    rid = str((entry or {}).get('_id') or '')
                except Exception:
                    rid = ''
                if rid:
                    related_ids.append(rid)
    seen = set()
    deduped: List[str] = []
    for rid in related_ids:
        if not rid or rid in seen:
            continue
        seen.add(rid)
        deduped.append(rid)
    return scope_id, file_name, deduped


def _coerce_content_from_doc(value: Any) -> str:
    if value is None:
        return ""
    try:
        s = str(value)
    except Exception:
        s = ""
    return html.unescape(s)


def _as_note_response(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': str(doc.get('_id')),
        'file_id': str(doc.get('file_id', '')),
        'content': _coerce_content_from_doc(doc.get('content', '')),
        'position': {
            'x': int(doc.get('position_x', 100) or 100),
            'y': int(doc.get('position_y', 100) or 100),
        },
        'size': {
            'width': int(doc.get('width', 240) or 240),
            'height': int(doc.get('height', 180) or 180),
        },
        'color': str(doc.get('color', '#FFFFCC') or '#FFFFCC'),
        'is_minimized': bool(doc.get('is_minimized', False)),
        'line_start': doc.get('line_start'),
        'line_end': doc.get('line_end'),
        'anchor_id': doc.get('anchor_id') or '',
        'anchor_text': doc.get('anchor_text') or '',
        # פתק לוח. הלקוח מזהה לפי זה לאיזה משטח לצרף אותו, ו-``mode`` קובע
        # אם הוא נע עם הלוח או נשאר על המסך. בפתק קובץ שניהם ריקים,
        # והמצב ממשיך להיגזר מ-``anchor_id`` כמו קודם.
        'board_id': str(doc.get('board_id', '') or ''),
        'mode': str(doc.get('mode', '') or ''),
        'updated_at': (doc.get('updated_at').isoformat() if doc.get('updated_at') else None),
        'created_at': (doc.get('created_at').isoformat() if doc.get('created_at') else None),
    }


# --- Routes ---

@sticky_notes_bp.route('/<file_id>', methods=['GET'])
@require_auth
@notes_rate_limit('list', 180)
@traced("sticky_notes.list")
def list_notes(file_id: str):
    """List all sticky notes for current user and file."""
    try:
        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        scope_id, file_name, related_ids = _resolve_scope(db, user_id, file_id)
        query: Dict[str, Any] = {'user_id': user_id}
        criteria: List[Dict[str, Any]] = []
        if scope_id:
            criteria.append({'scope_id': scope_id})
        if related_ids:
            criteria.append({'file_id': {'$in': related_ids}})
        if criteria:
            query['$or'] = criteria
        else:
            query['file_id'] = str(file_id)
        cursor = db.sticky_notes.find(query).sort('created_at', 1)
        raw_docs = list(cursor) if cursor is not None else []
        notes = [
            _as_note_response(doc) for doc in raw_docs if isinstance(doc, dict)
        ]
        if scope_id:
            missing_ids = [doc.get('_id') for doc in raw_docs if isinstance(doc, dict) and not doc.get('scope_id')]
            if missing_ids:
                try:
                    update_payload: Dict[str, Any] = {'scope_id': scope_id}
                    if file_name:
                        update_payload['file_name'] = file_name
                    db.sticky_notes.update_many({'_id': {'$in': missing_ids}}, {'$set': update_payload})
                except Exception:
                    pass
        resp = jsonify({'ok': True, 'notes': notes, 'count': len(notes)})
        # מניעת קאשינג בדפדפן/פרוקסי כדי שלא תוחזר גרסה ישנה של פתקים
        try:
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
        except Exception:
            pass
        return resp
    except Exception as e:
        try:
            emit_event("sticky_notes_list_error", severity="anomaly", file_id=str(file_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to list notes'}), 500


# --- Sticky note reminders API ---

def _parse_when_to_utc(payload: Dict[str, Any], user_tz: str) -> Optional[datetime]:
    """Parse reminder time from payload into aware UTC datetime.

    Supports:
    - preset values:  "1h", "3h", "24h", "1w", "today-21", "tomorrow-09"
    - explicit: payload["at"] as ISO-like string ("YYYY-MM-DDTHH:MM") with optional seconds
    - free text: payload["time_text"] using reminders.utils.parse_time
    """
    try:
        from zoneinfo import ZoneInfo  # type: ignore
    except Exception:  # pragma: no cover
        ZoneInfo = None  # type: ignore

    now_local = None
    try:
        tz = ZoneInfo(user_tz) if (user_tz and ZoneInfo) else None
    except Exception:
        tz = None
    try:
        now_local = datetime.now(tz or timezone.utc)
    except Exception:
        now_local = datetime.now(timezone.utc)

    preset = str((payload or {}).get('preset') or '').strip().lower()
    if preset:
        if preset in {'1h', '1hr'}:
            return (now_local + timedelta(hours=1)).astimezone(timezone.utc)
        if preset in {'3h', '3hr'}:
            return (now_local + timedelta(hours=3)).astimezone(timezone.utc)
        if preset in {'24h', '1d'}:
            return (now_local + timedelta(hours=24)).astimezone(timezone.utc)
        if preset in {'1w', '7d'}:
            return (now_local + timedelta(days=7)).astimezone(timezone.utc)
        if preset == 'today-21':
            base = now_local.replace(hour=21, minute=0, second=0, microsecond=0)
            if base <= now_local:
                # if passed, schedule for tomorrow 21:00
                base = base + timedelta(days=1)
            return base.astimezone(timezone.utc)
        if preset == 'tomorrow-09':
            base = (now_local + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
            return base.astimezone(timezone.utc)

    at = (payload or {}).get('at')
    if at:
        try:
            # Expecting local naive string like "YYYY-MM-DDTHH:MM" (datetime-local)
            # If seconds provided, they'll be ignored by slicing
            s = str(at).strip()
            # Normalize seconds if present
            if len(s) >= 16:
                from datetime import datetime as _dt
                local_naive = _dt.strptime(s[:16], '%Y-%m-%dT%H:%M')
                if tz:
                    aware = local_naive.replace(tzinfo=tz)
                else:
                    aware = local_naive.replace(tzinfo=timezone.utc)
                return aware.astimezone(timezone.utc)
        except Exception:
            pass

    # Free text
    time_text = (payload or {}).get('time_text')
    if time_text:
        try:
            try:
                from reminders.utils import parse_time as _parse
            except Exception:
                _parse = None  # type: ignore
            if _parse:
                dt = _parse(str(time_text), user_tz or 'UTC')
                if dt:
                    return dt.astimezone(timezone.utc)
        except Exception:
            pass

    return None


def _ensure_user_owns_note(db, user_id: int, note_id: str) -> Optional[Dict[str, Any]]:
    raw_id = str(note_id or "").strip()
    if not raw_id:
        return None
    candidates: List[Any] = []
    try:
        from bson import ObjectId  # type: ignore
    except Exception:
        ObjectId = None  # type: ignore
    if ObjectId and raw_id:
        try:
            candidates.append(ObjectId(raw_id))
        except Exception:
            pass
    candidates.append(raw_id)
    for candidate in candidates:
        try:
            note = db.sticky_notes.find_one({'_id': candidate, 'user_id': int(user_id)})
        except Exception:
            note = None
        if isinstance(note, dict):
            return note
    return None


@sticky_notes_bp.route('/note/<note_id>/reminder', methods=['GET'])
@require_auth
@notes_rate_limit('note_reminder_get', 180)
@traced('sticky_notes.reminder_get')
def get_note_reminder(note_id: str):
    try:
        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        note = _ensure_user_owns_note(db, user_id, note_id)
        if not note:
            return jsonify({'ok': False, 'error': 'Note not found'}), 404
        r = db.note_reminders.find_one({'user_id': user_id, 'note_id': str(note_id), 'status': {'$in': ['pending', 'snoozed']}})
        if not r:
            return jsonify({'ok': True, 'reminder': None})
        out = {
            'id': str(r.get('_id')),
            'status': r.get('status', 'pending'),
            'remind_at': (r.get('remind_at').isoformat() if isinstance(r.get('remind_at'), datetime) else None),
            'snooze_until': (r.get('snooze_until').isoformat() if isinstance(r.get('snooze_until'), datetime) else None),
        }
        return jsonify({'ok': True, 'reminder': out})
    except Exception:
        return jsonify({'ok': False, 'error': 'Failed'}), 500


@sticky_notes_bp.route('/note/<note_id>/reminder', methods=['POST'])
@require_auth
@notes_rate_limit('note_reminder_set', 60)
@traced('sticky_notes.reminder_set')
def set_note_reminder(note_id: str):
    try:
        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        note = _ensure_user_owns_note(db, user_id, note_id)
        if not note:
            return jsonify({'ok': False, 'error': 'Note not found'}), 404
        payload = request.get_json(silent=True) or {}
        client_tz = str(payload.get('tz') or 'Asia/Jerusalem')
        dt_utc = _parse_when_to_utc(payload, client_tz)
        if not dt_utc:
            return jsonify({'ok': False, 'error': 'Invalid time'}), 400
        if dt_utc <= datetime.now(timezone.utc):
            return jsonify({'ok': False, 'error': 'Time must be in the future'}), 400
        now_utc = datetime.now(timezone.utc)
        # Fields to set on every update
        set_fields = {
            'user_id': user_id,
            'note_id': str(note_id),
            'file_id': str(note.get('file_id', '')),
            # לפתק לוח אין file_id, ובלי השדה הזה ה-Service Worker
            # לא היה יודע לאן לפתוח את ההתראה.
            'board_id': str(note.get('board_id', '') or ''),
            'status': 'pending',
            'remind_at': dt_utc,
            'snooze_until': None,
            'ack_at': None,
            'updated_at': now_utc,
            'needs_push': True,
        }
        # Upsert: keep only one active reminder per note for simplicity
        try:
            db.note_reminders.update_one(
                {'user_id': user_id, 'note_id': str(note_id)},
                {
                    '$set': set_fields,
                    '$setOnInsert': {'created_at': now_utc},
                },
                upsert=True,
            )
        except Exception:
            return jsonify({'ok': False, 'error': 'Failed to save'}), 500
        try:
            emit_event('note_reminder_set', severity='info', user_id=user_id, note_id=str(note_id))
        except Exception:
            pass
        return jsonify({'ok': True, 'remind_at': dt_utc.isoformat()})
    except Exception:
        return jsonify({'ok': False, 'error': 'Failed'}), 500


@sticky_notes_bp.route('/note/<note_id>/reminder', methods=['DELETE'])
@require_auth
@notes_rate_limit('note_reminder_delete', 60)
@traced('sticky_notes.reminder_delete')
def delete_note_reminder(note_id: str):
    try:
        user_id = int(session['user_id'])
        db = get_db()
        note = _ensure_user_owns_note(db, user_id, note_id)
        if not note:
            return jsonify({'ok': False, 'error': 'Note not found'}), 404
        db.note_reminders.delete_one({'user_id': user_id, 'note_id': str(note_id)})
        return jsonify({'ok': True})
    except Exception:
        return jsonify({'ok': False, 'error': 'Failed'}), 500


@sticky_notes_bp.route('/note/<note_id>/snooze', methods=['POST'])
@require_auth
@notes_rate_limit('note_reminder_snooze', 120)
@traced('sticky_notes.reminder_snooze')
def snooze_note_reminder(note_id: str):
    try:
        user_id = int(session['user_id'])
        db = get_db()
        payload = request.get_json(silent=True) or {}
        minutes = int(payload.get('minutes') or 60)
        if minutes < 1 or minutes > 24 * 60:
            return jsonify({'ok': False, 'error': 'Invalid minutes'}), 400
        new_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        r = db.note_reminders.update_one(
            {'user_id': user_id, 'note_id': str(note_id), 'status': {'$in': ['pending', 'snoozed']}},
            {'$set': {
                'status': 'snoozed',
                'snooze_until': new_time,
                'remind_at': new_time,
                'updated_at': datetime.now(timezone.utc),
                'ack_at': None,
                'needs_push': True,  # Reset so push will be sent again
            }},
        )
        if getattr(r, 'matched_count', 0) <= 0:
            return jsonify({'ok': False, 'error': 'Reminder not found'}), 404
        return jsonify({'ok': True, 'remind_at': new_time.isoformat()})
    except Exception:
        return jsonify({'ok': False, 'error': 'Failed'}), 500


@sticky_notes_bp.route('/reminders/summary', methods=['GET'])
@require_auth
@notes_rate_limit('note_reminders_summary', 300)
@traced('sticky_notes.reminders_summary')
def reminders_summary():
    """Return minimal summary for persistent UI badge.

    Response:
      { ok, has_due: bool, count_due: int, next: { note_id, file_id, remind_at } | null }
    """
    try:
        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        now = datetime.now(timezone.utc)
        try:
            cursor = db.note_reminders.find({
                'user_id': user_id,
                'status': {'$in': ['pending', 'snoozed']},
                'remind_at': {'$lte': now},
                'ack_at': None,
            }).sort('remind_at', 1)
        except Exception:
            cursor = []
        items = list(cursor) if cursor is not None else []
        has_due = len(items) > 0
        nxt = None
        if has_due:
            first = items[0]
            nxt = {
                'note_id': str(first.get('note_id', '')),
                'file_id': str(first.get('file_id', '')),
                'remind_at': first.get('remind_at').isoformat() if isinstance(first.get('remind_at'), datetime) else None,
            }
        return jsonify({'ok': True, 'has_due': has_due, 'count_due': len(items), 'next': nxt})
    except Exception:
        return jsonify({'ok': False, 'error': 'Failed'}), 500


@sticky_notes_bp.route('/reminders/list', methods=['GET'])
@require_auth
@notes_rate_limit('note_reminders_list', 300)
@traced('sticky_notes.reminders_list')
def reminders_list():
    """Return a list of due sticky‑note reminders for the current user.

    Response:

    .. code-block:: json

        {
          "ok": true,
          "items": [
            { "note_id": "...", "file_id": "...", "preview": "...", "anchor_id": "h2-intro", "anchor_text": "Intro" }
          ],
          "count": 1
        }
    """
    try:
        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        now = datetime.now(timezone.utc)
        # Pagination bounds
        try:
            limit_param = int(request.args.get('limit', 20))
        except Exception:
            limit_param = 20
        limit_param = max(1, min(50, limit_param))

        try:
            cursor = (
                db.note_reminders
                .find({
                    'user_id': user_id,
                    'status': {'$in': ['pending', 'snoozed']},
                    'remind_at': {'$lte': now},
                    'ack_at': None,
                })
                .sort('remind_at', 1)
                .limit(limit_param)
            )
        except Exception:
            cursor = []

        reminders = list(cursor) if cursor is not None else []
        items = []

        def _first_n_words(text: str, n: int = 6) -> str:
            try:
                s = _sanitize_text(text or '', 5000)
                words = [w for w in s.strip().split() if w]
                if not words:
                    return ''
                head = words[:max(1, n)]
                out = ' '.join(head)
                if len(words) > n:
                    out += '…'
                return out
            except Exception:
                return ''

        for r in reminders:
            try:
                note_id = str(r.get('note_id') or '')
                file_id = str(r.get('file_id') or '')
                board_id = str(r.get('board_id') or '')
                preview = ''
                anchor_id = ''
                anchor_text = ''

                note_doc = None
                # Try ObjectId first for performance/accuracy
                try:
                    oid = ObjectId(note_id)
                except Exception:
                    oid = None
                if oid is not None:
                    try:
                        note_doc = db.sticky_notes.find_one({'_id': oid, 'user_id': user_id})
                    except Exception:
                        note_doc = None
                if note_doc is None and note_id:
                    try:
                        note_doc = db.sticky_notes.find_one({'_id': note_id, 'user_id': user_id})
                    except Exception:
                        note_doc = None

                if isinstance(note_doc, dict):
                    preview_source = _coerce_content_from_doc(note_doc.get('content', '')) or (note_doc.get('anchor_text') or '')
                    preview = _first_n_words(preview_source, 6)
                    anchor_id = str(note_doc.get('anchor_id') or '')
                    anchor_text = str(note_doc.get('anchor_text') or '')
                    # Prefer file_id/board_id from note if missing on reminder
                    # (defensive — תזכורות ישנות נכתבו לפני שהשדה נוסף)
                    if not file_id:
                        try:
                            file_id = str(note_doc.get('file_id') or '')
                        except Exception:
                            pass
                    if not board_id:
                        try:
                            board_id = str(note_doc.get('board_id') or '')
                        except Exception:
                            pass
                else:
                    preview = ''

                items.append({
                    'note_id': note_id,
                    'file_id': file_id,
                    'board_id': board_id,
                    'preview': preview,
                    'anchor_id': anchor_id,
                    'anchor_text': anchor_text,
                })
            except Exception:
                # Skip malformed entries rather than failing the entire list
                continue

        return jsonify({'ok': True, 'items': items, 'count': len(items)})
    except Exception:
        return jsonify({'ok': False, 'error': 'Failed'}), 500


@sticky_notes_bp.route('/reminders/ack', methods=['POST'])
@require_auth
@notes_rate_limit('note_reminders_ack', 300)
@traced('sticky_notes.reminders_ack')
def reminders_ack():
    """Mark current due reminder as acknowledged (user opened it)."""
    try:
        user_id = int(session['user_id'])
        db = get_db()
        payload = request.get_json(silent=True) or {}
        note_id = str(payload.get('note_id') or '').strip()
        if not note_id:
            return jsonify({'ok': False, 'error': 'note_id required'}), 400
        r = db.note_reminders.update_one(
            {'user_id': user_id, 'note_id': note_id, 'ack_at': None},
            {'$set': {'ack_at': datetime.now(timezone.utc), 'updated_at': datetime.now(timezone.utc)}}
        )
        if getattr(r, 'matched_count', 0) <= 0:
            return jsonify({'ok': False, 'error': 'Not found'}), 404
        return jsonify({'ok': True})
    except Exception:
        return jsonify({'ok': False, 'error': 'Failed'}), 500


@sticky_notes_bp.route('/<file_id>', methods=['POST'])
@require_auth
@notes_rate_limit('create', 60)
@traced("sticky_notes.create")
def create_note(file_id: str):
    """Create a new sticky note for a file."""
    try:
        from sticky_notes_target import NoteQuotaError, check_note_quota

        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        scope_id, scope_file_name, _ = _resolve_scope(db, user_id, file_id)
        data = request.get_json(silent=True) or {}
        if 'content_b64' in data:
            try:
                content = _decode_content_b64(data.get('content_b64'), max_decoded_chars=5000)
            except ValueError:
                # Backward compatibility: if plain content is present, fall back to it.
                if 'content' in data:
                    content = _sanitize_text(data.get('content', ''), 5000)
                else:
                    return jsonify({'ok': False, 'error': 'Invalid content_b64'}), 400
        else:
            content = _sanitize_text(data.get('content', ''), 5000)
        pos = data.get('position') or {}
        size = data.get('size') or {}
        color = str(data.get('color', '#FFFFCC') or '#FFFFCC')
        is_minimized = bool(data.get('is_minimized', False))
        line_start = data.get('line_start')
        line_end = data.get('line_end')
        anchor_id = (data.get('anchor_id') or '').strip()[:256]
        anchor_text = (data.get('anchor_text') or '').strip()[:256]

        # תקרת הפתקים למשתמש חלה על כל הפתקים, לא רק על אלה שבלוחות.
        # היא מתועדת מזה זמן ולא נאכפה בשום מקום; אכיפה רק במסלול הלוח
        # הייתה הופכת את התיעוד לנכון-למחצה.
        try:
            check_note_quota(
                _count_or_none(db.sticky_notes, {'user_id': user_id}),
                MAX_NOTES_PER_USER,
                is_admin=_current_user_is_admin(),
            )
        except NoteQuotaError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 409

        doc = {
            'user_id': user_id,
            'file_id': str(file_id),
            'content': content,
            'position_x': _coerce_int(pos.get('x'), 100, 0, 100000),
            'position_y': _coerce_int(pos.get('y'), 100, 0, 1000000),
            'width': _coerce_int(size.get('width'), 250, 120, 1200),
            'height': _coerce_int(size.get('height'), 200, 80, 1200),
            'color': color if color else '#FFFFCC',
            'is_minimized': bool(is_minimized),
            'line_start': int(line_start) if isinstance(line_start, int) else None,
            'line_end': int(line_end) if isinstance(line_end, int) else None,
            'anchor_id': anchor_id or None,
            'anchor_text': anchor_text or None,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
        }
        if scope_id:
            doc['scope_id'] = scope_id
        if scope_file_name:
            doc['file_name'] = scope_file_name
        res = db.sticky_notes.insert_one(doc)
        nid = str(getattr(res, 'inserted_id', ''))
        try:
            emit_event("sticky_note_created", severity="info", user_id=int(user_id), file_id=str(file_id))
        except Exception:
            pass
        resp = jsonify({'ok': True, 'id': nid})
        try:
            resp.headers['Cache-Control'] = 'no-store'
        except Exception:
            pass
        return resp, 201
    except Exception as e:
        try:
            emit_event("sticky_notes_create_error", severity="anomaly", file_id=str(file_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to create note'}), 500


@sticky_notes_bp.route('/note/<note_id>', methods=['PUT'])
@require_auth
@notes_rate_limit('update', 300)
@traced("sticky_notes.update")
def update_note(note_id: str):
    """Update existing note; only owner can update."""
    try:
        user_id = int(session['user_id'])
        data = request.get_json(silent=True) or {}
        updates: Dict[str, Any] = {}
        # Prefer content_b64 if provided (avoid "on-the-wire" clear text)
        if 'content_b64' in data or 'content' in data:
            if 'content_b64' in data:
                try:
                    updates['content'] = _decode_content_b64(data.get('content_b64'), max_decoded_chars=5000)
                except ValueError:
                    # Backward compatibility: if plain content is present, fall back to it.
                    if 'content' in data:
                        updates['content'] = _sanitize_text(data.get('content'), 5000)
                    else:
                        return jsonify({'ok': False, 'error': 'Invalid content_b64'}), 400
            elif 'content' in data:
                updates['content'] = _sanitize_text(data.get('content'), 5000)
        if 'position' in data and isinstance(data.get('position'), dict):
            pos = data['position']
            updates['position_x'] = _coerce_int(pos.get('x'), 100, 0, 100000)
            updates['position_y'] = _coerce_int(pos.get('y'), 100, 0, 1000000)
        if 'size' in data and isinstance(data.get('size'), dict):
            size = data['size']
            updates['width'] = _coerce_int(size.get('width'), 250, 120, 1200)
            updates['height'] = _coerce_int(size.get('height'), 200, 80, 1200)
        if 'color' in data:
            color = str(data.get('color') or '').strip()
            if color:
                updates['color'] = color
        if 'is_minimized' in data:
            updates['is_minimized'] = bool(data.get('is_minimized'))
        if 'line_start' in data:
            try:
                updates['line_start'] = int(data.get('line_start'))
            except Exception:
                updates['line_start'] = None
        if 'line_end' in data:
            try:
                updates['line_end'] = int(data.get('line_end'))
            except Exception:
                updates['line_end'] = None
        if 'anchor_id' in data:
            aid = (data.get('anchor_id') or '').strip()[:256]
            updates['anchor_id'] = aid or None
        if 'anchor_text' in data:
            atx = (data.get('anchor_text') or '').strip()[:256]
            updates['anchor_text'] = atx or None

        if not updates:
            return jsonify({'ok': False, 'error': 'No fields to update'}), 400

        updates['updated_at'] = datetime.now(timezone.utc)

        db = get_db()
        # Validate ObjectId early and return 400 on malformed input
        try:
            oid = ObjectId(note_id)
        except InvalidId:
            return jsonify({'ok': False, 'error': 'Invalid note_id'}), 400
        note = db.sticky_notes.find_one({'_id': oid, 'user_id': user_id})
        if not note:
            return jsonify({'ok': False, 'error': 'Note not found'}), 404
        # פתק לוח אינו נושא scope_id ולעולם לא יישא — ובלי השומר הזה
        # כל עדכון שלו היה מריץ _resolve_scope, כלומר קריאה ל-code_snippets
        # רק כדי לגלות שאין קובץ.
        if not note.get('scope_id') and not note.get('board_id'):
            scope_id, scope_file_name, _ = _resolve_scope(db, user_id, note.get('file_id'))
            if scope_id:
                updates['scope_id'] = scope_id
                if scope_file_name and 'file_name' not in updates:
                    updates['file_name'] = scope_file_name
        # מניעת דריסה בין מכשירים: אם התקבלה prev_updated_at ונמוכה מהעדכנית – החזר 409
        try:
            prev_updated_at = data.get('prev_updated_at')
            if prev_updated_at:
                try:
                    prev_dt = datetime.fromisoformat(str(prev_updated_at))
                except Exception:
                    prev_dt = None
                if prev_dt and isinstance(note.get('updated_at'), datetime) and prev_dt < note['updated_at']:
                    return jsonify({'ok': False, 'error': 'Conflict', 'updated_at': note['updated_at'].isoformat()}), 409
        except Exception:
            pass
        db.sticky_notes.update_one({'_id': oid, 'user_id': user_id}, {'$set': updates})
        try:
            emit_event("sticky_note_updated", severity="info", user_id=int(user_id), note_id=str(note_id))
        except Exception:
            pass
        # שליחת חותמת הזמן שנוצרה עבור העדכון הנוכחי (ללא שאילתא נוספת)
        try:
            updated_at_iso = updates.get('updated_at').isoformat() if updates.get('updated_at') else None
        except Exception:
            updated_at_iso = None
        resp = jsonify({'ok': True, 'updated_at': updated_at_iso})
        try:
            resp.headers['Cache-Control'] = 'no-store'
        except Exception:
            pass
        return resp
    except Exception as e:
        try:
            emit_event("sticky_notes_update_error", severity="anomaly", note_id=str(note_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to update note'}), 500


@sticky_notes_bp.route('/note/<note_id>', methods=['DELETE'])
@require_auth
@notes_rate_limit('delete', 120)
@traced("sticky_notes.delete")
def delete_note(note_id: str):
    """Delete a note; only owner can delete."""
    try:
        user_id = int(session['user_id'])
        db = get_db()
        try:
            oid = ObjectId(note_id)
        except InvalidId:
            return jsonify({'ok': False, 'error': 'Invalid note_id'}), 400
        res = db.sticky_notes.delete_one({'_id': oid, 'user_id': user_id})
        if int(getattr(res, 'deleted_count', 0) or 0) <= 0:
            return jsonify({'ok': False, 'error': 'Note not found'}), 404
        try:
            emit_event("sticky_note_deleted", severity="info", user_id=int(user_id), note_id=str(note_id))
        except Exception:
            pass
        resp = jsonify({'ok': True})
        try:
            resp.headers['Cache-Control'] = 'no-store'
        except Exception:
            pass
        return resp
    except Exception as e:
        try:
            emit_event("sticky_notes_delete_error", severity="anomaly", note_id=str(note_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to delete note'}), 500


@sticky_notes_bp.route('/batch', methods=['POST'])
@require_auth
@notes_rate_limit('batch', 300)
@traced("sticky_notes.batch")
def batch_update_notes():
    """Batch update multiple notes in one request.

    Body format (JSON):

    .. code-block:: json

        {
          "updates": [
            {
              "id": "...",
              "content": "...",
              "position": {"x": 120, "y": 240},
              "size": {"width": 260, "height": 200},
              "color": "#FFFFCC",
              "is_minimized": false,
              "line_start": 10,
              "line_end": null,
              "anchor_id": "h2-intro",
              "anchor_text": "Intro",
              "prev_updated_at": "2024-01-01T00:00:00+00:00"
            }
          ]
        }

    Response JSON contains ``results`` with per-item status, e.g. 200/409.
    """
    try:
        user_id = int(session['user_id'])
        db = get_db()
        payload = request.get_json(silent=True) or {}
        updates_input = payload.get('updates')
        if isinstance(updates_input, list):
            items = updates_input
        elif isinstance(payload, list):
            items = payload
        else:
            items = []
        if not items:
            return jsonify({'ok': False, 'error': 'No updates provided'}), 400

        results: List[Dict[str, Any]] = []
        for item in items:
            try:
                note_id = str((item or {}).get('id') or '').strip()
                if not note_id:
                    results.append({'id': None, 'ok': False, 'status': 400, 'error': 'Missing id'})
                    continue
                try:
                    oid = ObjectId(note_id)
                except InvalidId:
                    results.append({'id': note_id, 'ok': False, 'status': 400, 'error': 'Invalid id'})
                    continue
                note = db.sticky_notes.find_one({'_id': oid, 'user_id': user_id})
                if not note:
                    results.append({'id': note_id, 'ok': False, 'status': 404, 'error': 'Not found'})
                    continue

                fragment = item
                updates: Dict[str, Any] = {}
                if 'content_b64' in fragment or 'content' in fragment:
                    if 'content_b64' in fragment:
                        try:
                            updates['content'] = _decode_content_b64(fragment.get('content_b64'), max_decoded_chars=5000)
                        except ValueError:
                            # Backward compatibility: if plain content is present, fall back to it.
                            if 'content' in fragment:
                                updates['content'] = _sanitize_text(fragment.get('content'), 5000)
                            else:
                                results.append({'id': note_id, 'ok': False, 'status': 400, 'error': 'Invalid content_b64'})
                                continue
                    elif 'content' in fragment:
                        updates['content'] = _sanitize_text(fragment.get('content'), 5000)
                if 'position' in fragment and isinstance(fragment.get('position'), dict):
                    pos = fragment['position']
                    updates['position_x'] = _coerce_int(pos.get('x'), 100, 0, 100000)
                    updates['position_y'] = _coerce_int(pos.get('y'), 100, 0, 1000000)
                if 'size' in fragment and isinstance(fragment.get('size'), dict):
                    size = fragment['size']
                    updates['width'] = _coerce_int(size.get('width'), 250, 120, 1200)
                    updates['height'] = _coerce_int(size.get('height'), 200, 80, 1200)
                if 'color' in fragment:
                    col = str(fragment.get('color') or '').strip()
                    if col:
                        updates['color'] = col
                if 'is_minimized' in fragment:
                    updates['is_minimized'] = bool(fragment.get('is_minimized'))
                if 'line_start' in fragment:
                    try:
                        updates['line_start'] = int(fragment.get('line_start'))
                    except Exception:
                        updates['line_start'] = None
                if 'line_end' in fragment:
                    try:
                        updates['line_end'] = int(fragment.get('line_end'))
                    except Exception:
                        updates['line_end'] = None
                if 'anchor_id' in fragment:
                    aid = (fragment.get('anchor_id') or '').strip()[:256]
                    updates['anchor_id'] = aid or None
                if 'anchor_text' in fragment:
                    atx = (fragment.get('anchor_text') or '').strip()[:256]
                    updates['anchor_text'] = atx or None

                # conflict detection similar to single update
                try:
                    prev_updated_at = fragment.get('prev_updated_at')
                    if prev_updated_at:
                        try:
                            prev_dt = datetime.fromisoformat(str(prev_updated_at))
                        except Exception:
                            prev_dt = None
                        if prev_dt and isinstance(note.get('updated_at'), datetime) and prev_dt < note['updated_at']:
                            results.append({'id': note_id, 'ok': False, 'status': 409, 'error': 'Conflict', 'updated_at': note['updated_at'].isoformat()})
                            continue
                    # stamp scope if missing — אך לא לפתק לוח, שאין לו
                    # scope ולעולם לא יהיה. ראו את השומר המקביל ב-update_note.
                    if not note.get('scope_id') and not note.get('board_id'):
                        scope_id, scope_file_name, _ = _resolve_scope(db, user_id, note.get('file_id'))
                        if scope_id:
                            updates['scope_id'] = scope_id
                            if scope_file_name and 'file_name' not in updates:
                                updates['file_name'] = scope_file_name
                except Exception:
                    pass

                updates['updated_at'] = datetime.now(timezone.utc)
                db.sticky_notes.update_one({'_id': oid, 'user_id': user_id}, {'$set': updates})
                results.append({'id': note_id, 'ok': True, 'status': 200, 'updated_at': updates['updated_at'].isoformat()})
            except Exception as e:
                try:
                    emit_event("sticky_notes_batch_item_error", severity="anomaly", error=str(e))
                except Exception:
                    pass
                nid = None
                try:
                    nid = str((item or {}).get('id') or '')
                except Exception:
                    nid = None
                results.append({'id': nid, 'ok': False, 'status': 500, 'error': 'Failed'})

        resp = jsonify({'ok': True, 'results': results})
        try:
            resp.headers['Cache-Control'] = 'no-store'
        except Exception:
            pass
        return resp
    except Exception as e:
        try:
            emit_event("sticky_notes_batch_error", severity="anomaly", error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to process batch'}), 500


# --- Board notes ---
#
# ראוטים נפרדים לפתקי לוח, ולא הכללה של ``/<file_id>``. הכללה הייתה מכריחה
# כל צרכן להכיר קידוד כלשהו בתוך הפרמטר, ושוברת גם את ה-JS וגם את הטסטים
# שמניחים שהסגמנט הזה הוא מזהה קובץ. אין התנגשות ניתוב: ``/board/<x>`` הוא
# שני סגמנטים ו-``/<file_id>`` אחד — בדיוק כמו ``/note/<id>`` ו-
# ``/reminders/*`` שכבר חיים כאן.
#
# מה שלא חוזר על עצמו כאן בכוונה: ``PUT /note/<id>``, ``DELETE /note/<id>``,
# ``POST /batch`` וכל ראוטי התזכורות מזהים פתק לפי ``_id + user_id`` בלבד,
# ולכן הם עובדים על פתקי לוח בלי שורת קוד אחת. זה כל הרווח של "אוסף פתקים
# אחד": מסלול הכתיבה, ה-debounce, ה-optimistic concurrency וה-keepalive
# מגיעים בירושה.

#: תקרת פתקים ללוח. אותו ערך שמתועד ב-``docs/user/sticky_notes.rst`` וש-
#: ``mcp_server/handlers`` אוכף לקובץ.
MAX_NOTES_PER_BOARD = 200

#: תקרת פתקים למשתמש. הייתה מתועדת ולא נאכפה בשום מקום בקוד.
MAX_NOTES_PER_USER = 1000


def _current_user_is_admin() -> bool:
    """אדמין פטור מתקרות. ``user_roles`` הוא מודול טהור ולכן אין כאן מעגל."""
    try:
        from user_roles import is_admin
        return bool(is_admin(int(session.get('user_id') or 0)))
    except Exception:
        return False


def _count_or_none(coll: Any, query: Dict[str, Any]) -> Optional[int]:
    """ספירה, או ``None`` כשהיא נכשלה.

    ההבחנה חשובה: ``check_note_quota`` דוחה על ``None`` במקום להניח אפס.
    """
    try:
        return int(coll.count_documents(query))
    except Exception:
        return None


def _resolve_owned_board(db: Any, user_id: int, board_id: str) -> Optional[Dict[str, Any]]:
    """הלוח, אם הוא קיים ושייך למשתמש. אחרת ``None``.

    בלי הבדיקה הזו אפשר היה ליצור פתקים על ``board_id`` שרירותי — פתקים
    שאינם נראים בשום ממשק אבל כן נספרים בתקרה. ``mcp_server/backend`` עושה
    את המקבילה לקובץ ומחזיר ``file_not_found``.
    """
    try:
        oid = ObjectId(str(board_id))
    except Exception:
        return None
    try:
        doc = db.note_boards.find_one({'_id': oid, 'user_id': int(user_id)})
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


@sticky_notes_bp.route('/board/<board_id>', methods=['GET'])
@require_auth
@notes_rate_limit('board_list', 180)
@traced("sticky_notes.board_list")
def list_board_notes(board_id: str):
    """פתקי לוח. שאילתה ישירה, בלי ``$or`` ובלי מעבר ב-``code_snippets``."""
    try:
        from sticky_notes_target import board_notes_filter

        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        if not _resolve_owned_board(db, user_id, board_id):
            return jsonify({'ok': False, 'error': 'board_not_found'}), 404

        cursor = db.sticky_notes.find(board_notes_filter(user_id, board_id)).sort('created_at', 1)
        raw_docs = list(cursor) if cursor is not None else []
        notes = [_as_note_response(doc) for doc in raw_docs if isinstance(doc, dict)]

        resp = jsonify({'ok': True, 'notes': notes, 'count': len(notes)})
        try:
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
        except Exception:
            pass
        return resp
    except Exception as e:
        try:
            emit_event("sticky_notes_board_list_error", severity="anomaly", error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to list board notes'}), 500


@sticky_notes_bp.route('/board/<board_id>', methods=['POST'])
@require_auth
@notes_rate_limit('board_create', 60)
@traced("sticky_notes.board_create")
def create_board_note(board_id: str):
    """פתק חדש על לוח."""
    try:
        from sticky_notes_target import (
            DEFAULT_BOARD_MODE,
            NoteQuotaError,
            board_notes_filter,
            build_note_target,
            check_note_quota,
            is_valid_mode,
            normalize_mode,
        )

        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        if not _resolve_owned_board(db, user_id, board_id):
            return jsonify({'ok': False, 'error': 'board_not_found'}), 404

        data = request.get_json(silent=True) or {}

        raw_mode = data.get('mode')
        if raw_mode is not None and not is_valid_mode(raw_mode):
            return jsonify({'ok': False, 'error': 'invalid_mode'}), 400
        mode = normalize_mode(raw_mode, DEFAULT_BOARD_MODE)

        if 'content_b64' in data:
            try:
                content = _decode_content_b64(data.get('content_b64'), max_decoded_chars=5000)
            except ValueError:
                if 'content' in data:
                    content = _sanitize_text(data.get('content', ''), 5000)
                else:
                    return jsonify({'ok': False, 'error': 'Invalid content_b64'}), 400
        else:
            content = _sanitize_text(data.get('content', ''), 5000)

        # תקרות — ולפני הכתיבה, לא אחריה. ``_count_or_none`` מבחין בין אפס
        # לבין ספירה שנכשלה, ו-``check_note_quota`` דוחה על השנייה.
        is_admin_user = _current_user_is_admin()
        try:
            check_note_quota(
                _count_or_none(db.sticky_notes, board_notes_filter(user_id, board_id)),
                MAX_NOTES_PER_BOARD,
                is_admin=is_admin_user,
            )
            check_note_quota(
                _count_or_none(db.sticky_notes, {'user_id': user_id}),
                MAX_NOTES_PER_USER,
                is_admin=is_admin_user,
            )
        except NoteQuotaError as exc:
            return jsonify({'ok': False, 'error': str(exc)}), 409

        pos = data.get('position') or {}
        size = data.get('size') or {}
        color = str(data.get('color', '#FFFFCC') or '#FFFFCC')

        doc: Dict[str, Any] = {
            'user_id': user_id,
            'content': content,
            'position_x': _coerce_int(pos.get('x'), 100, 0, 100000),
            'position_y': _coerce_int(pos.get('y'), 100, 0, 1000000),
            'width': _coerce_int(size.get('width'), 250, 120, 1200),
            'height': _coerce_int(size.get('height'), 200, 80, 1200),
            'color': color if color else '#FFFFCC',
            'is_minimized': bool(data.get('is_minimized', False)),
            'mode': mode,
            'created_at': datetime.now(timezone.utc),
            'updated_at': datetime.now(timezone.utc),
        }
        # שדות היעד עוברים דרך הבנאי, ולא נכתבים כאן ביד. זה מה שמונע
        # ממסמך לצאת עם שני משטחים או בלי אף אחד.
        doc.update(build_note_target(board_id=board_id))

        res = db.sticky_notes.insert_one(doc)
        nid = str(getattr(res, 'inserted_id', ''))
        try:
            emit_event("sticky_note_created", severity="info", user_id=int(user_id), board_id=str(board_id))
        except Exception:
            pass
        resp = jsonify({'ok': True, 'id': nid})
        try:
            resp.headers['Cache-Control'] = 'no-store'
        except Exception:
            pass
        return resp, 201
    except Exception as e:
        try:
            emit_event("sticky_notes_board_create_error", severity="anomaly", error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to create note'}), 500


@sticky_notes_bp.route('/note/<note_id>/task', methods=['POST'])
@require_auth
@notes_rate_limit('note_task_toggle', 300)
@traced("sticky_notes.task_toggle")
def toggle_note_task(note_id: str):
    """מסמן או מבטל צ'קבוקס בתוך פתק.

    **הראוט הזה קיים כדי שאפשר יהיה לאמת את הכתיבה.** האלטרנטיבה — לשלוח
    את התוכן המלא ב-``PUT /note/<id>`` — הופכת כל קליק לדריסת
    last-writer-wins של עריכות מקבילות, ובעיקר הופכת אימות לבלתי אפשרי:
    אפשר לאמת רק שכתבנו את מה ששלחנו. הבקשה כאן נושאת **כוונה** (מספר
    סידורי + מצב רצוי), וזה הדבר היחיד שניתן לאמת מול המסד.

    הסדר, וכל שלב בו מגן על משהו:

    1. הפתק קיים ושייך למשתמש — אחרת 404.
    2. ``prev_updated_at`` — אחרת 409, בדיוק כמו ב-``update_note``.
    3. סידורי שאינו קיים ⇒ **409**, לא 200. התצוגה של הלקוח מיושנת.
    4. כבר במצב המבוקש ⇒ 200 בלי כתיבה. אידמפוטנטי.
    5. Compare-and-swap: הפילטר כולל את התוכן הקודם, כך שכותב מקביל אינו
       נדרס.
    6. **קריאה חוזרת מהמסד** ובדיקה שהתו אכן השתנה. לא ``modified_count``,
       לא ``ok: true`` — אלה מדווחים על הקריאה, לא על המצב.

    בכל מסלול התשובה נושאת את התוכן הסמכותי, כדי שהלקוח יסתנכרן בלי
    סיבוב נוסף — וגם במסלול הכשל, שם זה מה שמאפשר לו להחזיר את התצוגה
    למה שבאמת שמור.
    """
    try:
        from sticky_notes_tasks import task_state_at_index, toggle_task_at_index

        user_id = int(session['user_id'])
        db = get_db()
        try:
            oid = ObjectId(str(note_id))
        except InvalidId:
            return jsonify({'ok': False, 'error': 'Invalid note_id'}), 400

        data = request.get_json(silent=True) or {}
        try:
            index = int(data.get('index'))
        except Exception:
            return jsonify({'ok': False, 'error': 'invalid_index'}), 400
        if index < 0:
            return jsonify({'ok': False, 'error': 'invalid_index'}), 400
        checked = bool(data.get('checked'))

        note = db.sticky_notes.find_one({'_id': oid, 'user_id': user_id})
        if not note:
            return jsonify({'ok': False, 'error': 'Note not found'}), 404

        prev_updated_at = data.get('prev_updated_at')
        if prev_updated_at:
            try:
                prev_dt = datetime.fromisoformat(str(prev_updated_at).replace('Z', '+00:00'))
            except Exception:
                prev_dt = None
            if prev_dt and isinstance(note.get('updated_at'), datetime) and prev_dt < note['updated_at']:
                return jsonify({
                    'ok': False,
                    'error': 'Conflict',
                    'content': note.get('content', ''),
                    'updated_at': note['updated_at'].isoformat(),
                }), 409

        original = note.get('content', '') or ''
        new_content, changed = toggle_task_at_index(original, index, checked)

        if not changed:
            # שתי סיבות אפשריות, ורק אחת מהן תקינה.
            if task_state_at_index(original, index) is None:
                # הסידורי אינו קיים — התצוגה של הלקוח מתארת פתק אחר.
                return jsonify({
                    'ok': False,
                    'error': 'task_index_not_found',
                    'content': original,
                }), 409
            # כבר במצב המבוקש. אין כתיבה, וזה בסדר גמור.
            return jsonify({'ok': True, 'changed': False, 'content': original})

        now = datetime.now(timezone.utc)
        db.sticky_notes.update_one(
            {'_id': oid, 'user_id': user_id, 'content': original},
            {'$set': {'content': new_content, 'updated_at': now}},
        )

        fresh = db.sticky_notes.find_one({'_id': oid, 'user_id': user_id})
        applied = bool(fresh) and task_state_at_index(fresh.get('content', '') or '', index) is checked
        if not applied:
            try:
                emit_event(
                    "sticky_note_task_not_applied",
                    severity="error",
                    user_id=int(user_id),
                    note_id=str(note_id),
                )
            except Exception:
                pass
            return jsonify({
                'ok': False,
                'error': 'task_toggle_not_applied',
                'content': (fresh.get('content', '') if fresh else original),
            }), 409

        fresh_updated = fresh.get('updated_at')
        return jsonify({
            'ok': True,
            'changed': True,
            'content': fresh.get('content', ''),
            'updated_at': fresh_updated.isoformat() if isinstance(fresh_updated, datetime) else None,
        })
    except Exception as e:
        try:
            emit_event("sticky_notes_task_error", severity="anomaly", error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to toggle task'}), 500

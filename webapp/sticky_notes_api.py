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
import hashlib
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

# Module-level guard to ensure indexes only once per process
_INDEX_READY = False

def _ensure_indexes() -> None:
    global _INDEX_READY
    if _INDEX_READY:
        return
    try:
        db = get_db()
        coll = db.sticky_notes
        try:
            from pymongo import ASCENDING, DESCENDING, IndexModel  # type: ignore
            indexes = [
                IndexModel([("user_id", ASCENDING), ("file_id", ASCENDING)], name="user_file_idx"),
                IndexModel([("user_id", ASCENDING), ("file_id", ASCENDING), ("created_at", ASCENDING)], name="user_file_created"),
                IndexModel([("updated_at", DESCENDING)], name="updated_desc"),
            ]
            coll.create_indexes(indexes)
        except Exception:
            # Best-effort: if pymongo typings not available or running in stub env
            try:
                coll.create_index([("user_id", 1), ("file_id", 1)], name="user_file_idx")
                coll.create_index([("user_id", 1), ("file_id", 1), ("created_at", 1)], name="user_file_created")
                coll.create_index([("updated_at", -1)], name="updated_desc")
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

        _INDEX_READY = True
    except Exception:
        # Do not fail requests due to index creation errors
        pass

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
    if not file_name:
        return None
    try:
        normalized = re.sub(r"\s+", " ", str(file_name).strip()).lower()
    except Exception:
        normalized = str(file_name or "").strip().lower()
    if not normalized:
        return None
    digest = hashlib.sha256(f"{user_id}::{normalized}".encode('utf-8')).hexdigest()[:16]
    return f"user:{user_id}:file:{digest}"


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
    try:
        from bson import ObjectId  # type: ignore
    except Exception:
        ObjectId = None  # type: ignore
    try:
        oid = ObjectId(note_id) if ObjectId else note_id
    except Exception:
        oid = note_id
    try:
        note = db.sticky_notes.find_one({'_id': oid, 'user_id': int(user_id)})
    except Exception:
        note = None
    return note if isinstance(note, dict) else None


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
            'status': 'pending',
            'remind_at': dt_utc,
            'snooze_until': None,
            'ack_at': None,
            'updated_at': now_utc,
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
            {'$set': {'status': 'snoozed', 'snooze_until': new_time, 'remind_at': new_time, 'updated_at': datetime.now(timezone.utc), 'ack_at': None}},
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
        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        scope_id, scope_file_name, _ = _resolve_scope(db, user_id, file_id)
        data = request.get_json(silent=True) or {}
        content = _sanitize_text(data.get('content', ''), 5000)
        pos = data.get('position') or {}
        size = data.get('size') or {}
        color = str(data.get('color', '#FFFFCC') or '#FFFFCC')
        is_minimized = bool(data.get('is_minimized', False))
        line_start = data.get('line_start')
        line_end = data.get('line_end')
        anchor_id = (data.get('anchor_id') or '').strip()[:256]
        anchor_text = (data.get('anchor_text') or '').strip()[:256]

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
        if 'content' in data:
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
        if not note.get('scope_id'):
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
                if 'content' in fragment:
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
                    # stamp scope if missing
                    if not note.get('scope_id'):
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

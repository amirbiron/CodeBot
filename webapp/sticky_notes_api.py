"""
Sticky Notes API for Markdown preview
- Stores user-specific notes per file in MongoDB
- Endpoints: list, create, update, delete
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, session
from functools import wraps
from typing import Any, Dict, Optional
from datetime import datetime, timezone
import html

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


def _sanitize_text(text: Any, max_length: int = 5000) -> str:
    if text is None:
        return ""
    try:
        s = str(text)
    except Exception:
        s = ""
    s = s[:max_length]
    return html.escape(s)


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


def _as_note_response(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'id': str(doc.get('_id')),
        'file_id': str(doc.get('file_id', '')),
        'content': str(doc.get('content', '')),
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
@traced("sticky_notes.list")
def list_notes(file_id: str):
    """List all sticky notes for current user and file."""
    try:
        _ensure_indexes()
        user_id = int(session['user_id'])
        db = get_db()
        cursor = db.sticky_notes.find({'user_id': user_id, 'file_id': str(file_id)}).sort('created_at', 1)
        notes = [
            _as_note_response(doc) for doc in (list(cursor) if cursor is not None else []) if isinstance(doc, dict)
        ]
        return jsonify({'ok': True, 'notes': notes, 'count': len(notes)})
    except Exception as e:
        try:
            emit_event("sticky_notes_list_error", severity="anomaly", file_id=str(file_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to list notes'}), 500


@sticky_notes_bp.route('/<file_id>', methods=['POST'])
@require_auth
@traced("sticky_notes.create")
def create_note(file_id: str):
    """Create a new sticky note for a file."""
    try:
        _ensure_indexes()
        user_id = int(session['user_id'])
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
        db = get_db()
        res = db.sticky_notes.insert_one(doc)
        nid = str(getattr(res, 'inserted_id', ''))
        try:
            emit_event("sticky_note_created", severity="info", user_id=int(user_id), file_id=str(file_id))
        except Exception:
            pass
        return jsonify({'ok': True, 'id': nid}), 201
    except Exception as e:
        try:
            emit_event("sticky_notes_create_error", severity="anomaly", file_id=str(file_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to create note'}), 500


@sticky_notes_bp.route('/note/<note_id>', methods=['PUT'])
@require_auth
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
        from bson import ObjectId  # type: ignore
        note = db.sticky_notes.find_one({'_id': ObjectId(note_id), 'user_id': user_id})
        if not note:
            return jsonify({'ok': False, 'error': 'Note not found'}), 404
        db.sticky_notes.update_one({'_id': ObjectId(note_id), 'user_id': user_id}, {'$set': updates})
        try:
            emit_event("sticky_note_updated", severity="info", user_id=int(user_id), note_id=str(note_id))
        except Exception:
            pass
        return jsonify({'ok': True})
    except Exception as e:
        try:
            emit_event("sticky_notes_update_error", severity="anomaly", note_id=str(note_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to update note'}), 500


@sticky_notes_bp.route('/note/<note_id>', methods=['DELETE'])
@require_auth
@traced("sticky_notes.delete")
def delete_note(note_id: str):
    """Delete a note; only owner can delete."""
    try:
        user_id = int(session['user_id'])
        db = get_db()
        from bson import ObjectId  # type: ignore
        res = db.sticky_notes.delete_one({'_id': ObjectId(note_id), 'user_id': user_id})
        if int(getattr(res, 'deleted_count', 0) or 0) <= 0:
            return jsonify({'ok': False, 'error': 'Note not found'}), 404
        try:
            emit_event("sticky_note_deleted", severity="info", user_id=int(user_id), note_id=str(note_id))
        except Exception:
            pass
        return jsonify({'ok': True})
    except Exception as e:
        try:
            emit_event("sticky_notes_delete_error", severity="anomaly", note_id=str(note_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to delete note'}), 500

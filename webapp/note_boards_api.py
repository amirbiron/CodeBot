"""
Note Boards API — יצירה, שינוי שם, ומחיקה של לוחות פתקים.

ראוטי **הפתקים** של הלוח חיים ב-``webapp/sticky_notes_api`` ולא כאן, כי שם
כבר יושבים ``require_auth``, ``notes_rate_limit``, ``_sanitize_text``,
``_decode_content_b64``, ``_coerce_int`` ו-``_as_note_response``. שכפול שלהם
לקובץ שני הוא בדיוק סוג הסטייה ש-``sticky_notes_scope`` נוצר כדי למנוע.

מה שכן כאן: הלוחות עצמם — ובעיקר **המחיקה**, שהיא הפעולה היחידה בפיצ'ר
שיכולה לאבד נתונים.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, session

try:  # type: ignore
    from bson import ObjectId  # type: ignore
except Exception:  # pragma: no cover
    def ObjectId(x):  # type: ignore
        s = str(x or "")
        if len(s) != 24:
            raise ValueError("malformed ObjectId")
        return s

try:  # type: ignore
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None

from note_boards import (
    DEFAULT_BOARD_NAME,
    ensure_default_board,
    list_boards,
    normalize_board_name,
    reattach_orphan_notes,
)

note_boards_bp = Blueprint("note_boards", __name__, url_prefix="/api/note-boards")

#: תקרת לוחות למשתמש. האפיון אומר "ללא הגבלת מספר", והכוונה היא שהמשתמש לא
#: ייתקל בתקרה בשימוש רגיל — לא שאין תקרה בכלל. בלי שום גבול, באג בלקוח
#: שיוצר לוח בלולאה ימלא את האוסף בשקט.
MAX_BOARDS_PER_USER = 500


def get_db():
    from webapp.app import get_db as _get_db  # local import to avoid circulars
    return _get_db()


def require_auth(f):
    @wraps(f)
    def _inner(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return _inner


def _board_response(doc: Dict[str, Any], note_count: Optional[int] = None) -> Dict[str, Any]:
    out = {
        'id': str(doc.get('_id')),
        'name': str(doc.get('name') or DEFAULT_BOARD_NAME),
        'is_default': bool(doc.get('is_default', False)),
        'order': int(doc.get('order') or 0),
        'created_at': (doc.get('created_at').isoformat() if doc.get('created_at') else None),
        'updated_at': (doc.get('updated_at').isoformat() if doc.get('updated_at') else None),
    }
    if note_count is not None:
        out['note_count'] = int(note_count)
    return out


def _owned_board(db: Any, user_id: int, board_id: str) -> Optional[Dict[str, Any]]:
    try:
        oid = ObjectId(str(board_id))
    except Exception:
        return None
    try:
        doc = db.note_boards.find_one({'_id': oid, 'user_id': int(user_id)})
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


@note_boards_bp.route('', methods=['GET'])
@note_boards_bp.route('/', methods=['GET'])
@require_auth
def list_user_boards():
    """רשימת הלוחות, עם מונה פתקים לכל אחד.

    בדרך: יצירת לוח ברירת המחדל אם חסר, וסריקת פתקים יתומים. שתי הפעולות
    אידמפוטנטיות, וזו הנקודה הטבעית להריץ אותן — היא נטענת בכל כניסה לעמוד.
    """
    try:
        user_id = int(session['user_id'])
        db = get_db()

        default_id = ensure_default_board(db, user_id)
        boards = list_boards(db, user_id)
        known_ids = [str(b.get('_id')) for b in boards]

        reattached = 0
        if default_id:
            reattached = reattach_orphan_notes(db, user_id, known_ids, default_id)
            if reattached:
                emit_event(
                    "note_board_orphans_reattached",
                    severity="anomaly",
                    user_id=int(user_id),
                    count=int(reattached),
                )

        items = []
        for board in boards:
            try:
                count = db.sticky_notes.count_documents({
                    'user_id': user_id,
                    'board_id': str(board.get('_id')),
                })
            except Exception:
                count = None
            items.append(_board_response(board, count))

        resp = jsonify({'ok': True, 'boards': items, 'count': len(items), 'reattached': reattached})
        try:
            resp.headers['Cache-Control'] = 'no-store'
        except Exception:
            pass
        return resp
    except Exception as e:
        try:
            emit_event("note_boards_list_error", severity="anomaly", error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to list boards'}), 500


@note_boards_bp.route('', methods=['POST'])
@note_boards_bp.route('/', methods=['POST'])
@require_auth
def create_board():
    """לוח חדש."""
    try:
        user_id = int(session['user_id'])
        db = get_db()
        data = request.get_json(silent=True) or {}
        name = normalize_board_name(data.get('name'))

        try:
            existing = int(db.note_boards.count_documents({'user_id': user_id}))
        except Exception:
            # ספירה שנכשלה אינה "אין לוחות". אותה הכרעה כמו בתקרת הפתקים.
            return jsonify({'ok': False, 'error': 'board_quota_unknown'}), 409
        if existing >= MAX_BOARDS_PER_USER:
            return jsonify({'ok': False, 'error': 'board_quota_exceeded'}), 409

        now = datetime.now(timezone.utc)
        doc = {
            'user_id': user_id,
            'name': name,
            'is_default': False,
            'order': existing,
            'created_at': now,
            'updated_at': now,
        }
        res = db.note_boards.insert_one(doc)
        new_id = getattr(res, 'inserted_id', None)

        # אימות בקריאה חוזרת. ``inserted_id`` שחזר אינו מוכיח שהמסמך קיים,
        # ולוח שאינו קיים הוא לוח שכל פתק שינחת עליו ייעלם מהממשק.
        created = db.note_boards.find_one({'_id': new_id, 'user_id': user_id}) if new_id is not None else None
        if not created:
            emit_event("note_board_create_not_applied", severity="error", user_id=int(user_id))
            return jsonify({'ok': False, 'error': 'board_create_not_applied'}), 500

        return jsonify({'ok': True, 'board': _board_response(created, 0)}), 201
    except Exception as e:
        try:
            emit_event("note_boards_create_error", severity="anomaly", error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to create board'}), 500


@note_boards_bp.route('/<board_id>', methods=['PATCH'])
@require_auth
def rename_board(board_id: str):
    """שינוי שם. מותר גם ללוח ברירת המחדל — הזיהוי שלו הוא ``is_default``."""
    try:
        user_id = int(session['user_id'])
        db = get_db()
        board = _owned_board(db, user_id, board_id)
        if not board:
            return jsonify({'ok': False, 'error': 'board_not_found'}), 404

        data = request.get_json(silent=True) or {}
        if 'name' not in data:
            return jsonify({'ok': False, 'error': 'no_fields_to_update'}), 400
        name = normalize_board_name(data.get('name'))

        db.note_boards.update_one(
            {'_id': board['_id'], 'user_id': user_id},
            {'$set': {'name': name, 'updated_at': datetime.now(timezone.utc)}},
        )
        fresh = db.note_boards.find_one({'_id': board['_id'], 'user_id': user_id})
        if not fresh or str(fresh.get('name') or '') != name:
            return jsonify({'ok': False, 'error': 'rename_not_applied'}), 409
        return jsonify({'ok': True, 'board': _board_response(fresh)})
    except Exception as e:
        try:
            emit_event("note_boards_rename_error", severity="anomaly", error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to rename board'}), 500


@note_boards_bp.route('/<board_id>', methods=['DELETE'])
@require_auth
def delete_board(board_id: str):
    """מחיקת לוח, אחרי העברת הפתקים שעליו ללוח ברירת המחדל.

    זו הפעולה היחידה בפיצ'ר שיכולה לאבד נתונים, ולכן הסדר כאן אינו מקרי:

    1. לוח ברירת מחדל — חסום. באוספים אין חסימה כזו בכלל, וזו סטייה מכוונת:
       מחיקת אוסף מאבדת סידור, מחיקת לוח מאבדת את המקום היחיד של הפתק.
    2. ``ensure_default_board`` — ולא הנחה שהיעד קיים.
    3. ספירה **לפני** ההעברה, כי ``modified_count`` מדווח בחסר כשמסמך כבר
       היה בערך היעד, וממילא אסור להסתמך עליו.
    4. אחרי ההעברה — **ספירה חוזרת**. אם נשארו פתקים, עוצרים ולא מוחקים.
       הלוח שורד, אפשר לנסות שוב, ואף פתק לא מתייתם.
    """
    try:
        user_id = int(session['user_id'])
        db = get_db()
        board = _owned_board(db, user_id, board_id)
        if not board:
            return jsonify({'ok': False, 'error': 'board_not_found'}), 404
        if bool(board.get('is_default')):
            return jsonify({'ok': False, 'error': 'cannot_delete_default'}), 409

        default_id = ensure_default_board(db, user_id)
        if not default_id:
            return jsonify({'ok': False, 'error': 'default_board_unavailable'}), 500

        src = str(board.get('_id'))
        src_query = {'user_id': user_id, 'board_id': src}
        try:
            moved_expected = int(db.sticky_notes.count_documents(src_query))
        except Exception:
            return jsonify({'ok': False, 'error': 'notes_count_failed'}), 500

        if moved_expected:
            db.sticky_notes.update_many(
                src_query,
                {'$set': {'board_id': str(default_id), 'updated_at': datetime.now(timezone.utc)}},
            )
            try:
                remaining = int(db.sticky_notes.count_documents(src_query))
            except Exception:
                return jsonify({'ok': False, 'error': 'notes_count_failed'}), 500
            if remaining:
                emit_event(
                    "note_board_delete_aborted",
                    severity="error",
                    user_id=int(user_id),
                    board_id=src,
                    remaining=int(remaining),
                )
                return jsonify({
                    'ok': False,
                    'error': 'notes_move_incomplete',
                    'remaining': remaining,
                }), 500

        db.note_boards.delete_one({'_id': board['_id'], 'user_id': user_id})
        still_there = db.note_boards.find_one({'_id': board['_id'], 'user_id': user_id})
        if still_there:
            return jsonify({'ok': False, 'error': 'board_delete_not_applied'}), 500

        return jsonify({
            'ok': True,
            'moved': moved_expected,
            'target_board_id': str(default_id),
        })
    except Exception as e:
        try:
            emit_event("note_boards_delete_error", severity="anomaly", error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'Failed to delete board'}), 500

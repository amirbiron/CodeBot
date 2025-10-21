"""
Bookmarks API Endpoints for WebApp
"""
from flask import Blueprint, jsonify, request, session
from bson import ObjectId
from functools import wraps
from typing import Optional, Dict
import logging
import html

from database.bookmarks_manager import BookmarksManager
from database.bookmark import VALID_COLORS as MODEL_VALID_COLORS

logger = logging.getLogger(__name__)

# Observability: structured events and internal alerts (fail-open stubs)
try:  # type: ignore
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None
try:  # type: ignore
    from internal_alerts import emit_internal_alert  # type: ignore
except Exception:  # pragma: no cover
    def emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):  # type: ignore
        return None


def _get_request_id() -> str:
    try:
        rid = getattr(request, "_req_id", "")
        if not rid:
            rid = request.headers.get("X-Request-ID", "")
        return rid or ""
    except Exception:
        return ""

# יצירת Blueprint
bookmarks_bp = Blueprint('bookmarks', __name__, url_prefix='/api/bookmarks')


# ==================== Internal helpers (placed before routes) ====================

def _get_file_info(file_id: str) -> Optional[Dict[str, str]]:
    """שליפת פרטי קובץ לפי מזהה לשימוש ה-API.
    מקור האמת הוא אוסף code_snippets, בהתאם לקוד האפליקציה.
    """
    try:
        db = get_db()
        from bson import ObjectId as _ObjectId
        doc = db.code_snippets.find_one({'_id': _ObjectId(file_id)})
        if not doc:
            return None
        file_name = doc.get('file_name', '')
        file_path = (
            doc.get('file_path')
            or doc.get('path')
            or file_name
        )
        return {
            'file_name': file_name,
            'file_path': file_path,
        }
    except Exception:
        return None


def get_db():
    """Get database instance - implement based on your setup"""
    from webapp.app import get_db as _get_db
    return _get_db()


def get_bookmarks_manager():
    """Get bookmarks manager instance"""
    return BookmarksManager(get_db())


# ==================== Decorators ====================

def require_auth(f):
    """Decorator to check if user is authenticated"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function


def sanitize_input(text: str, max_length: int = 500) -> str:
    """Sanitize user input to prevent XSS"""
    if not text:
        return ""
    
    # הגבלת אורך
    text = str(text)[:max_length]
    
    # HTML escape
    text = html.escape(text)
    
    return text


# ==================== API Endpoints ====================

@bookmarks_bp.route('/<file_id>/toggle', methods=['POST'])
@require_auth
def toggle_bookmark(file_id):
    """
    Toggle bookmark for a specific line in a file.

    Args:
        file_id: The ID of the file to toggle a bookmark for.

    Returns:
        A Flask response with a JSON body describing the action performed.

    Example:
        Request JSON::

            {"line_number": 12, "line_text": "print('hi')", "note": "בדיקה", "color": "yellow"}

        Response JSON::

            {"ok": true, "action": "added", "bookmark": {"line_number": 12, "color": "yellow"}, "error": null}
    """
    try:
        user_id = session['user_id']
        data = request.get_json()
        
        # ולידציה: עיגון לפי מספר שורה או לפי anchor_id
        if not data:
            return jsonify({'ok': False, 'error': 'Missing request body'}), 400

        anchor_id = (data.get('anchor_id') or '').strip()
        anchor_text = (data.get('anchor_text') or '').strip()
        anchor_type = (data.get('anchor_type') or '').strip()

        if anchor_id:
            # במצב עוגן – line_number יכול להיות 0/None
            try:
                line_number = int(data.get('line_number') or 0)
            except Exception:
                line_number = 0
            if len(anchor_id) > 256:
                anchor_id = anchor_id[:256]
            if len(anchor_text) > 256:
                anchor_text = anchor_text[:256]
        else:
            if 'line_number' not in data:
                return jsonify({'ok': False, 'error': 'Missing line_number'}), 400
            line_number = data.get('line_number')
            if not isinstance(line_number, int) or line_number <= 0:
                return jsonify({'ok': False, 'error': 'Invalid line_number'}), 400
        
        # סניטציה של קלט
        line_text = sanitize_input(data.get('line_text', ''), 100)
        note = sanitize_input(data.get('note', ''), 500)
        color = data.get('color', 'yellow')
        
        # ולידציה של צבע
        valid_colors = list(MODEL_VALID_COLORS)
        if color not in valid_colors:
            color = 'yellow'
        
        # קבלת פרטי הקובץ
        file_info = _get_file_info(file_id)
        
        if not file_info:
            return jsonify({'ok': False, 'error': 'File not found'}), 404
        
        # ביצוע toggle
        bm_manager = get_bookmarks_manager()
        result = bm_manager.toggle_bookmark(
            user_id=user_id,
            file_id=file_id,
            file_name=file_info.get('file_name', ''),
            file_path=file_info.get('file_path', ''),
            line_number=line_number,
            line_text=line_text,
            note=note,
            color=color,
            anchor_id=(anchor_id or None),
            anchor_text=(anchor_text or None),
            anchor_type=(anchor_type or None)
        )
        
        return jsonify(result)
        
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_toggle_error",
                severity="anomaly",
                operation="bookmarks.toggle",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                file_id=str(file_id),
                error=str(e),
            )
            emit_internal_alert(
                name="bookmarks_toggle_failed",
                severity="anomaly",
                summary=f"file_id={file_id}, request_id={rid or 'n/a'}",
                user_id=int(uid) if uid is not None else None,
            )
        except Exception:
            pass
        logger.error(f"Error in toggle_bookmark: {e}", exc_info=True)
        return jsonify({'ok': False, 'error': 'Internal server error'}), 500


@bookmarks_bp.route('/<file_id>', methods=['GET'])
@require_auth
def get_file_bookmarks(file_id):
    """
    Get all bookmarks for a specific file.

    Query parameters:
    - include_invalid: bool (default: false) – whether to include invalid bookmarks

    Returns:
        A Flask response with a JSON body containing the bookmarks and count.
    """
    try:
        user_id = session['user_id']
        include_invalid = request.args.get('include_invalid', 'false').lower() == 'true'
        
        bm_manager = get_bookmarks_manager()
        bookmarks = bm_manager.get_file_bookmarks(user_id, file_id, include_invalid)
        
        return jsonify({
            'ok': True,
            'bookmarks': bookmarks,
            'count': len(bookmarks)
        })
        
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_get_file_error",
                severity="anomaly",
                operation="bookmarks.get_file",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                file_id=str(file_id),
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error getting file bookmarks: {e}")
        return jsonify({'ok': False, 'error': 'Failed to get bookmarks'}), 500


@bookmarks_bp.route('/all', methods=['GET'])
@require_auth
def get_all_bookmarks():
    """
    Get all bookmarks for the current user.

    Query parameters:
    - limit: int (default: 100)
    - skip: int (default: 0)

    Returns:
        A Flask response with aggregated bookmarks grouped by files.
    """
    try:
        user_id = session['user_id']
        # Guard query params: default and validate non-numeric values
        limit_raw = request.args.get('limit')
        skip_raw = request.args.get('skip')

        try:
            limit = int(limit_raw) if (limit_raw not in (None, "")) else 100
            skip = int(skip_raw) if (skip_raw not in (None, "")) else 0
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Invalid limit/skip'}), 400

        # clamp values
        if limit < 1:
            limit = 1
        if limit > 500:
            limit = 500
        if skip < 0:
            skip = 0
        
        bm_manager = get_bookmarks_manager()
        result = bm_manager.get_user_bookmarks(user_id, limit, skip)
        
        return jsonify(result)
        
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_get_all_error",
                severity="anomaly",
                operation="bookmarks.get_all",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error getting all bookmarks: {e}")
        return jsonify({'ok': False, 'error': 'Failed to get bookmarks'}), 500


@bookmarks_bp.route('/<file_id>/<int:line_number>/note', methods=['PUT'])
@require_auth
def update_bookmark_note(file_id, line_number):
    """
    Update note for a specific bookmark.

    Example:
        Request JSON::

            {"note": "כאן הערה"}
    """
    try:
        user_id = session['user_id']
        data = request.get_json()
        
        if not data or 'note' not in data:
            return jsonify({'ok': False, 'error': 'Missing note'}), 400
        
        note = sanitize_input(data['note'], 500)
        
        anchor_id = (data.get('anchor_id') or '').strip()
        bm_manager = get_bookmarks_manager()
        if anchor_id:
            result = bm_manager.update_bookmark_note_by_anchor(user_id, file_id, anchor_id, note)
        else:
            result = bm_manager.update_bookmark_note(user_id, file_id, line_number, note)
        
        return jsonify(result)
        
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_update_note_error",
                severity="anomaly",
                operation="bookmarks.update_note",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                file_id=str(file_id),
                line_number=int(line_number),
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error updating bookmark note: {e}")
        return jsonify({'ok': False, 'error': 'Failed to update note'}), 500


@bookmarks_bp.route('/<file_id>/<int:line_number>/color', methods=['PUT'])
@require_auth
def update_bookmark_color(file_id, line_number):
    """עדכון צבע של סימנייה"""
    try:
        user_id = session['user_id']
        data = request.get_json()
        if not data or 'color' not in data:
            return jsonify({'ok': False, 'error': 'Missing color'}), 400
        color = str(data.get('color', 'yellow')).lower()

        # ולידציה של צבע מול המודל
        if color not in MODEL_VALID_COLORS:
            return jsonify({'ok': False, 'error': 'Invalid color'}), 400

        anchor_id = (data.get('anchor_id') or '').strip()
        bm_manager = get_bookmarks_manager()
        if anchor_id:
            result = bm_manager.update_bookmark_color_by_anchor(user_id, file_id, anchor_id, color)
        else:
            result = bm_manager.update_bookmark_color(user_id, file_id, line_number, color)
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_update_color_error",
                severity="anomaly",
                operation="bookmarks.update_color",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                file_id=str(file_id),
                line_number=int(line_number),
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error updating bookmark color: {e}")
        return jsonify({'ok': False, 'error': 'Failed to update color'}), 500


@bookmarks_bp.route('/<file_id>/<int:line_number>', methods=['DELETE'])
@require_auth
def delete_bookmark(file_id, line_number):
    """Delete a specific bookmark"""
    try:
        user_id = session['user_id']
        
        anchor_id = (request.args.get('anchor_id') or '').strip()
        bm_manager = get_bookmarks_manager()
        if anchor_id:
            result = bm_manager.delete_bookmark_by_anchor(user_id, file_id, anchor_id)
        else:
            result = bm_manager.delete_bookmark(user_id, file_id, line_number)
        
        return jsonify(result)
        
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_delete_error",
                severity="anomaly",
                operation="bookmarks.delete",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                file_id=str(file_id),
                line_number=int(line_number),
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error deleting bookmark: {e}")
        return jsonify({'ok': False, 'error': 'Failed to delete bookmark'}), 500


@bookmarks_bp.route('/<file_id>/clear', methods=['DELETE'])
@require_auth
def clear_file_bookmarks(file_id):
    """Delete all bookmarks for a specific file"""
    try:
        user_id = session['user_id']
        
        bm_manager = get_bookmarks_manager()
        result = bm_manager.delete_file_bookmarks(user_id, file_id)
        
        return jsonify(result)
        
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_clear_file_error",
                severity="anomaly",
                operation="bookmarks.clear_file",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                file_id=str(file_id),
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error clearing file bookmarks: {e}")
        return jsonify({'ok': False, 'error': 'Failed to clear bookmarks'}), 500


@bookmarks_bp.route('/<file_id>/sync', methods=['POST'])
@require_auth
def check_file_sync(file_id):
    """
    Check if bookmarks need sync due to file changes.

    Request JSON: {"content": "<file content>"}

    Returns: {"changed": bool, "affected": [...]}
    """
    try:
        data = request.get_json()
        
        if not data or 'content' not in data:
            return jsonify({'ok': False, 'error': 'Missing file content'}), 400
        
        bm_manager = get_bookmarks_manager()
        result = bm_manager.check_file_sync(file_id, data['content'])
        
        return jsonify(result)
        
    except Exception as e:
        rid = _get_request_id()
        try:
            emit_event(
                "bookmarks_check_sync_error",
                severity="anomaly",
                operation="bookmarks.check_sync",
                handled=True,
                request_id=rid,
                file_id=str(file_id),
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error checking file sync: {e}")
        return jsonify({'ok': False, 'error': 'Failed to check sync'}), 500


@bookmarks_bp.route('/stats', methods=['GET'])
@require_auth
def get_bookmark_stats():
    """Get bookmark statistics for current user"""
    try:
        user_id = session['user_id']
        
        bm_manager = get_bookmarks_manager()
        stats = bm_manager.get_user_stats(user_id)
        
        return jsonify({
            'ok': True,
            'stats': stats
        })
        
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_get_stats_error",
                severity="anomaly",
                operation="bookmarks.get_stats",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error getting bookmark stats: {e}")
        return jsonify({'ok': False, 'error': 'Failed to get stats'}), 500


@bookmarks_bp.route('/export', methods=['GET'])
@require_auth
def export_bookmarks():
    """Export all user bookmarks as JSON"""
    try:
        user_id = session['user_id']
        
        bm_manager = get_bookmarks_manager()
        result = bm_manager.get_user_bookmarks(user_id, limit=1000)
        
        if not result.get('ok'):
            return jsonify({'ok': False, 'error': 'Failed to export'}), 500
        
        from flask import make_response
        from datetime import datetime
        import json
        
        export_data = {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "files": result['files'],
            "total_bookmarks": result['total_bookmarks']
        }
        
        response = make_response(json.dumps(export_data, indent=2, ensure_ascii=False))
        response.headers['Content-Type'] = 'application/json'
        response.headers['Content-Disposition'] = 'attachment; filename=bookmarks_export.json'
        
        return response
        
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_export_error",
                severity="anomaly",
                operation="bookmarks.export",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                error=str(e),
            )
            emit_internal_alert(
                name="bookmarks_export_failed",
                severity="anomaly",
                summary=f"request_id={rid or 'n/a'}",
                user_id=int(uid) if uid is not None else None,
            )
        except Exception:
            pass
        logger.error(f"Error exporting bookmarks: {e}")
        return jsonify({'ok': False, 'error': 'Failed to export'}), 500


# ==================== User preferences (default color) ====================

@bookmarks_bp.route('/prefs', methods=['GET'])
@require_auth
def get_prefs():
    """החזרת העדפות סימניות של המשתמש (צבע ברירת מחדל)."""
    try:
        db = get_db()
        user_id = session['user_id']
        user = db.users.find_one({'user_id': user_id}) or {}
        prefs = (user.get('bookmark_prefs') or {})
        default_color = (prefs.get('default_color') or 'yellow')
        if default_color not in MODEL_VALID_COLORS:
            default_color = 'yellow'
        return jsonify({
            'ok': True,
            'default_color': default_color,
            'valid_colors': list(MODEL_VALID_COLORS),
        })
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_get_prefs_error",
                severity="anomaly",
                operation="bookmarks.get_prefs",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error getting bookmark prefs: {e}")
        return jsonify({'ok': False, 'error': 'Failed to get prefs'}), 500


@bookmarks_bp.route('/prefs', methods=['PUT'])
@require_auth
def set_prefs():
    """עדכון צבע ברירת מחדל לסימניות עבור המשתמש."""
    try:
        from datetime import datetime, timezone
        db = get_db()
        user_id = session['user_id']
        data = request.get_json(silent=True) or {}
        color = (data.get('default_color') or data.get('color') or 'yellow').lower()
        if color not in MODEL_VALID_COLORS:
            return jsonify({'ok': False, 'error': 'Invalid color'}), 400
        db.users.update_one(
            {'user_id': user_id},
            {'$set': {
                'bookmark_prefs.default_color': color,
                'updated_at': datetime.now(timezone.utc)
            }},
            upsert=True
        )
        return jsonify({'ok': True, 'default_color': color})
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event(
                "bookmarks_set_prefs_error",
                severity="anomaly",
                operation="bookmarks.set_prefs",
                handled=True,
                request_id=rid,
                user_id=int(uid) if uid is not None else None,
                error=str(e),
            )
        except Exception:
            pass
        logger.error(f"Error setting bookmark prefs: {e}")
        return jsonify({'ok': False, 'error': 'Failed to set prefs'}), 500


# ==================== Internal helpers ====================

def _get_file_info(file_id: str) -> dict | None:
    """שליפת פרטי קובץ לפי מזהה לשימוש ה-API"""
    try:
        db = get_db()
        doc = db.code_snippets.find_one({'_id': ObjectId(file_id)})
        if not doc:
            return None
        return {
            'file_name': doc.get('file_name', ''),
            'file_path': doc.get('file_name', ''),  # אין נתיב אמיתי — נשמור file_name
        }
    except Exception:
        return None


# ==================== Error Handlers ====================

@bookmarks_bp.errorhandler(404)
def not_found(error):
    return jsonify({'ok': False, 'error': 'Endpoint not found'}), 404


@bookmarks_bp.errorhandler(500)
def internal_error(error):
    try:
        rid = _get_request_id()
        uid = session.get('user_id')
        emit_event(
            "bookmarks_internal_error",
            severity="error",
            operation="bookmarks.internal_error",
            request_id=rid,
            user_id=int(uid) if uid is not None else None,
            error=str(error),
        )
    except Exception:
        pass
    logger.error(f"Internal error: {error}")
    return jsonify({'ok': False, 'error': 'Internal server error'}), 500

"""
Collections API Endpoints for WebApp (My Collections)

MVP: ידני בלבד + חוקים בסיסיים (compute_smart_items) ללא שיתוף/ייצוא.
מוגן ע"י require_auth, כולל dynamic_cache ואירועי observability.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, session
from functools import wraps
from typing import Optional, Dict, Any, List
import html
import logging

from cache_manager import dynamic_cache, cache
try:
    from config import config as _cfg  # type: ignore
except Exception:  # pragma: no cover
    _cfg = None  # type: ignore

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

# Manual tracing decorator (fail-open)
try:  # type: ignore
    from observability_instrumentation import traced  # type: ignore
except Exception:  # pragma: no cover
    def traced(*_a, **_k):  # type: ignore
        def _inner(f):
            return f
        return _inner


# Blueprint
# חשוב: אין לקבוע url_prefix כאן; הרישום מתבצע ב-app עם '/api/collections'
collections_bp = Blueprint('collections', __name__)
# Alias for conventional import style in app registration
# Some environments expect `collections_api.bp` by convention.
bp = collections_bp


# ==================== Helpers ====================

def _get_request_id() -> str:
    try:
        rid = getattr(request, "_req_id", "")
        if not rid:
            rid = request.headers.get("X-Request-ID", "")
        return rid or ""
    except Exception:
        return ""


def get_db():
    from webapp.app import get_db as _get_db
    return _get_db()


def get_manager():
    from database.collections_manager import CollectionsManager
    return CollectionsManager(get_db())


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


def sanitize_input(text: str, max_length: int = 500) -> str:
    if not text:
        return ""
    s = str(text)[:max_length]
    return html.escape(s)


def _build_public_collection_url(token: str) -> str:
    try:
        base = getattr(_cfg, 'PUBLIC_BASE_URL', None) if _cfg is not None else None
        if not base:
            # Fallback: נשתמש ב-host_url הנוכחי
            base = getattr(request, 'host_url', '') or ''
        base = str(base).rstrip('/')
        return f"{base}/api/collections/shared/{token}"
    except Exception:
        return f"/api/collections/shared/{token}"


# ==================== Endpoints ====================

@collections_bp.route('', methods=['POST'])
@require_auth
@traced("collections.create")
def create_collection():
    try:
        user_id = int(session['user_id'])
        data = request.get_json(silent=True) or {}
        name = sanitize_input(data.get('name', ''), 80)
        description = sanitize_input(data.get('description', ''), 500)
        mode = str(data.get('mode', 'manual')).lower()
        rules = data.get('rules') or {}
        icon = data.get('icon')
        color = data.get('color')
        is_favorite = bool(data.get('is_favorite', False))
        sort_order = data.get('sort_order')

        mgr = get_manager()
        result = mgr.create_collection(
            user_id=user_id,
            name=name,
            description=description,
            mode=mode,
            rules=rules if isinstance(rules, dict) else {},
            icon=icon,
            color=color,
            is_favorite=is_favorite,
            sort_order=sort_order if isinstance(sort_order, int) else None,
        )
        if result.get('ok'):
            # Invalidate list/detail caches
            try:
                uid = str(user_id)
                cache.delete_pattern(f"collections_list:{uid}:*")
                if result.get('collection') and result['collection'].get('id'):
                    cid = result['collection']['id']
                    cache.delete_pattern(f"collections_detail:{uid}:-api-collections-{cid}*")
            except Exception:
                pass
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event("collections_create_error", severity="anomaly", operation="collections.create", handled=True, request_id=rid, user_id=int(uid) if uid else None, error=str(e))
        except Exception:
            pass
        logger.error("Error creating collection: %s", e, exc_info=True)
        return jsonify({'ok': False, 'error': 'שגיאה ביצירת האוסף'}), 500


@collections_bp.route('', methods=['GET'])
@require_auth
@traced("collections.list")
@dynamic_cache(content_type='collections_list', key_prefix='collections_list')
def list_collections():
    try:
        user_id = int(session['user_id'])
        try:
            limit = int(request.args.get('limit') or 100)
            skip = int(request.args.get('skip') or 0)
        except Exception:
            return jsonify({'ok': False, 'error': 'Invalid limit/skip'}), 400
        mgr = get_manager()
        result = mgr.list_collections(user_id, limit=limit, skip=skip)
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        uid = session.get('user_id')
        try:
            emit_event("collections_get_list_error", severity="anomaly", operation="collections.list", handled=True, request_id=rid, user_id=int(uid) if uid else None, error=str(e))
        except Exception:
            pass
        logger.error("Error listing collections: %s", e)
        return jsonify({'ok': False, 'error': 'שגיאה בשליפת האוספים'}), 500


@collections_bp.route('/<collection_id>', methods=['GET'])
@require_auth
@traced("collections.get")
@dynamic_cache(content_type='collections_detail', key_prefix='collections_detail')
def get_collection(collection_id: str):
    try:
        user_id = int(session['user_id'])
        mgr = get_manager()
        result = mgr.get_collection(user_id, collection_id)
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        try:
            emit_event("collections_get_detail_error", severity="anomaly", operation="collections.get", handled=True, request_id=rid, collection_id=str(collection_id), error=str(e))
        except Exception:
            pass
        logger.error("Error getting collection: %s", e)
        return jsonify({'ok': False, 'error': 'שגיאה בשליפת האוסף'}), 500


@collections_bp.route('/<collection_id>', methods=['PUT'])
@require_auth
@traced("collections.update")
def update_collection(collection_id: str):
    try:
        user_id = int(session['user_id'])
        data = request.get_json(silent=True) or {}
        # sanitize string fields only
        for key in ('name', 'description', 'icon', 'color'):
            if key in data and isinstance(data[key], str):
                data[key] = sanitize_input(data[key], 80 if key == 'name' else 500)
        mgr = get_manager()
        result = mgr.update_collection(user_id, collection_id, **data)
        if result.get('ok'):
            try:
                uid = str(user_id)
                cache.delete_pattern(f"collections_list:{uid}:*")
                cache.delete_pattern(f"collections_detail:{uid}:-api-collections-{collection_id}*")
            except Exception:
                pass
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        try:
            emit_event("collections_update_error", severity="anomaly", operation="collections.update", handled=True, request_id=rid, collection_id=str(collection_id), error=str(e))
        except Exception:
            pass
        logger.error("Error updating collection: %s", e)
        return jsonify({'ok': False, 'error': 'שגיאה בעדכון האוסף'}), 500


@collections_bp.route('/<collection_id>', methods=['DELETE'])
@require_auth
@traced("collections.delete")
def delete_collection(collection_id: str):
    try:
        user_id = int(session['user_id'])
        mgr = get_manager()
        result = mgr.delete_collection(user_id, collection_id)
        if result.get('ok'):
            try:
                uid = str(user_id)
                cache.delete_pattern(f"collections_list:{uid}:*")
                cache.delete_pattern(f"collections_detail:{uid}:-api-collections-{collection_id}*")
                cache.delete_pattern(f"collections_items:{uid}:-api-collections-{collection_id}-items*")
            except Exception:
                pass
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        try:
            emit_event("collections_delete_error", severity="anomaly", operation="collections.delete", handled=True, request_id=rid, collection_id=str(collection_id), error=str(e))
        except Exception:
            pass
        logger.error("Error deleting collection: %s", e)
        return jsonify({'ok': False, 'error': 'שגיאה במחיקת האוסף'}), 500


@collections_bp.route('/<collection_id>/items', methods=['GET'])
@require_auth
@traced("collections.items")
@dynamic_cache(content_type='collections_items', key_prefix='collections_items')
def get_items(collection_id: str):
    try:
        user_id = int(session['user_id'])
        try:
            page = int(request.args.get('page') or 1)
            per_page = int(request.args.get('per_page') or 20)
        except Exception:
            return jsonify({'ok': False, 'error': 'Invalid page/per_page'}), 400
        include_computed = str(request.args.get('include_computed', 'true')).lower() == 'true'
        mgr = get_manager()
        result = mgr.get_collection_items(user_id, collection_id, page=page, per_page=per_page, include_computed=include_computed)
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        try:
            emit_event("collections_get_items_error", severity="anomaly", operation="collections.get_items", handled=True, request_id=rid, collection_id=str(collection_id), error=str(e))
        except Exception:
            pass
        logger.error("Error getting items: %s", e)
        return jsonify({'ok': False, 'error': 'שגיאה בשליפת פריטים'}), 500


@collections_bp.route('/<collection_id>/items', methods=['POST'])
@require_auth
@traced("collections.items_add")
def add_items(collection_id: str):
    try:
        user_id = int(session['user_id'])
        data = request.get_json(silent=True) or {}
        items = data.get('items') or []
        if not isinstance(items, list):
            return jsonify({'ok': False, 'error': 'items must be a list'}), 400
        # sanitize notes
        for it in items:
            if isinstance(it, dict) and 'note' in it and isinstance(it['note'], str):
                it['note'] = sanitize_input(it['note'], 500)
        mgr = get_manager()
        result = mgr.add_items(user_id, collection_id, items)
        if result.get('ok'):
            try:
                uid = str(user_id)
                cache.delete_pattern(f"collections_items:{uid}:-api-collections-{collection_id}-items*")
                cache.delete_pattern(f"collections_detail:{uid}:-api-collections-{collection_id}*")
                cache.delete_pattern(f"collections_list:{uid}:*")
            except Exception:
                pass
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        try:
            emit_event("collections_items_add_error", severity="anomaly", operation="collections.items_add", handled=True, request_id=rid, collection_id=str(collection_id), error=str(e))
        except Exception:
            pass
        logger.error("Error adding items: %s", e)
        return jsonify({'ok': False, 'error': 'שגיאה בהוספת פריטים'}), 500


@collections_bp.route('/<collection_id>/items', methods=['DELETE'])
@require_auth
@traced("collections.items_remove")
def remove_items(collection_id: str):
    try:
        user_id = int(session['user_id'])
        data = request.get_json(silent=True) or {}
        items = data.get('items') or []
        if not isinstance(items, list):
            return jsonify({'ok': False, 'error': 'items must be a list'}), 400
        mgr = get_manager()
        result = mgr.remove_items(user_id, collection_id, items)
        if result.get('ok'):
            try:
                uid = str(user_id)
                cache.delete_pattern(f"collections_items:{uid}:-api-collections-{collection_id}-items*")
                cache.delete_pattern(f"collections_detail:{uid}:-api-collections-{collection_id}*")
                cache.delete_pattern(f"collections_list:{uid}:*")
            except Exception:
                pass
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        try:
            emit_event("collections_items_remove_error", severity="anomaly", operation="collections.items_remove", handled=True, request_id=rid, collection_id=str(collection_id), error=str(e))
        except Exception:
            pass
        logger.error("Error removing items: %s", e)
        return jsonify({'ok': False, 'error': 'שגיאה בהסרת פריטים'}), 500


@collections_bp.route('/<collection_id>/reorder', methods=['PUT'])
@require_auth
@traced("collections.reorder")
def reorder_items(collection_id: str):
    try:
        user_id = int(session['user_id'])
        data = request.get_json(silent=True) or {}
        order = data.get('order') or []
        if not isinstance(order, list):
            return jsonify({'ok': False, 'error': 'order must be a list'}), 400
        mgr = get_manager()
        result = mgr.reorder_items(user_id, collection_id, order)
        if result.get('ok'):
            try:
                uid = str(user_id)
                cache.delete_pattern(f"collections_items:{uid}:-api-collections-{collection_id}-items*")
                cache.delete_pattern(f"collections_detail:{uid}:-api-collections-{collection_id}*")
            except Exception:
                pass
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        try:
            emit_event("collections_reorder_error", severity="anomaly", operation="collections.reorder", handled=True, request_id=rid, collection_id=str(collection_id), error=str(e))
        except Exception:
            pass
        logger.error("Error reordering items: %s", e)
        return jsonify({'ok': False, 'error': 'שגיאה בסידור פריטים'}), 500


# --- Phase 2: Share ---

@collections_bp.route('/<collection_id>/share', methods=['POST'])
@require_auth
@traced("collections.share")
def update_share(collection_id: str):
    """הפעלת/ביטול שיתוף עבור אוסף. Body: {enabled: bool, visibility?: 'private'|'link'}"""
    try:
        user_id = int(session['user_id'])
        data = request.get_json(silent=True) or {}
        if 'enabled' not in data:
            return jsonify({'ok': False, 'error': 'enabled חסר'}), 400
        enabled = bool(data.get('enabled'))
        visibility = data.get('visibility')
        mgr = get_manager()
        result = mgr.set_share(user_id, collection_id, enabled=enabled, visibility=visibility)
        if result.get('ok'):
            try:
                uid = str(user_id)
                cache.delete_pattern(f"collections_detail:{uid}:-api-collections-{collection_id}*")
                cache.delete_pattern(f"collections_list:{uid}:*")
            except Exception:
                pass
            # צרף URL ציבורי אם מופעל
            try:
                col = result.get('collection') or {}
                share = col.get('share') or {}
                if bool(share.get('enabled')) and share.get('token'):
                    result['public_url'] = _build_public_collection_url(str(share.get('token')))
            except Exception:
                pass
        return jsonify(result)
    except Exception as e:
        rid = _get_request_id()
        try:
            emit_event("collections_share_error", severity="anomaly", operation="collections.share", handled=True, request_id=rid, collection_id=str(collection_id), error=str(e))
        except Exception:
            pass
        logger.error("Error updating share: %s", e)
        return jsonify({'ok': False, 'error': 'שגיאה בעדכון שיתוף'}), 500


@collections_bp.route('/shared/<token>', methods=['GET'])
@traced("collections.shared_get")
def get_shared_collection(token: str):
    """שליפת אוסף משותף לצפייה ציבורית ללא התחברות (JSON בלבד)."""
    try:
        mgr = get_manager()
        res = mgr.get_collection_by_share_token(token)
        if not res.get('ok'):
            return jsonify({'ok': False, 'error': 'לא נמצא'}), 404
        col = res.get('collection') or {}
        # שליפת פריטים עבור המשתמש של האוסף (כולל computed)
        owner_id = int(col.get('user_id')) if col.get('user_id') is not None else None
        cid = str(col.get('id')) if col.get('id') is not None else None
        if not owner_id or not cid:
            return jsonify({'ok': False, 'error': 'לא נמצא'}), 404
        items_res = mgr.get_collection_items(owner_id, cid, page=1, per_page=200, include_computed=True)
        if not items_res.get('ok'):
            items_res = {'items': []}
        return jsonify({'ok': True, 'collection': col, 'items': items_res.get('items') or []})
    except Exception as e:
        try:
            emit_event("collections_shared_get_error", severity="anomaly", operation="collections.shared_get", handled=True, token=str(token), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'שגיאה בשליפת שיתוף'}), 500


# ==================== Error Handlers ====================

@collections_bp.errorhandler(404)
def not_found(error):
    return jsonify({'ok': False, 'error': 'Endpoint not found'}), 404


@collections_bp.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return jsonify({'ok': False, 'error': 'Internal server error'}), 500

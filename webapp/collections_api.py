"""
Collections API Endpoints for WebApp (My Collections)

MVP: ידני בלבד + חוקים בסיסיים (compute_smart_items) ללא שיתוף/ייצוא.
מוגן ע"י require_auth, כולל dynamic_cache ואירועי observability.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, session, send_file
from functools import wraps
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from io import BytesIO
import zipfile
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


def _get_public_base_url() -> str:
    """הפקת בסיס כתובת ציבורית לפעולות שיתוף (UI ו-API)."""
    try:
        configured_base = getattr(_cfg, 'PUBLIC_BASE_URL', None) if _cfg is not None else None
        if configured_base:
            return str(configured_base).rstrip('/')

        host_base = str(getattr(request, 'host_url', '') or '').rstrip('/')
        script_root = str(getattr(request, 'script_root', '') or '').strip()
        if script_root:
            script_root = '/' + script_root.strip('/') if script_root not in ('/', '') else ''
        return f"{host_base}{script_root}".rstrip('/')
    except Exception:
        return ''


def _build_public_collection_url(token: str) -> str:
    try:
        base = _get_public_base_url()
        prefix = base or ''
        return f"{prefix}/collections/shared/{token}"
    except Exception:
        return f"/collections/shared/{token}"


def _build_public_collection_api_url(token: str) -> str:
    try:
        base = _get_public_base_url()
        prefix = base or ''
        return f"{prefix}/api/collections/shared/{token}"
    except Exception:
        return f"/api/collections/shared/{token}"


_BINARY_EXTENSIONS = {
    '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico',
    '.mp3', '.mp4', '.avi', '.mov', '.wav',
    '.zip', '.rar', '.7z', '.tar', '.gz', '.pyc', '.pyo', '.class', '.o', '.a',
}


def _format_size(size_bytes: Optional[float]) -> Optional[str]:
    if size_bytes is None:
        return None
    try:
        size = float(size_bytes)
    except Exception:
        return None
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _is_binary(content: str, filename: str = "") -> bool:
    try:
        ext = ""
        if filename:
            lower = filename.lower()
            idx = lower.rfind('.')
            if idx >= 0:
                ext = lower[idx:]
        if ext in _BINARY_EXTENSIONS:
            return True
    except Exception:
        pass
    if not content:
        return False
    try:
        content.encode('utf-8')
    except UnicodeEncodeError:
        return True
    if '\0' in content:
        return True
    return False


def _to_iso(value: Any) -> Any:
    if isinstance(value, datetime):
        try:
            return value.isoformat()
        except Exception:
            return None
    return value


def _sanitize_filename(value: str, fallback: str = "file.txt") -> str:
    try:
        name = str(value or "").strip()
    except Exception:
        name = ""
    if not name:
        name = fallback
    name = name.replace("\\", "/")
    if "/" in name:
        name = name.split("/")[-1]
    name = name.replace("..", "_")
    return name or fallback


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
        if result.get('ok'):
            collections = result.get('collections') or []
            for col in collections:
                try:
                    share = col.get('share') or {}
                    token = share.get('token')
                    if bool(share.get('enabled')) and token:
                        public_url = _build_public_collection_url(str(token))
                        public_api_url = _build_public_collection_api_url(str(token))
                        col['public_url'] = public_url
                        col['public_api_url'] = public_api_url
                    else:
                        col.pop('public_url', None)
                        col.pop('public_api_url', None)
                except Exception:
                    continue
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
        if result.get('ok'):
            col = result.get('collection') or {}
            share = col.get('share') or {}
            token = share.get('token')
            if bool(share.get('enabled')) and token:
                public_url = _build_public_collection_url(str(token))
                public_api_url = _build_public_collection_api_url(str(token))
                result['public_url'] = public_url
                result['public_api_url'] = public_api_url
                col['public_url'] = public_url
                col['public_api_url'] = public_api_url
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
    """הפעלת/ביטול שיתוף עבור אוסף. Body: {enabled: bool}"""
    try:
        user_id = int(session['user_id'])
        data = request.get_json(silent=True) or {}
        if 'enabled' not in data:
            return jsonify({'ok': False, 'error': 'enabled חסר'}), 400
        enabled = bool(data.get('enabled'))
        mgr = get_manager()
        result = mgr.set_share(user_id, collection_id, enabled=enabled)
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
                token = share.get('token')
                if bool(share.get('enabled')) and token:
                    public_url = _build_public_collection_url(str(token))
                    public_api_url = _build_public_collection_api_url(str(token))
                    result['public_url'] = public_url
                    result['public_api_url'] = public_api_url
                    col['public_url'] = public_url
                    col['public_api_url'] = public_api_url
                else:
                    result.pop('public_url', None)
                    result.pop('public_api_url', None)
                    if isinstance(col, dict):
                        col.pop('public_url', None)
                        col.pop('public_api_url', None)
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
        ctx = mgr.get_share_context(token)
        if not ctx.get('ok'):
            error_message = ctx.get('error', 'שגיאה בשליפת שיתוף')
            status = 404 if error_message == 'לא נמצא' else 500
            return jsonify({'ok': False, 'error': error_message}), status

        collection = ctx.get('collection') or {}
        items = ctx.get('items') or []
        doc_refs_by_key: Dict[Tuple[str, str], Dict[str, Any]] = ctx.get('doc_refs_by_key', {})  # type: ignore[assignment]
        api_base = _build_public_collection_api_url(str(token))

        for item in items:
            try:
                source = str((item.get('source') or 'regular')).lower()
                file_name = str(item.get('file_name') or '').strip()
                share_meta = doc_refs_by_key.get((source, file_name))
                if not share_meta:
                    continue
                file_id = share_meta.get('doc_id')
                if not file_id:
                    continue
                share_payload: Dict[str, Any] = {
                    'file_id': file_id,
                    'view_url': f"{api_base}/files/{file_id}",
                    'download_url': f"{api_base}/files/{file_id}/download",
                    'language': share_meta.get('language'),
                    'updated_at': _to_iso(share_meta.get('updated_at')),
                    'created_at': _to_iso(share_meta.get('created_at')),
                    'size_bytes': share_meta.get('file_size'),
                    'lines_count': share_meta.get('lines_count'),
                }
                size_label = _format_size(share_meta.get('file_size'))
                if size_label:
                    share_payload['size_label'] = size_label
                item['share'] = share_payload
            except Exception:
                continue

        export_url = f"{api_base}/export"
        total_items = ctx.get('items_result', {}).get('total_items')
        response_body: Dict[str, Any] = {
            'ok': True,
            'collection': collection,
            'items': items,
            'export_url': export_url,
        }
        if total_items is not None:
            response_body['items_total'] = total_items
        return jsonify(response_body)
    except Exception as e:
        try:
            emit_event("collections_shared_get_error", severity="anomaly", operation="collections.shared_get", handled=True, token=str(token), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'שגיאה בשליפת שיתוף'}), 500


@collections_bp.route('/shared/<token>/files/<file_id>', methods=['GET'])
@traced("collections.shared_file")
def get_shared_file(token: str, file_id: str):
    try:
        mgr = get_manager()
        details = mgr.get_shared_file_details(token, file_id)
        if not details.get('ok'):
            error_message = details.get('error', 'שגיאה בשליפת קובץ')
            status = 404 if error_message == 'לא נמצא' else 500
            return jsonify({'ok': False, 'error': error_message}), status
        file_payload = details.get('file') or {}
        ctx = details.get('context') or {}
        collection = details.get('collection') or {}
        content = str(file_payload.get('content') or '')
        file_name = str(file_payload.get('file_name') or '')
        is_binary = _is_binary(content, file_name)
        preview_payload: Dict[str, Any] = {
            'id': file_payload.get('id'),
            'file_name': file_name,
            'language': file_payload.get('language'),
            'description': file_payload.get('description') or '',
            'tags': file_payload.get('tags') or [],
            'size_bytes': file_payload.get('size_bytes'),
            'size_label': _format_size(file_payload.get('size_bytes')),
            'lines_count': file_payload.get('lines_count'),
            'created_at': _to_iso(file_payload.get('created_at')),
            'updated_at': _to_iso(file_payload.get('updated_at')),
            'source': file_payload.get('source'),
            'is_binary': bool(is_binary),
            'download_url': f"{_build_public_collection_api_url(str(token))}/files/{file_payload.get('id')}/download",
        }
        if not is_binary:
            preview_payload['content'] = content
        mgr.log_share_activity(
            token,
            collection_id=ctx.get('collection_id'),
            file_id=file_payload.get('id'),
            event='view',
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        return jsonify({'ok': True, 'collection': collection, 'file': preview_payload})
    except Exception as e:
        try:
            emit_event("collections_shared_file_error", severity="anomaly", operation="collections.shared_file", handled=True, token=str(token), file_id=str(file_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'שגיאה בשליפת קובץ'}), 500


@collections_bp.route('/shared/<token>/files/<file_id>/download', methods=['GET'])
@traced("collections.shared_file_download")
def download_shared_file(token: str, file_id: str):
    try:
        mgr = get_manager()
        details = mgr.get_shared_file_details(token, file_id)
        if not details.get('ok'):
            error_message = details.get('error', 'שגיאה בשליפת קובץ')
            status = 404 if error_message == 'לא נמצא' else 500
            return jsonify({'ok': False, 'error': error_message}), status
        file_payload = details.get('file') or {}
        ctx = details.get('context') or {}
        content = str(file_payload.get('content') or '')
        file_name = _sanitize_filename(file_payload.get('file_name') or '', fallback='shared.txt')
        buffer = BytesIO()
        buffer.write(content.encode('utf-8'))
        buffer.seek(0)
        response = send_file(buffer, mimetype='text/plain; charset=utf-8', as_attachment=True, download_name=file_name)
        response.headers['Cache-Control'] = 'no-store'
        mgr.log_share_activity(
            token,
            collection_id=ctx.get('collection_id'),
            file_id=file_payload.get('id'),
            event='download',
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        return response
    except Exception as e:
        try:
            emit_event("collections_shared_file_download_error", severity="anomaly", operation="collections.shared_file_download", handled=True, token=str(token), file_id=str(file_id), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'שגיאה בהורדת קובץ'}), 500


@collections_bp.route('/shared/<token>/export', methods=['GET'])
@traced("collections.shared_export")
def export_shared_collection(token: str):
    try:
        mgr = get_manager()
        docs_res = mgr.collect_shared_documents(token)
        if not docs_res.get('ok'):
            error_message = docs_res.get('error', 'שגיאה ביצוא קבצים')
            status = 404 if error_message == 'לא נמצא' else 500
            return jsonify({'ok': False, 'error': error_message}), status
        documents = docs_res.get('documents') or []
        if not documents:
            return jsonify({'ok': False, 'error': 'אין קבצים זמינים לשיתוף'}), 404
        buffer = BytesIO()
        name_counters: Dict[str, int] = {}
        used_names: set[str] = set()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for doc in documents:
                base_name = _sanitize_filename(doc.get('file_name') or '', fallback='file.txt')
                counter = name_counters.get(base_name, 0)
                name_candidate = base_name
                while name_candidate in used_names:
                    counter += 1
                    if '.' in base_name:
                        stem, ext = base_name.rsplit('.', 1)
                        name_candidate = f"{stem}_{counter}.{ext}"
                    else:
                        name_candidate = f"{base_name}_{counter}"
                name_counters[base_name] = counter
                used_names.add(name_candidate)
                content = doc.get('content')
                if not isinstance(content, str):
                    content = str(content or '')
                zf.writestr(name_candidate, content)
        buffer.seek(0)
        collection = docs_res.get('collection') or {}
        ctx = docs_res.get('context') or {}
        slug = collection.get('slug') or collection.get('name') or 'collection'
        zip_name = _sanitize_filename(str(slug), fallback='collection') + '_shared.zip'
        response = send_file(buffer, mimetype='application/zip', as_attachment=True, download_name=zip_name)
        response.headers['Cache-Control'] = 'no-store'
        mgr.log_share_activity(
            token,
            collection_id=ctx.get('collection_id'),
            event='export',
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )
        return response
    except Exception as e:
        try:
            emit_event("collections_shared_export_error", severity="anomaly", operation="collections.shared_export", handled=True, token=str(token), error=str(e))
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'שגיאה בהפקת קובץ ZIP'}), 500


# ==================== Error Handlers ====================

@collections_bp.errorhandler(404)
def not_found(error):
    return jsonify({'ok': False, 'error': 'Endpoint not found'}), 404


@collections_bp.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return jsonify({'ok': False, 'error': 'Internal server error'}), 500

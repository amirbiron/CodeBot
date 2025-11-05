from __future__ import annotations

from flask import Blueprint, jsonify, request, Response
import os
from http_sync import request as http_request
from typing import Any, Dict, List, Optional, Tuple
import logging

from cache_manager import dynamic_cache
from services.community_library_service import list_public

logger = logging.getLogger(__name__)

community_lib_bp = Blueprint('community_library', __name__, url_prefix='/api/community-library')


def _parse_int(val: Optional[str], default: int, lo: int, hi: int) -> int:
    try:
        v = int(val) if val not in (None, "") else default
        return max(lo, min(hi, v))
    except Exception:
        return default


@community_lib_bp.route('', methods=['GET'])
@dynamic_cache(content_type='community_library', key_prefix='community_lib')
def get_public_items():
    try:
        q = request.args.get('q')
        page = _parse_int(request.args.get('page'), 1, 1, 10000)
        per_page = _parse_int(request.args.get('per_page'), 30, 1, 60)
        tags_raw = request.args.get('tags') or ''
        tags: List[str] = []
        if tags_raw:
            for t in tags_raw.split(','):
                ts = (t or '').strip()
                if ts:
                    tags.append(ts)
        items, total = list_public(q=q, page=page, per_page=per_page, tags=tags or None)
        return jsonify({
            'ok': True,
            'items': items,
            'page': page,
            'per_page': per_page,
            'total': total,
        })
    except Exception as e:
        try:
            logger.error("community_library_api_error: %s", e, exc_info=True)
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@community_lib_bp.route('/logo/<path:file_id>', methods=['GET'])
def get_logo(file_id: str):
    """Proxy a Telegram file by file_id without exposing the bot token.

    Caches are handled by clients via Cache-Control; upstream requests use short timeouts.
    """
    try:
        token = os.getenv('BOT_TOKEN', '')
        if not token or not file_id:
            return Response(status=404)
        # Resolve file_path from file_id
        meta_resp = http_request(
            'GET',
            f'https://api.telegram.org/bot{token}/getFile',
            params={'file_id': file_id},
            timeout=5,
        )
        if int(getattr(meta_resp, 'status_code', 0) or 0) != 200:
            return Response(status=404)
        try:
            body = meta_resp.json() if getattr(meta_resp, 'content', None) is not None else {}
            file_path = ((body or {}).get('result') or {}).get('file_path')
        except Exception:
            file_path = None
        if not file_path:
            return Response(status=404)
        # Fetch the actual file bytes
        file_resp = http_request(
            'GET',
            f'https://api.telegram.org/file/bot{token}/{file_path}',
            timeout=8,
        )
        if int(getattr(file_resp, 'status_code', 0) or 0) != 200:
            return Response(status=404)
        content_type = None
        try:
            content_type = (file_resp.headers or {}).get('Content-Type')
        except Exception:
            content_type = None
        headers = {'Cache-Control': 'public, max-age=86400'}
        if content_type:
            headers['Content-Type'] = content_type
        return Response(file_resp.content, headers=headers)
    except Exception:
        return Response(status=404)

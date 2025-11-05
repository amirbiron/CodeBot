from __future__ import annotations

from flask import Blueprint, jsonify, request
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

from __future__ import annotations

from flask import Blueprint, jsonify, request
from typing import List
import logging

from cache_manager import dynamic_cache
from services.snippet_library_service import list_public_snippets

logger = logging.getLogger(__name__)

snippets_bp = Blueprint('snippets_api', __name__, url_prefix='/api/snippets')


def _parse_int(val: str | None, default: int, lo: int, hi: int) -> int:
    try:
        v = int(val) if val not in (None, "") else default
        return max(lo, min(hi, v))
    except Exception:
        return default


@snippets_bp.route('', methods=['GET'])
@dynamic_cache(content_type='snippets_library', key_prefix='snippets')
def get_public_snippets():
    try:
        q = request.args.get('q') or request.args.get('title')
        language = request.args.get('language') or request.args.get('lang')
        page = _parse_int(request.args.get('page'), 1, 1, 10000)
        per_page = _parse_int(request.args.get('per_page'), 30, 1, 60)
        items, total = list_public_snippets(q=q, language=language, page=page, per_page=per_page)
        return jsonify({
            'ok': True,
            'items': items,
            'page': page,
            'per_page': per_page,
            'total': total,
        })
    except Exception as e:
        try:
            logger.error("snippets_library_api_error: %s", e, exc_info=True)
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'internal_error'}), 500

"""
API endpoints לחיפוש (כולל סמנטי).
Search API Blueprint.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, session

from config import config

logger = logging.getLogger(__name__)

search_bp = Blueprint("search_api", __name__, url_prefix="/api/search")


def _parse_int(val: Optional[str], default: int, lo: int, hi: int) -> int:
    """Parse integer with bounds."""
    try:
        v = int(val) if val not in (None, "") else default
        return max(lo, min(hi, v))
    except Exception:
        return default


@search_bp.route("", methods=["GET"])
def search_files():
    """
    חיפוש קבצים.

    Query params:
        q: שאילתת החיפוש
        type: סוג החיפוש (text, fuzzy, regex, semantic, function, content) - ברירת מחדל: text
        language: סינון לפי שפת תכנות
        limit: מספר תוצאות מקסימלי (ברירת מחדל: 20)

    Returns:
        JSON עם תוצאות החיפוש
    """
    try:
        user_id = int(session.get("user_id") or 0)
    except Exception:
        user_id = 0

    if user_id <= 0:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # פרמטרים
    query = request.args.get("q", "").strip()
    search_type = request.args.get("type", "text").lower()
    language = request.args.get("language")
    limit = _parse_int(request.args.get("limit"), 20, 1, 100)

    if not query:
        return jsonify({"ok": True, "items": [], "total": 0})

    try:
        from search_engine import search_engine, SearchType, SearchFilter

        # מיפוי סוג חיפוש
        type_map = {
            "text": SearchType.TEXT,
            "fuzzy": SearchType.FUZZY,
            "regex": SearchType.REGEX,
            "semantic": SearchType.SEMANTIC,
            "function": SearchType.FUNCTION,
            "content": SearchType.CONTENT,
        }

        st = type_map.get(search_type, SearchType.TEXT)

        # בדיקה שסמנטי מופעל
        if st == SearchType.SEMANTIC and not getattr(config, "SEMANTIC_SEARCH_ENABLED", False):
            # Fallback לחיפוש רגיל
            st = SearchType.FUZZY

        # הכנת פילטרים
        filters = None
        if language:
            filters = SearchFilter(languages=[language])

        # ביצוע החיפוש
        results = search_engine.search(
            user_id=user_id,
            query=query,
            search_type=st,
            filters=filters,
            limit=limit,
        )

        # המרה ל-JSON-serializable
        items = []
        for r in results:
            items.append(
                {
                    "file_name": r.file_name,
                    "programming_language": r.programming_language,
                    "tags": r.tags,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    "score": round(r.relevance_score, 4),
                    "snippet_preview": (r.snippet_preview or "")[:200] if r.snippet_preview else None,
                    "is_semantic": st == SearchType.SEMANTIC,
                }
            )

        return jsonify(
            {
                "ok": True,
                "items": items,
                "total": len(items),
                "search_type": search_type,
                "semantic_enabled": getattr(config, "SEMANTIC_SEARCH_ENABLED", False),
            }
        )

    except Exception as e:
        logger.error(f"Search API error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": "search_failed"}), 500


@search_bp.route("/suggest", methods=["GET"])
def search_suggestions():
    """הצעות להשלמת חיפוש."""
    try:
        user_id = int(session.get("user_id") or 0)
    except Exception:
        user_id = 0

    if user_id <= 0:
        return jsonify({"ok": False, "suggestions": []})

    partial = request.args.get("q", "").strip()
    limit = _parse_int(request.args.get("limit"), 10, 1, 20)

    if len(partial) < 2:
        return jsonify({"ok": True, "suggestions": []})

    try:
        from search_engine import search_engine

        suggestions = search_engine.suggest_completions(user_id, partial, limit)
        return jsonify({"ok": True, "suggestions": suggestions})
    except Exception as e:
        logger.error(f"Suggestions error: {e}")
        return jsonify({"ok": True, "suggestions": []})


@search_bp.route("/status", methods=["GET"])
def search_status():
    """סטטוס מערכת החיפוש הסמנטי."""
    try:
        user_id = int(session.get("user_id") or 0)
    except Exception:
        user_id = 0

    if user_id <= 0:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    from database import db

    # ספירת קבצים עם/בלי embedding
    try:
        total = db.manager.collection.count_documents(
            {
                "user_id": user_id,
                "is_active": {"$ne": False},
            }
        )
        indexed = db.manager.collection.count_documents(
            {
                "user_id": user_id,
                "is_active": {"$ne": False},
                "embedding": {"$exists": True, "$ne": None},
            }
        )
    except Exception:
        total, indexed = 0, 0

    return jsonify(
        {
            "ok": True,
            "semantic_enabled": getattr(config, "SEMANTIC_SEARCH_ENABLED", False),
            "total_files": total,
            "indexed_files": indexed,
            "indexing_progress": round(indexed / total * 100, 1) if total > 0 else 0,
        }
    )


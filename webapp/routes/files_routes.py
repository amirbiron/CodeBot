"""
Files API Routes - Pilot for layered architecture refactoring.

This module implements the first API endpoint migrated to the new architecture:
Route -> Facade/Container -> Service/Domain -> Repository -> DB

Issue: #2871 (Step 2 - Pilot)
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Blueprint, jsonify, request, session

logger = logging.getLogger(__name__)

files_bp = Blueprint("files_api", __name__, url_prefix="/api")

def _get_files_facade():
    """
    Lazy import of FilesFacade to avoid circular imports at module load time.

    Returns the singleton FilesFacade instance from the webapp container.
    """
    from src.infrastructure.composition.webapp_container import get_files_facade

    return get_files_facade()


@files_bp.route("/files", methods=["GET"])
def api_get_files():
    """
    Authentication is enforced by the shared `login_required` decorator from `webapp.app`.

    We import it lazily inside the request handler to avoid circular imports during app startup:
    `webapp.app` registers this Blueprint (imports this module) after defining `login_required`.
    """
    from webapp.app import login_required  # late import to avoid circular imports

    return login_required(_api_get_files_impl)()


def _api_get_files_impl():
    """
    GET /api/files - Paginated list of user's regular files.

    Query Parameters:
        page (int): Page number (default: 1)
        per_page (int): Items per page (default: 20, max: 100)

    Returns:
        JSON: {
            "ok": true,
            "files": [...],
            "total": int,
            "page": int,
            "per_page": int,
            "total_pages": int
        }
    """
    try:
        user_id = session["user_id"]

        # Parse pagination parameters with defaults and limits
        try:
            requested_page = max(1, int(request.args.get("page", 1)))
        except (ValueError, TypeError):
            requested_page = 1

        try:
            per_page = min(100, max(1, int(request.args.get("per_page", 20))))
        except (ValueError, TypeError):
            per_page = 20

        # Use FilesFacade instead of direct DB access
        facade = _get_files_facade()

        # We may need at most one re-fetch if the requested page is out-of-bounds.
        # Keep pagination metadata consistent by deriving it from the final fetch.
        page = requested_page
        files, total = facade.get_regular_files_paginated(user_id=user_id, page=page, per_page=per_page)
        total_pages = (total + per_page - 1) // per_page if total > 0 else 1
        clamped_page = min(max(1, page), total_pages)
        if clamped_page != page:
            page = clamped_page
            files, total = facade.get_regular_files_paginated(user_id=user_id, page=page, per_page=per_page)
            total_pages = (total + per_page - 1) // per_page if total > 0 else 1
            # In case the dataset changed between the two calls, re-clamp the page for consistency.
            page = min(max(1, page), total_pages)

        # Serialize files for JSON response (convert ObjectId to string)
        serialized_files = []
        for f in files:
            file_dict = _serialize_file(f)
            serialized_files.append(file_dict)

        return jsonify({
            "ok": True,
            "files": serialized_files,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        })

    except Exception:
        logger.exception("Error in api_get_files")
        return jsonify({
            "ok": False,
            "error": "Failed to fetch files",
        }), 500


def _serialize_file(file_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Serialize a file document for JSON response.

    Converts ObjectId to string and handles None values.
    """
    import datetime as _dt

    def _json_safe(v: Any) -> Any:
        # Handle common non-JSON types
        try:
            if isinstance(v, (_dt.datetime, _dt.date)):
                return v.isoformat()
        except Exception:
            pass
        # ObjectId (avoid importing bson in environments without it)
        try:
            if type(v).__name__ == "ObjectId":
                return str(v)
        except Exception:
            pass
        # Recursive structures
        if isinstance(v, dict):
            return {str(k): _json_safe(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [_json_safe(x) for x in v]
        return v

    result = {}

    for key, value in file_doc.items():
        if key == "_id":
            result["id"] = str(value)
        else:
            result[key] = _json_safe(value)

    return result

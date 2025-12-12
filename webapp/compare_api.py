"""
Compare API Endpoints
---------------------

אנדפוינטי JSON להשוואת קבצים וגרסאות.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, session
from werkzeug.exceptions import BadRequest

try:
    from bson import ObjectId
except Exception:  # pragma: no cover
    class ObjectId(str):  # type: ignore
        pass

from services.diff_service import DiffMode

compare_bp = Blueprint("compare", __name__, url_prefix="/api/compare")
logger = logging.getLogger(__name__)


# -------- Helpers -------- #
def _get_db():
    from webapp.app import get_db as _get_db  # noqa: WPS433

    return _get_db()


def _get_diff_service():
    from services.diff_service import DiffService  # noqa: WPS433

    return DiffService(_get_db())


def _require_auth() -> Optional[int]:
    user_id = session.get("user_id")
    if user_id is None:
        return None
    try:
        return int(user_id)
    except Exception:  # pragma: no cover
        return None


def _load_file(db_ref, user_id: int, file_id: str) -> Optional[Dict[str, Any]]:
    if not file_id:
        return None
    try:
        obj_id = ObjectId(file_id)
    except Exception:
        return None
    try:
        return db_ref.code_snippets.find_one({"_id": obj_id, "user_id": user_id})
    except Exception:
        return None


def _parse_positive_int(value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if value in (None, "", "null"):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise BadRequest("invalid_number")
    if parsed <= 0:
        raise BadRequest("invalid_number")
    return parsed


# -------- Routes -------- #
@compare_bp.route("/versions/<file_id>", methods=["GET"])
def compare_versions(file_id: str):
    user_id = _require_auth()
    if user_id is None:
        return jsonify({"error": "unauthorized"}), 401

    db_ref = _get_db()
    file_doc = _load_file(db_ref, user_id, file_id)
    if not file_doc:
        return jsonify({"error": "file_not_found"}), 404

    file_name = (file_doc.get("file_name") or "").strip()
    if not file_name:
        return jsonify({"error": "file_not_found"}), 404

    current_version = int(file_doc.get("version") or 1)
    try:
        version_right = _parse_positive_int(request.args.get("right"), current_version) or current_version
        version_left = _parse_positive_int(
            request.args.get("left"),
            max(1, version_right - 1),
        ) or 1
    except BadRequest as err:
        return jsonify({"error": str(err)}), 400

    diff_service = _get_diff_service()
    result = diff_service.compare_versions(
        user_id,
        file_name,
        version_left,
        version_right,
        file_id=str(file_doc.get("_id")),
    )
    if not result:
        return jsonify({"error": "diff_unavailable"}), 400

    payload = result.to_dict()
    payload["mode"] = DiffMode.SIDE_BY_SIDE.value
    return jsonify(payload)


@compare_bp.route("/files", methods=["POST"])
def compare_files():
    user_id = _require_auth()
    if user_id is None:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    left_id = (data.get("left_file_id") or "").strip()
    right_id = (data.get("right_file_id") or "").strip()

    if not left_id or not right_id:
        return jsonify({"error": "missing_file_ids"}), 400
    if left_id == right_id:
        return jsonify({"error": "identical_files"}), 400

    diff_service = _get_diff_service()
    result = diff_service.compare_files(user_id, left_id, right_id)
    if not result:
        return jsonify({"error": "diff_unavailable"}), 400

    payload = result.to_dict()
    payload["mode"] = DiffMode.SIDE_BY_SIDE.value
    return jsonify(payload)


@compare_bp.route("/diff", methods=["POST"])
def compare_raw():
    user_id = _require_auth()
    if user_id is None:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    left_content = data.get("left_content") or ""
    right_content = data.get("right_content") or ""

    diff_service = _get_diff_service()
    result = diff_service.compute_diff(left_content, right_content)
    payload = result.to_dict()
    payload["mode"] = DiffMode.UNIFIED.value
    return jsonify(payload)


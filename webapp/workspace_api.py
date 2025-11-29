"""
Workspace-specific API endpoints (Kanban board state management).
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from webapp.collections_api import get_manager, require_auth, _get_request_id

try:  # Observability (fail-open)
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None


workspace_bp = Blueprint("workspace_api", __name__)
bp = workspace_bp  # optional alias for app registration expectations


@workspace_bp.route("/items/<item_id>/state", methods=["PATCH"])
@require_auth
def update_workspace_item_state(item_id: str):
    """Update a single workspace item state (todo/in_progress/done)."""
    try:
        user_id = int(session["user_id"])
    except Exception:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    state = payload.get("state")
    if not isinstance(state, str) or not state.strip():
        return jsonify({"ok": False, "error": "state_required"}), 400

    mgr = get_manager()
    result = mgr.update_workspace_item_state(user_id, item_id, state)
    if result.get("ok"):
        emit_event(
            "workspace_state_update_api",
            user_id=user_id,
            item_id=str(item_id),
            state=result.get("state"),
        )
        return jsonify(result)

    error_code = str(result.get("error") or "workspace_state_update_failed")
    rid = _get_request_id()
    emit_event(
        "workspace_state_update_api_error",
        severity="warning",
        handled=True,
        user_id=user_id,
        item_id=str(item_id),
        error=error_code,
        request_id=rid,
    )
    if error_code in {"invalid_workspace_state", "invalid_item_id", "state_required"}:
        status = 400
    elif error_code in {"workspace_item_not_found", "workspace_collection_missing"}:
        status = 404
    elif error_code == "invalid_user":
        status = 401
    else:
        status = 500
    return jsonify({"ok": False, "error": error_code}), status

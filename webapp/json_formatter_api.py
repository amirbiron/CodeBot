"""
JSON Formatter API Blueprint
============================
נקודות קצה ל-API של כלי עיצוב JSON.
"""

from __future__ import annotations

import json

from flask import Blueprint, jsonify, request, session

from services.json_formatter_service import get_json_formatter_service

json_formatter_bp = Blueprint("json_formatter", __name__, url_prefix="/api/json")


@json_formatter_bp.before_request
def _require_login_for_json_formatter():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "נדרש להתחבר"}), 401
    return None


@json_formatter_bp.route("/format", methods=["POST"])
def format_json():
    """
    עיצוב JSON עם הזחה.

    Request Body:
        {
            "content": "<json string>",
            "indent": 2,           // אופציונלי
            "sort_keys": false     // אופציונלי
        }

    Response:
        {
            "success": true,
            "result": "<formatted json>",
            "stats": { ... }
        }
    """
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"success": False, "error": "Missing content"}), 400

    service = get_json_formatter_service()

    try:
        indent = data.get("indent", 2)
        if isinstance(indent, str) and indent.strip().isdigit():
            indent = int(indent.strip())
        if indent is not None and not isinstance(indent, (int, str)):
            return jsonify({"success": False, "error": "Invalid indent: must be int or string"}), 400
        if isinstance(indent, int):
            # שמירה על גבולות סבירים כדי למנוע שימוש חריג
            indent = max(0, min(8, indent))

        result = service.format_json(
            data["content"],
            indent=indent,
            sort_keys=data.get("sort_keys", False),
        )
        stats = service.get_json_stats(data["content"])
        return jsonify(
            {
                "success": True,
                "result": result,
                "stats": {
                    "total_keys": stats.total_keys,
                    "max_depth": stats.max_depth,
                    "total_values": stats.total_values,
                },
            }
        )
    except json.JSONDecodeError as e:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Invalid JSON: {e.msg}",
                    "line": e.lineno,
                    "column": e.colno,
                }
            ),
            400,
        )
    except TypeError as e:
        return jsonify({"success": False, "error": f"Invalid request: {str(e)}"}), 400


@json_formatter_bp.route("/minify", methods=["POST"])
def minify_json():
    """
    דחיסת JSON לשורה אחת.

    Request Body:
        { "content": "<json string>" }

    Response:
        {
            "success": true,
            "result": "<minified json>",
            "original_size": 1234,
            "minified_size": 567,
            "savings_percent": 54.0
        }
    """
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"success": False, "error": "Missing content"}), 400

    service = get_json_formatter_service()

    try:
        result = service.minify_json(data["content"])
        original_size = len(data["content"].encode("utf-8"))
        minified_size = len(result.encode("utf-8"))
        savings = ((original_size - minified_size) / original_size * 100) if original_size > 0 else 0

        return jsonify(
            {
                "success": True,
                "result": result,
                "original_size": original_size,
                "minified_size": minified_size,
                "savings_percent": round(savings, 1),
            }
        )
    except json.JSONDecodeError as e:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Invalid JSON: {e.msg}",
                    "line": e.lineno,
                    "column": e.colno,
                }
            ),
            400,
        )


@json_formatter_bp.route("/validate", methods=["POST"])
def validate_json():
    """
    אימות תקינות JSON.

    Request Body:
        { "content": "<json string>" }

    Response (valid):
        {
            "success": true,
            "is_valid": true,
            "stats": { ... }
        }

    Response (invalid):
        {
            "success": true,
            "is_valid": false,
            "error": "Expecting property name",
            "line": 5,
            "column": 12
        }
    """
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"success": False, "error": "Missing content"}), 400

    service = get_json_formatter_service()
    result = service.validate_json(data["content"])

    response = {"success": True, "is_valid": result.is_valid}

    if result.is_valid:
        stats = service.get_json_stats(data["content"])
        response["stats"] = {
            "total_keys": stats.total_keys,
            "max_depth": stats.max_depth,
            "string_count": stats.string_count,
            "number_count": stats.number_count,
            "boolean_count": stats.boolean_count,
            "null_count": stats.null_count,
            "array_count": stats.array_count,
            "object_count": stats.object_count,
        }
    else:
        response["error"] = result.error_message
        response["line"] = result.error_line
        response["column"] = result.error_column

    return jsonify(response)


@json_formatter_bp.route("/fix", methods=["POST"])
def fix_json():
    """
    ניסיון לתקן שגיאות נפוצות ב-JSON.

    Request Body:
        { "content": "<json string with errors>" }

    Response:
        {
            "success": true,
            "result": "<fixed json>",
            "fixes_applied": ["removed trailing commas", "..."]
        }
    """
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"success": False, "error": "Missing content"}), 400

    service = get_json_formatter_service()

    try:
        fixed, fixes = service.fix_common_errors(data["content"])
        # נסה לאמת את התוצאה
        json.loads(fixed)
        return jsonify({"success": True, "result": fixed, "fixes_applied": fixes})
    except json.JSONDecodeError as e:
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"Could not fix JSON: {e.msg}",
                    "fixes_attempted": fixes if "fixes" in locals() else [],
                }
            ),
            400,
        )


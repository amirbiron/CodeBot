"""
Code Tools API Blueprint
========================
נקודות קצה לעיצוב קוד, linting ותיקון אוטומטי.
"""

import os

from flask import Blueprint, request, jsonify, session
from services.code_formatter_service import get_code_formatter_service

code_tools_bp = Blueprint("code_tools", __name__, url_prefix="/api/code")

def _is_admin(user_id: int) -> bool:
    admin_ids_env = os.getenv("ADMIN_USER_IDS", "")
    admin_ids_list = admin_ids_env.split(",") if admin_ids_env else []
    admin_ids = [int(x.strip()) for x in admin_ids_list if x.strip().isdigit()]
    return user_id in admin_ids


@code_tools_bp.before_request
def _require_admin_for_code_tools():
    """
    Code Tools הם פיצ'ר Admin-only.
    חשוב לא להסתמך רק על הסתרה ב-UI.
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"success": False, "error": "נדרש להתחבר"}), 401
    try:
        uid_int = int(user_id)
    except Exception:
        return jsonify({"success": False, "error": "משתמש לא תקין"}), 401
    if not _is_admin(uid_int):
        return jsonify({"success": False, "error": "Admin בלבד"}), 403


@code_tools_bp.route("/format", methods=["POST"])
def format_code():
    """
    עיצוב קוד.

    Request Body:
        {
            "code": "<source code>",
            "language": "python",        // אופציונלי
            "tool": "black",             // black | isort | autopep8
            "options": {                 // אופציונלי
                "line_length": 88
            }
        }

    Response:
        {
            "success": true,
            "formatted_code": "...",
            "diff": "...",
            "lines_changed": 5,
            "has_changes": true,
            "tool_used": "black"
        }
    """
    data = request.get_json()
    if not data or "code" not in data:
        return jsonify({"success": False, "error": "חסר קוד"}), 400

    service = get_code_formatter_service()

    result = service.format_code(
        code=data["code"],
        language=data.get("language", "python"),
        tool=data.get("tool", "black"),
        options=data.get("options", {}),
    )

    return jsonify(
        {
            "success": result.success,
            "formatted_code": result.formatted_code,
            "diff": result.get_diff() if result.success else None,
            "lines_changed": result.lines_changed,
            "has_changes": result.has_changes(),
            "tool_used": result.tool_used,
            "error": result.error_message,
        }
    )


@code_tools_bp.route("/lint", methods=["POST"])
def lint_code():
    """
    בדיקת איכות קוד.

    Request Body:
        {
            "code": "<source code>",
            "language": "python",
            "filename": "example.py"     // אופציונלי
        }

    Response:
        {
            "success": true,
            "score": 8.5,
            "issues": [
                {
                    "line": 10,
                    "column": 5,
                    "code": "E501",
                    "message": "line too long",
                    "severity": "warning",
                    "fixable": true
                }
            ],
            "has_errors": false,
            "fixable_count": 3
        }
    """
    data = request.get_json()
    if not data or "code" not in data:
        return jsonify({"success": False, "error": "חסר קוד"}), 400

    service = get_code_formatter_service()

    result = service.lint_code(
        code=data["code"],
        language=data.get("language", "python"),
        filename=data.get("filename", "code.py"),
    )

    issues = [
        {
            "line": i.line,
            "column": i.column,
            "code": i.code,
            "message": i.message,
            "severity": i.severity,
            "fixable": i.fixable,
        }
        for i in result.issues
    ]

    return jsonify(
        {
            "success": result.success,
            "score": result.score,
            "issues": issues,
            "has_errors": result.has_errors,
            "fixable_count": result.fixable_count,
            "error": result.error_message,
        }
    )


@code_tools_bp.route("/fix", methods=["POST"])
def auto_fix_code():
    """
    תיקון אוטומטי של בעיות.

    Request Body:
        {
            "code": "<source code>",
            "level": "safe",             // safe | cautious | aggressive
            "language": "python"
        }

    Response:
        {
            "success": true,
            "fixed_code": "...",
            "diff": "...",
            "fixes_applied": ["autopep8", "isort"],
            "issues_remaining": [...],
            "level": "safe"
        }
    """
    data = request.get_json()
    if not data or "code" not in data:
        return jsonify({"success": False, "error": "חסר קוד"}), 400

    service = get_code_formatter_service()

    result = service.auto_fix(
        code=data["code"],
        level=data.get("level", "safe"),
        language=data.get("language", "python"),
    )

    diff = service.get_diff(result.original_code, result.fixed_code) if result.success else None

    issues_remaining = [
        {
            "line": i.line,
            "column": i.column,
            "code": i.code,
            "message": i.message,
            "severity": i.severity,
        }
        for i in result.issues_remaining
    ]

    return jsonify(
        {
            "success": result.success,
            "fixed_code": result.fixed_code,
            "diff": diff,
            "fixes_applied": result.fixes_applied,
            "issues_remaining": issues_remaining,
            "level": result.level,
            "error": result.error_message,
        }
    )


@code_tools_bp.route("/tools", methods=["GET"])
def get_available_tools():
    """
    קבלת רשימת כלים זמינים.

    Response:
        {
            "tools": {
                "black": true,
                "isort": true,
                "flake8": true,
                "autopep8": false
            }
        }
    """
    service = get_code_formatter_service()
    return jsonify({"tools": service.get_available_tools()})


@code_tools_bp.route("/diff", methods=["POST"])
def get_diff():
    """
    השוואת שני קטעי קוד.

    Request Body:
        {
            "original": "<original code>",
            "modified": "<modified code>"
        }

    Response:
        {
            "diff": "...",
            "lines_changed": 5
        }
    """
    data = request.get_json()
    if not data or "original" not in data or "modified" not in data:
        return jsonify({"success": False, "error": "חסר קוד מקור או יעד"}), 400

    service = get_code_formatter_service()

    diff = service.get_diff(data["original"], data["modified"])
    lines_changed = service._count_changes(data["original"], data["modified"])

    return jsonify(
        {
            "success": True,
            "diff": diff,
            "lines_changed": lines_changed,
        }
    )


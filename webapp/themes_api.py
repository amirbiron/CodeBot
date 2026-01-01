"""
Themes API (Presets / Import / Export)
מימוש לפי GUIDES/custom_themes_guide.md
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Optional

from flask import Blueprint, Response, jsonify, request, session

from services.theme_parser_service import (
    export_theme_to_json,
    generate_codemirror_css_from_tokens,
    parse_native_theme,
    parse_vscode_theme,
    validate_and_sanitize_theme_variables,
    validate_theme_json,
)
from services.theme_presets_service import apply_preset_to_user, get_preset_by_id, list_presets

logger = logging.getLogger(__name__)

themes_bp = Blueprint("themes", __name__, url_prefix="/api/themes")

MAX_THEME_FILE_SIZE = 512 * 1024  # 512KB
MAX_THEMES_PER_USER = 10


def get_db():
    from webapp.app import get_db as _get_db  # local import to avoid circular deps
    return _get_db()


def get_current_user_id() -> Optional[int]:
    try:
        uid = session.get("user_id")
        if uid is None:
            return None
        return int(uid)
    except Exception:
        return None


def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "error": "נדרש להתחבר"}), 401
        return f(*args, **kwargs)

    return decorated_function


def _count_user_themes(db, user_id: int) -> int:
    try:
        user_doc = db.users.find_one({"user_id": int(user_id)}, {"custom_themes": 1}) or {}
        themes = user_doc.get("custom_themes") if isinstance(user_doc, dict) else None
        if isinstance(themes, list):
            return len(themes)
        return 0
    except Exception:
        return 0


@themes_bp.route("/presets", methods=["GET"])
@require_auth
def presets_list():
    category = (request.args.get("category") or "").strip().lower() or None
    presets = list_presets(category=category)
    return jsonify({"success": True, "presets": presets})


@themes_bp.route("/presets/<preset_id>", methods=["GET"])
@require_auth
def preset_details(preset_id: str):
    preset = get_preset_by_id(preset_id)
    if not preset:
        return jsonify({"success": False, "error": "ערכה לא נמצאה"}), 404

    # מחזירים את כל המשתנים עבור Preview
    return jsonify(
        {
            "id": preset.get("id"),
            "name": preset.get("name"),
            "description": preset.get("description", ""),
            "category": preset.get("category", "dark"),
            "preview_colors": preset.get("preview_colors", []),
            "variables": preset.get("variables", {}),
            "syntax_css": preset.get("syntax_css", ""),
        }
    )


@themes_bp.route("/presets/<preset_id>/apply", methods=["POST"])
@require_auth
def preset_apply(preset_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    db = get_db()
    if _count_user_themes(db, user_id) >= MAX_THEMES_PER_USER:
        return (
            jsonify({"success": False, "error": f"הגעת למגבלה של {MAX_THEMES_PER_USER} ערכות מותאמות אישית"}),
            400,
        )

    try:
        new_theme = apply_preset_to_user(user_id=user_id, preset_id=preset_id, db=db)
        return jsonify(
            {
                "success": True,
                "theme": {"id": new_theme["id"], "name": new_theme["name"], "source": "preset"},
                "message": "הערכה נוספה בהצלחה!",
            }
        )
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception:
        logger.exception("Apply preset error")
        return jsonify({"success": False, "error": "שגיאה בהוספת הערכה"}), 500


@themes_bp.route("/import", methods=["POST"])
@require_auth
def import_theme():
    """
    ייבוא ערכת נושא מקובץ JSON.

    תומך בשני פורמטים:
    1) VS Code theme (עם colors)
    2) פורמט מקומי (עם variables)
    """
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    db = get_db()

    if _count_user_themes(db, user_id) >= MAX_THEMES_PER_USER:
        return (
            jsonify({"success": False, "error": f"הגעת למגבלה של {MAX_THEMES_PER_USER} ערכות מותאמות אישית"}),
            400,
        )

    json_content: str | None = None

    try:
        if "file" in request.files:
            file = request.files["file"]
            if not file or not file.filename:
                return jsonify({"success": False, "error": "לא נבחר קובץ"}), 400
            if not str(file.filename).lower().endswith(".json"):
                return jsonify({"success": False, "error": "הקובץ חייב להיות בסיומת .json"}), 400

            # בדיקת גודל
            try:
                file.seek(0, 2)
                size = int(file.tell() or 0)
            finally:
                try:
                    file.seek(0)
                except Exception:
                    pass

            if size > MAX_THEME_FILE_SIZE:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"הקובץ גדול מדי (מקסימום {MAX_THEME_FILE_SIZE // 1024}KB)",
                        }
                    ),
                    400,
                )

            json_content = file.read().decode("utf-8", errors="replace")

        elif request.is_json:
            payload = request.get_json(silent=True) or {}
            json_content = payload.get("json_content", "")

        if not json_content:
            return jsonify({"success": False, "error": "לא התקבל תוכן"}), 400

        is_valid, error_msg = validate_theme_json(json_content)
        if not is_valid:
            return jsonify({"success": False, "error": error_msg}), 400

        data = json.loads(json_content)

        syntax_css = ""
        if isinstance(data, dict) and "colors" in data:
            parsed = parse_vscode_theme(data)
            source = "vscode"
            token_colors = data.get("tokenColors", [])
            try:
                syntax_css = generate_codemirror_css_from_tokens(token_colors if isinstance(token_colors, list) else [])
            except Exception:
                syntax_css = ""
        else:
            parsed = parse_native_theme(data)
            source = "import"

        raw_vars = parsed.get("variables", {}) if isinstance(parsed, dict) else {}
        filtered_vars = validate_and_sanitize_theme_variables(raw_vars)

        new_theme = {
            "id": str(uuid.uuid4()),
            "name": (parsed.get("name") if isinstance(parsed, dict) else None) or "Imported Theme",
            "description": (parsed.get("description") if isinstance(parsed, dict) else None)
            or f"Imported from {source}",
            "is_active": False,
            "source": source,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "variables": filtered_vars,
            "syntax_css": syntax_css,
        }

        db.users.update_one(
            {"user_id": int(user_id)},
            {"$push": {"custom_themes": new_theme}},
            upsert=True,
        )

        return jsonify(
            {
                "success": True,
                "theme": {"id": new_theme["id"], "name": new_theme["name"], "source": source},
                "message": "הערכה יובאה בהצלחה!",
            }
        )

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception:
        logger.exception("Theme import error")
        return jsonify({"success": False, "error": "שגיאה בייבוא הערכה"}), 500


@themes_bp.route("/<theme_id>/export", methods=["GET"])
@require_auth
def export_theme(theme_id: str):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    db = get_db()
    user_doc = db.users.find_one({"user_id": int(user_id), "custom_themes.id": theme_id}, {"custom_themes.$": 1})
    if not user_doc or not user_doc.get("custom_themes"):
        return jsonify({"success": False, "error": "ערכה לא נמצאה"}), 404

    theme = (user_doc.get("custom_themes") or [None])[0]
    if not isinstance(theme, dict):
        return jsonify({"success": False, "error": "ערכה לא נמצאה"}), 404

    json_content = export_theme_to_json(theme)

    filename = (theme.get("name") or "theme").strip().replace('"', "").replace("/", "_")
    if not filename:
        filename = "theme"

    return Response(
        json_content,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
    )


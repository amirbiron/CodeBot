"""
Theme Presets Service
טוען ומנהל ערכות נושא מוכנות מראש
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from services.theme_parser_service import validate_and_sanitize_theme_variables
from services.theme_parser_service import sanitize_codemirror_css

logger = logging.getLogger(__name__)

# נתיב לקובץ ה-presets
PRESETS_FILE = Path(__file__).parent.parent / "webapp" / "static" / "data" / "theme_presets.json"

# מטמון בזיכרון
_presets_cache: dict | None = None


def load_presets(force_reload: bool = False) -> dict:
    """
    טוען את ערכות הנושא המוכנות מהקובץ.
    """
    global _presets_cache

    if _presets_cache is not None and not force_reload:
        return _presets_cache

    try:
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            _presets_cache = data
            logger.info("Loaded %s theme presets", len(data.get("presets", [])))
            return data
    except FileNotFoundError:
        logger.warning("Presets file not found: %s", PRESETS_FILE)
        return {"version": "1.0.0", "presets": []}
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in presets file: %s", e)
        return {"version": "1.0.0", "presets": []}


def get_preset_by_id(preset_id: str) -> Optional[dict]:
    """מחזיר ערכת נושא לפי ID."""
    data = load_presets()
    for preset in data.get("presets", []):
        if preset.get("id") == preset_id:
            return preset
    return None


def list_presets(category: Optional[str] = None) -> list[dict]:
    """
    מחזיר רשימת ערכות, אופציונלית לפי קטגוריה.

    Returns:
        רשימה של ערכות (ללא המשתנים - רק מטא-דאטה)
    """
    data = load_presets()
    presets = data.get("presets", [])

    if category:
        presets = [p for p in presets if p.get("category") == category]

    return [
        {
            "id": p["id"],
            "name": p["name"],
            "description": p.get("description", ""),
            "category": p.get("category", "dark"),
            "preview_colors": p.get("preview_colors", []),
        }
        for p in presets
        if isinstance(p, dict) and p.get("id") and p.get("name")
    ]


def apply_preset_to_user(user_id: int, preset_id: str, db) -> dict:
    """
    יוצר ערכה מותאמת אישית חדשה מתוך preset ושומר ב-MongoDB.
    """
    import uuid
    from datetime import datetime, timezone

    preset = get_preset_by_id(preset_id)
    if not preset:
        raise ValueError(f"Preset not found: {preset_id}")

    raw_vars = preset.get("variables", {}) if isinstance(preset, dict) else {}
    variables = validate_and_sanitize_theme_variables(raw_vars)

    raw_syntax_css = preset.get("syntax_css", "") if isinstance(preset, dict) else ""
    syntax_css = sanitize_codemirror_css(raw_syntax_css) if isinstance(raw_syntax_css, str) else ""

    new_theme = {
        "id": str(uuid.uuid4()),
        "name": preset["name"],
        "description": preset.get("description") or f"Based on {preset['name']} preset",
        "is_active": False,
        "source": "preset",
        "source_preset_id": preset_id,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "variables": variables,
        "syntax_css": syntax_css,
    }

    db.users.update_one(
        {"user_id": int(user_id)},
        {"$push": {"custom_themes": new_theme}},
        upsert=True,
    )

    return new_theme


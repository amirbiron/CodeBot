"""
webapp/ui_theme_defaults.py

ברירת מחדל לערכת נושא ב-WebApp.

מטרה:
- לאפשר להגדיר ערכה דפולט אחרת במקום "classic"
- לתמוך בערכה ציבורית (Shared) באמצעות token בפורמט: "shared:<slug>"

הגדרה:
- ENV: DEFAULT_UI_THEME
  - ערכים נתמכים:
    - ערכת builtin: classic/ocean/high-contrast/dark/dim/rose-pine-dawn/nebula
    - ערכה ציבורית: shared:<slug> (ה-slug הוא ה-ID שנשמר ב-DB; ללא רווחים. בדרך כלל אותיות קטנות/מספרים/קו תחתון, ולעיתים גם מקף)
  - כל ערך לא תקין → classic
"""

from __future__ import annotations

import os
import re
from typing import Tuple

# Builtin themes שניתן להשתמש בהן כברירת מחדל (לא כולל "custom" כי אין משמעות כ-Default למשתמש חדש)
_BUILTIN_DEFAULT_THEMES = {
    "classic",
    "ocean",
    "high-contrast",
    "dark",
    "dim",
    "rose-pine-dawn",
    "nebula",
}

_THEME_ID_SAFE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def normalize_default_ui_theme_raw(raw: str | None) -> str:
    """
    מנרמל/מנקה ערך ברירת מחדל לערכת נושא.

    מחזיר תמיד token תקין, או "classic" כנפילה לאחור.
    """
    v = str(raw or "").strip().lower()
    if not v:
        return "classic"

    if v in _BUILTIN_DEFAULT_THEMES:
        return v

    # תמיכה בערכה ציבורית: shared:<slug>
    if v.startswith("shared:"):
        theme_id = v.split("shared:", 1)[1].strip()
        if theme_id and _THEME_ID_SAFE_RE.fullmatch(theme_id):
            return f"shared:{theme_id}"

    return "classic"


def get_default_ui_theme_raw() -> str:
    """קורא מה-ENV ומחזיר token מנורמל."""
    return normalize_default_ui_theme_raw(os.getenv("DEFAULT_UI_THEME", "classic"))


def get_default_ui_theme_parts() -> Tuple[str, str, str]:
    """
    מחזיר (theme_type, theme_id, theme_attr) עבור ברירת המחדל.

    - builtin: ("builtin", "<id>", "<id>")
    - shared : ("shared", "<slug>", "shared:<slug>")
    """
    raw = get_default_ui_theme_raw()
    if raw.startswith("shared:"):
        theme_id = raw.split(":", 1)[1].strip()
        return "shared", theme_id, raw
    # builtin
    return "builtin", raw, raw


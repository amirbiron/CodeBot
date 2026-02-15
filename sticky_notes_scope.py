"""
Sticky Notes Scope ID — פונקציה קנונית לחישוב scope_id.

מטרת הקובץ: למנוע שכפול לוגיקה בין webapp/services ולצמצם סיכון לסטיות עתידיות.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional


def make_scope_id(user_id: int, file_name: Optional[str]) -> Optional[str]:
    """Generate a stable scope_id for a user's file name.

    Must stay consistent with sticky notes routing logic.
    """
    if not file_name:
        return None
    try:
        normalized = re.sub(r"\s+", " ", str(file_name).strip()).lower()
    except Exception:
        normalized = str(file_name or "").strip().lower()
    if not normalized:
        return None
    digest = hashlib.sha256(f"{int(user_id)}::{normalized}".encode("utf-8")).hexdigest()[:16]
    return f"user:{int(user_id)}:file:{digest}"


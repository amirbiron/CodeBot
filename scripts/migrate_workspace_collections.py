#!/usr/bin/env python3
"""מיגרציה: יצירת אוסף "שולחן עבודה" לכל משתמש קיים.

הרצה:
    python scripts/migrate_workspace_collections.py

הסקריפט בטוח להרצה מספר פעמים – הוא מדלג על משתמשים שכבר יש להם את האוסף.
"""

from __future__ import annotations

import logging
from typing import Any

from database.collections_manager import CollectionsManager


log = logging.getLogger(__name__)


def migrate_existing_users() -> None:
    """יוצר אוסף "שולחן עבודה" לכל המשתמשים שחסר להם."""
    try:
        from webapp.app import get_db  # import מקומי כדי להימנע מתלות מעגלית בזמן build
    except Exception as exc:  # pragma: no cover - קלט שגוי במיגרציה
        raise RuntimeError("לא ניתן לייבא את get_db מ-webapp.app") from exc

    db = get_db()
    manager = CollectionsManager(db)

    users_cursor = db.users.find({}, {"user_id": 1})  # type: ignore[attr-defined]
    created_count = 0
    checked_count = 0

    for raw_user in users_cursor:
        user_id = _safe_int((raw_user or {}).get("user_id"))
        if user_id is None:
            continue
        checked_count += 1

        existing = db.user_collections.find_one({  # type: ignore[attr-defined]
            "user_id": user_id,
            "name": "שולחן עבודה",
        })
        if existing:
            continue

        result = manager.create_collection(
            user_id=user_id,
            name="שולחן עבודה",
            description="קבצים שאני עובד עליהם כרגע",
            mode="manual",
            icon="🖥️",
            color="purple",
            is_favorite=True,
            sort_order=-1,
        )

        if result.get("ok"):
            created_count += 1
            log.info("✓ נוצר אוסף שולחן עבודה למשתמש %s", user_id)
        else:
            log.warning(
                "✗ כשל ביצירת אוסף למשתמש %s: %s",
                user_id,
                result.get("error", "unknown error"),
            )

    log.info("✅ מיגרציה הושלמה: נוצרו %s אוספים חדשים (מתוך %s משתמשים)", created_count, checked_count)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        migrate_existing_users()
    except Exception as exc:
        log.exception("❌ המיגרציה נכשלה")
        raise SystemExit(1) from exc
    raise SystemExit(0)

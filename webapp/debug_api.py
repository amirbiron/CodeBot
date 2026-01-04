"""
Debug API Blueprint (זמני)
==========================

מטרת ה-endpoints כאן היא דיאגנוסטיקה מהירה בזמן תקלות.
חשוב: הכל מוגבל למשתמש המחובר (session user_id) ולא חושף נתונים של משתמשים אחרים.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, session

logger = logging.getLogger(__name__)

debug_bp = Blueprint("debug_api", __name__, url_prefix="/api/debug")


def _get_user_id() -> int:
    try:
        return int(session.get("user_id") or 0)
    except Exception:
        return 0


@debug_bp.route("/inspect_file", methods=["GET"])
def inspect_file():
    """
    GET /api/debug/inspect_file?filename=<file_name>

    מחזיר JSON דיאגנוסטי על קובץ לפי file_name:
      - file_id
      - content_length
      - content_preview (500 תווים ראשונים)
      - has_embedding
      - embedding_preview (5 מספרים ראשונים)
    """
    user_id = _get_user_id()
    if user_id <= 0:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    filename = (request.args.get("filename") or "").strip()
    if not filename:
        return jsonify({"ok": False, "error": "missing_filename"}), 400

    try:
        from database import db
    except Exception as e:
        logger.error("debug inspect_file failed to import db: %s", e)
        return jsonify({"ok": False, "error": "db_unavailable"}), 500

    def _find_one(query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            return db.manager.collection.find_one(
                query,
                {"_id": 1, "code": 1, "embedding": 1},
                sort=[("version", -1), ("updated_at", -1), ("_id", -1)],
            )
        except TypeError:
            # תאימות למימושים ישנים שלא תומכים ב-projection/sort
            try:
                return db.manager.collection.find_one(query)
            except Exception:
                return None
        except Exception:
            return None

    base_query: Dict[str, Any] = {"user_id": user_id, "is_active": {"$ne": False}}

    # ניסיון 1: התאמה מדויקת
    doc = _find_one({**base_query, "file_name": filename})

    # ניסיון 2 (best-effort): התאמה לפי suffix, רק אם זה נראה כמו שם קובץ "נקי"
    if doc is None and "/" not in filename and len(filename) <= 180:
        try:
            safe = re.escape(filename) + r"$"
            doc = _find_one({**base_query, "file_name": {"$regex": safe}})
        except Exception:
            doc = None

    if not doc:
        return jsonify({"ok": False, "error": "not_found"}), 404

    try:
        file_id = str(doc.get("_id") or "")
    except Exception:
        file_id = ""

    code = doc.get("code")
    try:
        code_text = str(code or "")
    except Exception:
        code_text = ""

    embedding = doc.get("embedding")
    has_embedding = bool(isinstance(embedding, list) and len(embedding) > 0)
    embedding_preview = []
    if has_embedding:
        try:
            embedding_preview = [float(x) for x in embedding[:5]]
        except Exception:
            # אם יש שדה embedding אבל הוא לא תקין, עדיין נציג משהו כדי להבין שיש בעיה
            embedding_preview = []

    return jsonify(
        {
            "ok": True,
            "file_id": file_id,
            "content_length": len(code_text),
            "content_preview": code_text[:500],
            "has_embedding": has_embedding,
            "embedding_preview": embedding_preview,
        }
    )


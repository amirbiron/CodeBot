"""
Visual Rules API - Flask Blueprint
===================================
API לניהול כללים ויזואליים.

🔧 שימוש: הוסף ל-webapp/app.py:
    from webapp.rules_api import rules_bp
    app.register_blueprint(rules_bp, url_prefix='/api/rules')
"""

from __future__ import annotations

import logging
import os
import uuid
from functools import wraps

from flask import Blueprint, jsonify, request, session

from services.rules_storage import get_rules_storage
from services.rule_engine import AVAILABLE_FIELDS, EvaluationContext, get_rule_engine

logger = logging.getLogger(__name__)

rules_bp = Blueprint("rules", __name__)


def get_db():
    """קבלת חיבור DB (יבוא מ-webapp/app.py)."""
    # Lazy import כדי למנוע circular imports
    from webapp.app import get_db as app_get_db

    return app_get_db()


def admin_required(f):
    """
    דקורטור לבדיקת הרשאות admin.

    🔧 חשוב: משתמש בלוגיקה הקיימת של webapp/app.py!
    בודק גם login וגם שהמשתמש נמצא ב-ADMIN_USER_IDS.

    אפשרות 1 (מומלצת): שימוש בדקורטור הקיים:
        from webapp.app import admin_required

    אפשרות 2: מימוש מקומי (תואם לקיים):
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        # 1. בדיקת login
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"error": "unauthorized", "message": "נדרשת התחברות"}), 401

        # 2. בדיקת admin (חובה! לא אופציונלי!)
        admin_ids_env = os.getenv("ADMIN_USER_IDS", "")
        admin_ids_list = admin_ids_env.split(",") if admin_ids_env else []
        admin_ids = [int(x.strip()) for x in admin_ids_list if x.strip().isdigit()]

        if user_id not in admin_ids:
            return jsonify({"error": "forbidden", "message": "אין הרשאת אדמין"}), 403

        return f(*args, **kwargs)

    return decorated


@rules_bp.route("", methods=["GET"])
@admin_required
def rules_list():
    """GET /api/rules - רשימת כללים"""
    storage = get_rules_storage(get_db())

    enabled_only = request.args.get("enabled") == "true"
    tags = request.args.getlist("tag")

    try:
        limit = min(int(request.args.get("limit", 50)), 200)
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid limit/offset parameter"}), 400

    if limit < 0 or offset < 0:
        return jsonify({"error": "limit and offset must be non-negative"}), 400

    rules = storage.list_rules(
        enabled_only=enabled_only,
        tags=tags or None,
        limit=limit,
        offset=offset,
    )
    count = storage.count_rules(enabled_only=enabled_only)

    return jsonify(
        {
            "rules": rules,
            "total": count,
            "limit": limit,
            "offset": offset,
        }
    )


@rules_bp.route("/fields", methods=["GET"])
@admin_required
def rules_available_fields():
    """GET /api/rules/fields - שדות זמינים"""
    fields = [{"name": k, **v} for k, v in AVAILABLE_FIELDS.items()]
    return jsonify({"fields": fields})


@rules_bp.route("/test", methods=["POST"])
@admin_required
def rules_test():
    """POST /api/rules/test - בדיקת כלל על נתוני דמה"""
    try:
        data = request.get_json()
        # DEBUG: force-print incoming payload (tablet/no Network tab)
        # חשוב: לא להישבר אם ה-JSON לא dict (אנחנו מחזירים 400 בהמשך).
        try:
            print(f"🕵️‍♂️ DEBUG INCOMING RULE: {data.get('rule')}")
            print(f"🕵️‍♂️ DEBUG INCOMING DATA: {data.get('data')}")
        except Exception as e:
            print(f"🕵️‍♂️ DEBUG INCOMING RULE: <unavailable> err={e}")
            print(f"🕵️‍♂️ DEBUG INCOMING DATA: <unavailable> err={e}")
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid JSON"}), 400
        rule = data.get("rule", {})
        test_data = data.get("data", {})
        verbose = str(request.args.get("verbose", "true") or "true").strip().lower() not in {"0", "false", "no", "off"}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    engine = get_rule_engine()
    errors = engine.validate_rule(rule)

    if errors:
        return jsonify({"valid": False, "errors": errors})

    # FORCE VERBOSE TRUE FOR DEBUGGING
    context = EvaluationContext(data=test_data, metadata={"verbose": True})
    result = engine.evaluate(rule, context)

    return jsonify(
        {
            "valid": True,
            "matched": result.matched,
            "triggered_conditions": result.triggered_conditions,
            "actions": result.actions_to_execute,
            "evaluation_time_ms": result.evaluation_time_ms,
        }
    )


@rules_bp.route("/<rule_id>", methods=["GET"])
@admin_required
def rules_get(rule_id):
    """GET /api/rules/{rule_id} - קבלת כלל ספציפי"""
    storage = get_rules_storage(get_db())
    rule = storage.get_rule(rule_id)

    if not rule:
        return jsonify({"error": "Rule not found"}), 404

    return jsonify(rule)


@rules_bp.route("", methods=["POST"])
@admin_required
def rules_create():
    """POST /api/rules - יצירת כלל חדש"""
    try:
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid JSON"}), 400
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    # כדי להתאים ל-validate_rule שמצפה ל-rule_id
    if not data.get("rule_id"):
        data["rule_id"] = f"rule_{uuid.uuid4().hex[:12]}"

    engine = get_rule_engine()
    errors = engine.validate_rule(data)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    storage = get_rules_storage(get_db())
    rule_id = storage.save_rule(data)

    return jsonify({"rule_id": rule_id, "message": "Rule created"}), 201


@rules_bp.route("/<rule_id>", methods=["PUT"])
@admin_required
def rules_update(rule_id):
    """PUT /api/rules/{rule_id} - עדכון כלל"""
    try:
        data = request.get_json()
        if not isinstance(data, dict):
            return jsonify({"error": "Invalid JSON"}), 400
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    data["rule_id"] = rule_id

    engine = get_rule_engine()
    errors = engine.validate_rule(data)
    if errors:
        return jsonify({"error": "Validation failed", "details": errors}), 400

    storage = get_rules_storage(get_db())
    storage.save_rule(data)

    return jsonify({"rule_id": rule_id, "message": "Rule updated"})


@rules_bp.route("/<rule_id>", methods=["DELETE"])
@admin_required
def rules_delete(rule_id):
    """DELETE /api/rules/{rule_id} - מחיקת כלל"""
    storage = get_rules_storage(get_db())
    deleted = storage.delete_rule(rule_id)

    if not deleted:
        return jsonify({"error": "Rule not found"}), 404

    return jsonify({"message": "Rule deleted"})


@rules_bp.route("/<rule_id>/toggle", methods=["POST"])
@admin_required
def rules_toggle(rule_id):
    """POST /api/rules/{rule_id}/toggle - הפעלה/כיבוי כלל"""
    try:
        data = request.get_json() or {}
        enabled = data.get("enabled", True)
    except Exception:
        enabled = True

    storage = get_rules_storage(get_db())
    success = storage.toggle_rule(rule_id, enabled)

    if not success:
        return jsonify({"error": "Rule not found"}), 404

    return jsonify({"rule_id": rule_id, "enabled": enabled})


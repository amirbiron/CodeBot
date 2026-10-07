"""
GitHub Webhook Handler

מטפל באירועי push מ-GitHub ומפעיל סנכרון, ובאירועי ``deployment_status`` של אתר התיעוד ומפעיל
מעבר אינדוקס (``services/docs_index_service.py``).

ה-Blueprint מוחרג מהמגבלה הגורפת של ``Flask-Limiter`` (``webapp/app.py``, אחרי יצירת המגביל): ה-
webhook מגיע מכמה כתובות קבועות של GitHub, והמגבלה לפי IP הייתה חוסמת אותו ב-429 כשמספר המשלוחים
עובר אותה — ולכל פריסה של האתר יש כמה סטטוסים. כל בקשה כאן נבדקת בחתימה לפני כל עבודה.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")


def verify_github_signature(payload_body: bytes, signature: str) -> bool:
    """
    אימות חתימת GitHub Webhook

    Args:
        payload_body: גוף הבקשה (bytes)
        signature: ערך X-Hub-Signature-256

    Returns:
        True אם החתימה תקינה
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")

    if not secret:
        logger.warning("GITHUB_WEBHOOK_SECRET not set!")
        return False

    if not signature or not signature.startswith("sha256="):
        return False

    expected_signature = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()

    received_signature = signature[7:]  # Remove "sha256=" prefix

    return hmac.compare_digest(expected_signature, received_signature)


@webhooks_bp.route("/github", methods=["POST"])
def handle_github_webhook():
    """
    Endpoint לקבלת webhooks מ-GitHub

    Events supported:
    - push: סנכרון שינויים
    - ping: בדיקת תקינות
    - deployment_status: מעבר אינדוקס של אתר התיעוד
    """
    # אימות חתימה
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_github_signature(request.data, signature):
        logger.warning("Invalid webhook signature")
        return jsonify({"error": "Invalid signature"}), 401

    # זיהוי סוג האירוע
    event_type = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")

    logger.info(f"Received webhook: {event_type} (delivery: {delivery_id})")

    # Ping event (בדיקת תקינות)
    if event_type == "ping":
        return jsonify({"message": "pong", "delivery_id": delivery_id}), 200

    # Push event
    if event_type == "push":
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid JSON payload", "delivery_id": delivery_id}), 400
        return handle_push_event(payload, delivery_id)

    # פריסה של אתר התיעוד
    if event_type == "deployment_status":
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid JSON payload", "delivery_id": delivery_id}), 400
        return handle_deployment_status_event(payload, delivery_id)

    # אירועים אחרים - מתעלמים
    return jsonify({"message": f"Event '{event_type}' ignored", "delivery_id": delivery_id}), 200


def handle_push_event(payload: dict, delivery_id: str):
    """
    טיפול באירוע push

    Args:
        payload: JSON מ-GitHub
        delivery_id: מזהה ייחודי לאירוע
    """
    try:
        if not isinstance(payload, dict):
            return jsonify({"error": "Invalid JSON payload", "delivery_id": delivery_id}), 400
        # חילוץ מידע
        ref = str(payload.get("ref") or "")
        repo = payload.get("repository", {}) or {}
        repo_name = str(repo.get("name") or "")
        payload_default_branch = str(repo.get("default_branch") or "")
        # payload יכול להכיל null -> נוודא שתמיד נקבל מחרוזת כדי לא לקרוס על slicing
        new_sha = str(payload.get("after") or "")
        old_sha = str(payload.get("before") or "")

        # default branch דינמי: קודם DB (initial_import), ואז payload; רק אם לא יודעים בכלל ניפול ל-main/master.
        default_branch = ""
        try:
            from database.db_manager import get_db

            db = get_db()
            meta = db.repo_metadata.find_one({"repo_name": repo_name}) if repo_name else None
            if meta and meta.get("default_branch"):
                default_branch = str(meta["default_branch"])
        except Exception:
            default_branch = ""
        if not default_branch:
            default_branch = str(payload_default_branch or "").strip() or ""

        # אם זיהינו default_branch (DB/payload) נהיה קשוחים: רק הבראנץ' הזה מפעיל סנכרון.
        # רק אם אין לנו default_branch בכלל נרשה main/master כ-fallback.
        if default_branch:
            allowed_refs = {f"refs/heads/{default_branch}"}
        else:
            allowed_refs = {"refs/heads/main", "refs/heads/master"}

        # רק default branch (עם fallback ל-main/master)
        if ref not in allowed_refs:
            logger.info(f"Ignoring push to {ref} (default_branch={default_branch})")
            return jsonify({"message": f"Ignoring branch {ref}", "delivery_id": delivery_id}), 200

        # בדיקה ש-SHA תקין
        if new_sha == "0" * 40:
            # Branch deleted
            logger.info("Branch deleted, ignoring")
            return jsonify({"message": "Branch deleted"}), 200

        logger.info(f"Processing push: {repo_name} {old_sha[:7]}..{new_sha[:7]}")

        # הפעלת סנכרון ברקע
        from services.repo_sync_service import trigger_sync

        job_id = trigger_sync(
            repo_name=repo_name,
            new_sha=new_sha,
            old_sha=old_sha,
            trigger="webhook",
            delivery_id=delivery_id,
        )

        return (
            jsonify(
                {
                    "status": "queued",
                    "job_id": job_id,
                    "repo": repo_name,
                    "sha": new_sha[:7],
                    "delivery_id": delivery_id,
                }
            ),
            202,
        )

    except Exception as e:
        logger.exception(f"Failed to process push event: {e}")
        return jsonify({"error": "Processing failed", "delivery_id": delivery_id}), 500


def handle_deployment_status_event(payload: dict, delivery_id: str):
    """פריסה מוצלחת של אתר התיעוד ← מעבר אינדוקס לפי הקומיט שלה.

    GitHub שולח כמה סטטוסים לכל פריסה (``deployment_status.state``; נמדד: waiting, queued,
    in_progress, success), וגם לפריסות של ריפו או סביבה אחרים אם ה-webhook מוגדר עליהם. רק
    ``success`` של ``github-pages`` בריפו המקור מפעיל מעבר; כל השאר חוזרים ב-200 עם הסיבה, כדי
    שיומן המשלוחים ב-GitHub יאמר למה. ה-sha נכנס לכתובת של הקובץ, ולכן הוא נבדק בדקדוק לפני הכול.

    המעבר רץ ברקע (``request_pass``), והתשובה חוזרת מיד: ל-gevent אין תקרה על משך בקשה.
    """
    from pymongo.errors import PyMongoError

    from services import docs_index_service as docs_index
    from services import docs_search_contract as contract

    deployment = payload.get("deployment")
    status = payload.get("deployment_status")
    repository = payload.get("repository")
    if not (isinstance(deployment, dict) and isinstance(status, dict) and isinstance(repository, dict)):
        return jsonify({"error": "Invalid deployment_status payload", "delivery_id": delivery_id}), 400

    if repository.get("full_name") != contract.SOURCE_REPO_FULL_NAME:
        reason = "other_repository"
    elif deployment.get("environment") != contract.PAGES_ENVIRONMENT:
        reason = "other_environment"
    elif status.get("state") != "success":
        reason = "not_success"
    else:
        reason = ""
    if reason:
        return jsonify({"message": "ignored", "reason": reason, "delivery_id": delivery_id}), 200

    sha = deployment.get("sha")
    if not contract.is_commit_sha(sha):
        return jsonify({"error": "Invalid deployment sha", "delivery_id": delivery_id}), 400

    from database.db_manager import get_db

    db = get_db()
    if db is None:
        return jsonify({"error": "database_unavailable", "delivery_id": delivery_id}), 503
    try:
        result = docs_index.request_pass(db, trigger=docs_index.TRIGGER_DEPLOY, commit=sha)
    except PyMongoError:
        logger.exception("docs index: could not request a pass for deployment %s", sha[:7])
        return jsonify({"error": "database_unavailable", "delivery_id": delivery_id}), 503
    logger.info("docs index: deployment %s %s a pass", sha[:7], result)
    return jsonify({"status": result, "sha": sha[:7], "delivery_id": delivery_id}), 202


@webhooks_bp.route("/github/test", methods=["POST"])
def test_webhook():
    """Endpoint לבדיקה ידנית (ללא אימות חתימה)"""
    if not current_app.debug:
        return jsonify({"error": "Only available in debug mode"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    return handle_push_event(payload, "test-delivery")


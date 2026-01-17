"""
GitHub Webhook Handler

מטפל באירועי push מ-GitHub ומפעיל סנכרון
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

        # default branch דינמי: קודם DB (initial_import), ואז payload, ואז fallback
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
            default_branch = str(payload_default_branch or "").strip() or "main"

        allowed_refs = {
            f"refs/heads/{default_branch}",
            "refs/heads/main",  # fallback
            "refs/heads/master",  # fallback
        }

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


@webhooks_bp.route("/github/test", methods=["POST"])
def test_webhook():
    """Endpoint לבדיקה ידנית (ללא אימות חתימה)"""
    if not current_app.debug:
        return jsonify({"error": "Only available in debug mode"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    return handle_push_event(payload, "test-delivery")


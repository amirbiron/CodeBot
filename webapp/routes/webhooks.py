"""
GitHub Webhook Handler

מטפל באירועי push מ-GitHub ומפעיל סנכרון, ובאירועי ``deployment_status`` של אתר התיעוד ומפעיל
מעבר אינדוקס (``services/docs_index_service.py``). push לענף הראשי של ריפו המקור מבקש גם מעבר
שבודק את הקובץ הראשי של האתר — רשת הביטחון של האינדקס (``_request_docs_index_check``). ושני נתיבים
חתומים משרתים את הבדיקה שאחרי פריסת האתר ב-CI: מצב האינדקס לקומיט, ושליחה חוזרת של בקשת המעבר
(``docs_index_check_status`` ו-``docs_index_check_pass``).

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
    - push: סנכרון שינויים (ובריפו המקור גם רשת הביטחון של אינדקס התיעוד)
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

        response = {
            "status": "queued",
            "job_id": job_id,
            "repo": repo_name,
            "sha": new_sha[:7],
            "delivery_id": delivery_id,
        }
        from services.docs_search_contract import SOURCE_REPO_FULL_NAME

        if repo.get("full_name") == SOURCE_REPO_FULL_NAME:
            response["docs_index"] = _request_docs_index_check()
        return jsonify(response), 202

    except Exception as e:
        logger.exception(f"Failed to process push event: {e}")
        return jsonify({"error": "Processing failed", "delivery_id": delivery_id}), 500


def _request_docs_index_check() -> str:
    """רשת הביטחון של אינדקס התיעוד: מעבר שבודק את הקובץ הראשי של האתר, ב-push לענף הראשי של ריפו המקור.

    הבדיקה לא תלויה בסנכרון של המראה — היא קוראת את הקובץ מהאתר — ולכן היא כאן, בשכבה שמנתבת את
    אירועי GitHub לפי ריפו, ליד ה-webhook של הפריסה, ולא בסוף הסנכרון הכללי. בזמן ה-push הבנייה שלו
    עוד לא נפרסה, כך שהיא תופסת פריסה **קודמת** שה-webhook שלה לא הגיע; בדרך כלל היא נגמרת ב-304.

    מחזיר את מה ש-``request_pass`` מחזיר, או ``database_unavailable``: הסנכרון כבר בתור, ולכן מסד שאינו
    זמין לא משנה את התשובה עליו, והוא מדווח בשדה ``docs_index``. חריגה אחרת היא באג, ועולה.
    """
    from pymongo.errors import PyMongoError

    from database.db_manager import get_db
    from services import docs_index_service as docs_index

    db = get_db()
    if db is None:
        return "database_unavailable"
    try:
        return docs_index.request_pass(db, trigger=docs_index.TRIGGER_PUSH)
    except PyMongoError:
        logger.exception("docs index: the push safety net could not request a pass")
        return "database_unavailable"


def handle_deployment_status_event(payload: dict, delivery_id: str):
    """פריסה מוצלחת של אתר התיעוד ← מעבר אינדוקס לפי הקומיט שלה.

    GitHub שולח כמה סטטוסים לכל פריסה (``deployment_status.state``; נמדד: waiting, queued,
    in_progress, success), וגם לפריסות של ריפו או סביבה אחרים אם ה-webhook מוגדר עליהם. רק
    ``success`` של ``github-pages`` בריפו המקור מפעיל מעבר; כל השאר חוזרים ב-200 עם הסיבה, כדי
    שיומן המשלוחים ב-GitHub יאמר למה. ה-sha נכנס לכתובת של הקובץ, ולכן הוא נבדק בדקדוק לפני הכול.

    המעבר רץ ברקע (``request_pass``), והתשובה חוזרת מיד: ל-gevent אין תקרה על משך בקשה.
    """
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

    result = _request_deploy_pass(sha, "deployment")
    if result is None:
        return jsonify({"error": "database_unavailable", "delivery_id": delivery_id}), 503
    return jsonify({"status": result, "sha": sha[:7], "delivery_id": delivery_id}), 202


def _request_deploy_pass(sha: str, source: str):
    """מעבר לפי הקומיט של פריסת האתר — מה שה-webhook של הפריסה מבקש, ומה שהבדיקה שאחרי הפריסה שולחת שוב.

    ``source`` נכנס לשורת הלוג בלבד, כדי שיהיה אפשר לספור כמה מעברים הגיעו מהבדיקה ולא מ-GitHub. מחזיר את מה
    ש-``request_pass`` מחזיר, או ``None`` כשהמסד אינו זמין — והקורא עונה 503. כשל של המסד נרשם כאן, עם traceback.
    """
    from pymongo.errors import PyMongoError

    from database.db_manager import get_db
    from services import docs_index_service as docs_index

    db = get_db()
    if db is None:
        return None
    try:
        result = docs_index.request_pass(db, trigger=docs_index.TRIGGER_DEPLOY, commit=sha)
    except PyMongoError:
        logger.exception("docs index: could not request a pass for %s %s", source, sha[:7])
        return None
    logger.info("docs index: %s %s %s a pass", source, sha[:7], result)
    return result


# ---------------------------------------------------------------------------
# הבדיקה שאחרי פריסת האתר (``scripts/docs_index_check.py``, ב-``documentation.yml``)
#
# ה-CI ממתין שהאינדקס יגיע לקומיט שנפרס, ושולח שוב את בקשת המעבר כשה-webhook של הפריסה לא הביא לאחד —
# למשל כשהוא הגיע בזמן שהוובאפ עלה מחדש. שני הנתיבים חתומים באותו סוד ובאותה צורה כמו ה-webhook של GitHub
# (``verify_github_signature``), ולכן אינם פתוחים למי שאין לו את הסוד. החתימה היא על הגוף בלבד, בלי חותמת
# זמן, כמו של GitHub: מי שהקליט בקשה יכול לשלוח אותה שוב, וזה מחזיר לו מצב או מבקש מעבר לאותו קומיט —
# מעבר שאין לו מה לשנות נגמר בלי הטמעות.
# ---------------------------------------------------------------------------


def _signed_commit_request():
    """הקומיט מגוף חתום ``{"commit": "<sha>"}``, או תשובת סירוב: 401 לחתימה, 400 לגוף."""
    from services import docs_search_contract as contract

    if not verify_github_signature(request.data, request.headers.get("X-Hub-Signature-256", "")):
        logger.warning("docs index check: invalid signature")
        return None, (jsonify({"error": "Invalid signature"}), 401)
    payload = request.get_json(silent=True)
    commit = payload.get("commit") if isinstance(payload, dict) else None
    if not contract.is_commit_sha(commit):
        return None, (jsonify({"error": "invalid_commit"}), 400)
    return commit, None


@webhooks_bp.route("/docs-index/status", methods=["POST"])
def docs_index_check_status():
    """המצב שהבדיקה צריכה כדי להחליט (``status_for_deploy_check``) — קריאה בלבד, ממסמך המצב."""
    from pymongo.errors import PyMongoError

    from database.db_manager import get_db
    from services import docs_index_service as docs_index

    commit, failure = _signed_commit_request()
    if failure is not None:
        return failure
    db = get_db()
    if db is None:
        return jsonify({"error": "database_unavailable"}), 503
    try:
        status = docs_index.status_for_deploy_check(db, commit)
    except PyMongoError:
        logger.exception("docs index check: could not read the state for %s", commit[:7])
        return jsonify({"error": "database_unavailable"}), 503
    return jsonify(docs_index.jsonable(status)), 200


@webhooks_bp.route("/docs-index/pass", methods=["POST"])
def docs_index_check_pass():
    """שליחה חוזרת של בקשת המעבר של הפריסה — אותה בקשה שה-webhook של ``deployment_status`` מבקש."""
    commit, failure = _signed_commit_request()
    if failure is not None:
        return failure
    result = _request_deploy_pass(commit, "ci re-delivery")
    if result is None:
        return jsonify({"error": "database_unavailable"}), 503
    return jsonify({"status": result, "sha": commit[:7]}), 202


@webhooks_bp.route("/github/test", methods=["POST"])
def test_webhook():
    """Endpoint לבדיקה ידנית (ללא אימות חתימה)"""
    if not current_app.debug:
        return jsonify({"error": "Only available in debug mode"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid JSON payload"}), 400
    return handle_push_event(payload, "test-delivery")


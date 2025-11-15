from __future__ import annotations

from flask import Blueprint, jsonify, request, session
from functools import wraps
from typing import Any, Dict, Optional
from datetime import datetime, timezone, timedelta
import os


def get_db():
    from webapp.app import get_db as _get_db  # lazy import to avoid circulars
    return _get_db()


push_bp = Blueprint("push_api", __name__, url_prefix="/api/push")

_INDEX_READY = False


def _ensure_indexes() -> None:
    global _INDEX_READY
    if _INDEX_READY:
        return
    try:
        db = get_db()
        coll = db.push_subscriptions
        try:
            from pymongo import ASCENDING, IndexModel  # type: ignore

            models = [
                IndexModel([("user_id", ASCENDING), ("endpoint", ASCENDING)], name="user_endpoint_unique", unique=True),
                IndexModel([("user_id", ASCENDING), ("created_at", ASCENDING)], name="user_created_idx"),
            ]
            coll.create_indexes(models)
        except Exception:
            try:
                coll.create_index([("user_id", 1), ("endpoint", 1)], name="user_endpoint_unique", unique=True)
            except Exception:
                pass
            try:
                coll.create_index([("user_id", 1), ("created_at", 1)], name="user_created_idx")
            except Exception:
                pass
        _INDEX_READY = True
    except Exception:
        # Never fail request due to index creation
        pass


def require_auth(f):
    @wraps(f)
    def _inner(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    return _inner


@push_bp.route("/public-key", methods=["GET"])
def get_public_key():
    key = (os.getenv("VAPID_PUBLIC_KEY") or "").strip()
    if not key:
        # Return ok with empty key to allow client to show CTA but fail gracefully
        return jsonify({"ok": True, "vapidPublicKey": ""}), 200
    return jsonify({"ok": True, "vapidPublicKey": key}), 200


@push_bp.route("/subscribe", methods=["POST"])
@require_auth
def subscribe():
    try:
        _ensure_indexes()
        user_id = int(session["user_id"])  # type: ignore
        payload = request.get_json(silent=True) or {}
        # Normalize minimal fields we care about
        endpoint = str((payload or {}).get("endpoint") or "").strip()
        keys = dict((payload or {}).get("keys") or {})
        if not endpoint or not isinstance(keys, dict):
            return jsonify({"ok": False, "error": "Invalid subscription"}), 400

        now_utc = datetime.now(timezone.utc)
        set_fields = {
            "user_id": user_id,
            "endpoint": endpoint,
            "keys": {"p256dh": keys.get("p256dh", ""), "auth": keys.get("auth", "")},
            "subscription": payload,  # store full object for sending
            "content_encoding": (payload.get("contentEncoding") or payload.get("content_encoding") or ""),
            "updated_at": now_utc,
        }
        db = get_db()
        # Upsert per (user, endpoint)
        db.push_subscriptions.update_one(
            {"user_id": user_id, "endpoint": endpoint},
            {"$set": set_fields, "$setOnInsert": {"created_at": now_utc}},
            upsert=True,
        )
        try:
            from observability import emit_event  # type: ignore

            emit_event("push_subscribed", severity="info", user_id=int(user_id))
        except Exception:
            pass
        return jsonify({"ok": True}), 201
    except Exception:
        return jsonify({"ok": False, "error": "Failed to save subscription"}), 500


@push_bp.route("/subscribe", methods=["DELETE"])
@require_auth
def unsubscribe():
    try:
        user_id = int(session["user_id"])  # type: ignore
        payload = request.get_json(silent=True) or {}
        endpoint = str((payload or {}).get("endpoint") or request.args.get("endpoint") or "").strip()
        if not endpoint:
            return jsonify({"ok": False, "error": "endpoint required"}), 400
        db = get_db()
        db.push_subscriptions.delete_many({"user_id": user_id, "endpoint": endpoint})
        try:
            from observability import emit_event  # type: ignore

            emit_event("push_unsubscribed", severity="info", user_id=int(user_id))
        except Exception:
            pass
        return jsonify({"ok": True}), 200
    except Exception:
        return jsonify({"ok": False, "error": "Failed to unsubscribe"}), 500


# --- Background sender (opt-in via env) ---
_sender_started = False


def start_sender_if_enabled() -> None:
    global _sender_started
    if _sender_started:
        return
    enabled = (os.getenv("PUSH_NOTIFICATIONS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"})
    if not enabled:
        return
    try:
        import threading

        def _runner():
            try:
                _loop_send_due_reminders()
            except Exception:
                # Never crash main thread due to background errors
                pass

        t = threading.Thread(target=_runner, name="push-sender", daemon=True)
        t.start()
        _sender_started = True
    except Exception:
        pass


def _loop_send_due_reminders() -> None:
    import time
    SLEEP_SECONDS = max(20, int(os.getenv("PUSH_SEND_INTERVAL_SECONDS", "60") or "60"))
    while True:
        try:
            _send_due_once()
        except Exception:
            pass
        try:
            time.sleep(SLEEP_SECONDS)
        except Exception:
            # if interrupted, just continue
            continue


def _send_due_once(max_users: int = 100, max_per_user: int = 10) -> None:
    """Scan due sticky-note reminders and send web push per user subscriptions.

    Idempotency: send once per reminder schedule by checking last_push_success_at < remind_at.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    # Find up to N users with due reminders
    pipeline = [
        {
            "$match": {
                "status": {"$in": ["pending", "snoozed"]},
                "ack_at": None,
                "remind_at": {"$lte": now},
                "$expr": {
                    "$or": [
                        {"$eq": ["$last_push_success_at", None]},
                        {"$lt": ["$last_push_success_at", "$remind_at"]},
                    ]
                },
            }
        },
        {"$sort": {"remind_at": 1}},
        {"$limit": max_users * max_per_user},
    ]
    try:
        due = list(db.note_reminders.aggregate(pipeline))
    except Exception:
        due = []
    if not due:
        return
    # Group by user
    by_user: Dict[int, list] = {}
    for r in due:
        try:
            uid = int(r.get("user_id"))
            by_user.setdefault(uid, []).append(r)
        except Exception:
            continue
    for uid, items in list(by_user.items())[:max_users]:
        _send_for_user(uid, items[:max_per_user])


def _claim_reminder(db, reminder_doc: dict, ttl_seconds: int | None = None) -> bool:
    """Try to claim a reminder for sending to avoid duplicate pushes across workers.

    Returns True if this process owns the claim; False otherwise.
    """
    try:
        now = datetime.now(timezone.utc)
        ttl = max(10, int(os.getenv("PUSH_CLAIM_TTL_SECONDS", str(ttl_seconds or 60))))
        until = now + timedelta(seconds=ttl)
        try:
            import threading

            ident = threading.get_ident()
        except Exception:
            ident = 0
        owner = f"{os.getenv('HOSTNAME','')}-{os.getpid()}-{ident}"
        r_id = reminder_doc.get("_id")
        if not r_id:
            return False
        filt = {
            "_id": r_id,
            "ack_at": None,
            "status": {"$in": ["pending", "snoozed"]},
            # not currently claimed or claim expired
            "$or": [
                {"push_claimed_until": {"$exists": False}},
                {"push_claimed_until": {"$lte": now}},
            ],
        }
        upd = {
            "$set": {
                "push_claimed_by": owner,
                "push_claimed_at": now,
                "push_claimed_until": until,
            }
        }
        res = db.note_reminders.update_one(filt, upd)
        return bool(getattr(res, "matched_count", 0))
    except Exception:
        return False


def _send_for_user(user_id: int, reminders: list[dict]) -> None:
    db = get_db()
    subs = list(db.push_subscriptions.find({"user_id": int(user_id)}))
    if not subs:
        return
    # Load keys/env once
    vapid_private = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()
    vapid_email = (os.getenv("VAPID_SUB_EMAIL") or os.getenv("SUPPORT_EMAIL") or "").strip()
    if not vapid_private or not subs:
        return
    try:
        from pywebpush import webpush, WebPushException  # type: ignore
        import json
    except Exception:
        return

    # Track endpoints that should be removed after processing all reminders
    endpoints_to_delete: set[str] = set()

    for r in reminders:
        # Try to claim this reminder to avoid duplicate push across workers
        try:
            if not _claim_reminder(db, r):
                continue
        except Exception:
            # If claiming fails unexpectedly, fall back to best-effort send
            pass
        payload = {
            "title": "🔔 יש פתק ממתין",
            "body": _coerce_preview(db, r),
            "data": {
                "note_id": str(r.get("note_id") or ""),
                "file_id": str(r.get("file_id") or ""),
            },
            "actions": [
                {"action": "open_note", "title": "פתח פתק"},
                {"action": "snooze_10", "title": "דחה 10 דק׳"},
                {"action": "snooze_60", "title": "דחה שעה"},
                {"action": "snooze_1440", "title": "דחה 24 שעות"},
            ],
        }
        success_any = False
        for sub in subs:
            try:
                ep = str(sub.get("endpoint") or "")
                if ep and ep in endpoints_to_delete:
                    # Already known dead this run – skip extra attempts
                    continue
                info = sub.get("subscription") or {"endpoint": ep, "keys": sub.get("keys")}
                webpush(
                    subscription_info=info,
                    data=json.dumps(payload, ensure_ascii=False),
                    vapid_private_key=vapid_private,
                    vapid_claims={"sub": (f"mailto:{vapid_email}" if vapid_email and not vapid_email.startswith("mailto:") else vapid_email) or "mailto:support@example.com"},
                )
                success_any = True
            except Exception as ex:
                try:
                    from pywebpush import WebPushException  # type: ignore

                    if isinstance(ex, WebPushException):
                        status = getattr(getattr(ex, "response", None), "status_code", 0)
                        if status in (404, 410):
                            if ep:
                                endpoints_to_delete.add(ep)
                except Exception:
                    pass
                continue
        if success_any:
            try:
                db.note_reminders.update_one(
                    {"_id": r.get("_id")},
                    {"$set": {"last_push_success_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
                )
            except Exception:
                pass

    # After processing all reminders for this user, remove dead endpoints once
    if endpoints_to_delete:
        try:
            db.push_subscriptions.delete_many({"user_id": int(user_id), "endpoint": {"$in": list(endpoints_to_delete)}})
        except Exception:
            pass


def _coerce_preview(db, reminder_doc: dict) -> str:
    try:
        note_id = str(reminder_doc.get("note_id") or "")
        if not note_id:
            return ""
        # Try ObjectId, else raw
        try:
            from bson import ObjectId  # type: ignore

            oid = ObjectId(note_id)
        except Exception:
            oid = None
        note = None
        if oid is not None:
            try:
                note = db.sticky_notes.find_one({"_id": oid})
            except Exception:
                note = None
        if note is None and note_id:
            try:
                note = db.sticky_notes.find_one({"_id": note_id})
            except Exception:
                note = None
        if not isinstance(note, dict):
            return ""
        content = str(note.get("content") or note.get("anchor_text") or "").strip()
        if not content:
            return ""
        parts = [w for w in content.split() if w]
        if not parts:
            return ""
        head = parts[:6]
        out = " ".join(head)
        if len(parts) > 6:
            out += "…"
        return out
    except Exception:
        return ""

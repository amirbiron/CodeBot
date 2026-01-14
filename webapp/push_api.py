from __future__ import annotations

from flask import Blueprint, jsonify, request, session
from functools import wraps
from typing import Any, Dict, Optional
from datetime import datetime, timezone, timedelta
import os
import hashlib
import logging


def get_db():
    from webapp.app import get_db as _get_db  # lazy import to avoid circulars
    return _get_db()


push_bp = Blueprint("push_api", __name__, url_prefix="/api/push")

_INDEX_READY = False

# --- Lightweight in-memory SW report buffer (debug aid) ---
# We intentionally keep this small and lossy: it's only for quick debugging
# when users don't have access to DevTools or server logs.
_SW_REPORTS_MAX = 80
_SW_REPORTS: list[dict[str, Any]] = []

def _append_sw_report(item: dict[str, Any]) -> None:
    try:
        _SW_REPORTS.append(item)
        # Keep only last N
        if len(_SW_REPORTS) > _SW_REPORTS_MAX:
            del _SW_REPORTS[: max(0, len(_SW_REPORTS) - _SW_REPORTS_MAX)]
    except Exception:
        pass

def _persist_sw_report_to_db(doc: dict[str, Any]) -> None:
    """Best-effort persistence for SW reports (for multi-worker setups)."""
    try:
        db = get_db()
    except Exception:
        return
    try:
        coll = db.sw_push_reports
    except Exception:
        return
    try:
        coll.insert_one(doc)
    except Exception:
        return


def _env_positive_int(name: str, default: int) -> int:
    try:
        raw = os.getenv(name)
        if raw is None:
            return default
        raw = raw.strip()
        if not raw:
            return default
        value = int(raw)
        return value if value > 0 else default
    except Exception:
        return default


_PUSH_DELIVERY_TTL_SECONDS = _env_positive_int("PUSH_DELIVERY_TTL_SECONDS", 900)
_PUSH_TEST_TTL_SECONDS = _env_positive_int("PUSH_TEST_TTL_SECONDS", 120)
_PUSH_DELIVERY_URGENCY = (os.getenv("PUSH_DELIVERY_URGENCY") or "high").strip().lower()
if _PUSH_DELIVERY_URGENCY not in {"very-low", "low", "normal", "high"}:
    _PUSH_DELIVERY_URGENCY = "high"


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


def _session_user_id():
    """Return current session user id as int when possible, else string."""
    try:
        uid = session.get("user_id")
        try:
            return int(uid)  # type: ignore[arg-type]
        except Exception:
            return str(uid or "")
    except Exception:
        return ""


def _user_id_variants(uid):
    """Return list of possible representations for DB queries (int/str)."""
    variants: set = set()
    try:
        variants.add(uid)
    except Exception:
        pass
    try:
        variants.add(int(uid))
    except Exception:
        pass
    try:
        variants.add(str(uid))
    except Exception:
        pass
    return list(variants)


def require_auth(f):
    @wraps(f)
    def _inner(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    return _inner


def _coerce_vapid_pair() -> tuple[str, str]:
    """Return (public, private) VAPID keys from ENV.

    Supports either raw base64url strings or a JSON blob pasted into the env
    by mistake (e.g. output of `web-push generate-vapid-keys`).
    """
    # IMPORTANT: keep public/private from the same keypair source (avoid mismatches).
    # - If both WORKER_* keys exist, use them.
    # - Else use VAPID_* keys.
    worker_pub = (os.getenv("WORKER_VAPID_PUBLIC_KEY") or "").strip()
    worker_prv = (os.getenv("WORKER_VAPID_PRIVATE_KEY") or "").strip()
    server_pub = (os.getenv("VAPID_PUBLIC_KEY") or "").strip()
    server_prv = (os.getenv("VAPID_PRIVATE_KEY") or "").strip()

    if worker_pub and worker_prv:
        pub, prv = worker_pub, worker_prv
    else:
        # Prefer server pair for local pywebpush; if only public is needed (client),
        # other parts of the code can still safely use pub even when prv is empty.
        pub, prv = server_pub, server_prv
        # In remote-worker mode it's still valid to expose WORKER_VAPID_PUBLIC_KEY
        # as the subscription key even if server_prv is missing.
        if worker_pub and not pub:
            pub = worker_pub
    try:
        import json as _json  # defer import
        blob = None
        if pub.startswith("{") and '"publicKey"' in pub:
            blob = pub
        elif prv.startswith("{") and '"privateKey"' in prv:
            blob = prv
        if blob:
            data = _json.loads(blob)
            pub = str(data.get("publicKey", pub) or pub).strip()
            prv = str(data.get("privateKey", prv) or prv).strip()
    except Exception:
        pass
    # strip wrapping quotes if any
    try:
        if pub.startswith('"') and pub.endswith('"') and len(pub) > 2:
            pub = pub[1:-1]
    except Exception:
        pass
    try:
        if prv.startswith('"') and prv.endswith('"') and len(prv) > 2:
            prv = prv[1:-1]
    except Exception:
        pass
    return pub, prv


def _remote_delivery_cfg() -> dict[str, object]:
    """Read remote delivery configuration from environment.

    Returns dict with keys: enabled (bool), url (str), token (str), timeout (float).
    """
    try:
        enabled = (os.getenv("PUSH_REMOTE_DELIVERY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"})
        url = (os.getenv("PUSH_DELIVERY_URL") or "").strip()
        token = (os.getenv("PUSH_DELIVERY_TOKEN") or "").strip()
        timeout_s = float(os.getenv("PUSH_DELIVERY_TIMEOUT_SECONDS", "3") or "3")
        if enabled and (not url or not token):
            # Missing essentials disables remote path safely
            enabled = False
        return {"enabled": enabled, "url": url, "token": token, "timeout": timeout_s}
    except Exception:
        return {"enabled": False, "url": "", "token": "", "timeout": 3.0}


def _hash_endpoint(ep: str) -> str:
    try:
        return hashlib.sha256((ep or "").encode("utf-8")).hexdigest()[:12]
    except Exception:
        return ""


def _post_to_worker(
    subscription: dict,
    payload: dict,
    *,
    content_encoding: str = "aes128gcm",
    idempotency_key: str = "",
    ttl: Optional[int] = None,
    urgency: Optional[str] = None,
) -> tuple[bool, int, str]:
    """POST to external push worker. Returns (ok, status, error)."""
    try:
        import requests  # type: ignore
        import json as _json
    except Exception:
        return False, 0, "requests_not_available"
    cfg = _remote_delivery_cfg()
    if not bool(cfg.get("enabled")):
        return False, 0, "remote_disabled"
    url = str(cfg.get("url") or "").rstrip("/") + "/send"
    timeout_s = float(cfg.get("timeout") or 3.0)
    token = str(cfg.get("token") or "")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    options: dict[str, object] = {"contentEncoding": content_encoding}
    if ttl and ttl > 0:
        options["ttl"] = int(ttl)
    if urgency:
        options["urgency"] = urgency
    body = {"subscription": subscription, "payload": payload, "options": options}
    try:
        r = requests.post(url, data=_json.dumps(body, ensure_ascii=False), headers=headers, timeout=timeout_s)
        # Worker returns 200 with ok:true/false for known cases; 5xx on internal errors
        status = int(getattr(r, "status_code", 0) or 0)
        try:
            j = r.json() if hasattr(r, "json") else {}
        except Exception:
            j = {}
        if status >= 500 or status == 0:
            return False, status or 0, "worker_5xx"
        if isinstance(j, dict) and j.get("ok") is True:
            return True, 200, ""
        if isinstance(j, dict) and j.get("ok") is False:
            code = int(j.get("status") or 0)
            return False, code or status or 200, str(j.get("error") or "worker_error")
        # Fallback: treat non-JSON 2xx as failure
        return False, status or 200, "invalid_worker_response"
    except Exception as e:
        # Timeout / TLS / network
        try:
            _ = str(e)
        except Exception:
            _ = ""
        return False, 0, "worker_timeout"


@push_bp.route("/public-key", methods=["GET"])
def get_public_key():
    key, _ = _coerce_vapid_pair()
    if not key:
        # Return ok with empty key to allow client to show CTA but fail gracefully
        return jsonify({"ok": True, "vapidPublicKey": ""}), 200
    return jsonify({"ok": True, "vapidPublicKey": key}), 200


def _b64url_decode(s: str) -> bytes:
    try:
        import base64 as _b64
        s = (s or "").strip()
        pad = "=" * (-len(s) % 4)
        return _b64.urlsafe_b64decode(s + pad)
    except Exception:
        return b""


def _vapid_private_to_pem(vapid_private_key: str) -> str | None:
    """Convert base64url raw P-256 private key (32B) to PEM for compatibility.

    Prefer TraditionalOpenSSL (EC PRIVATE KEY) and fall back to PKCS8 if needed.
    """
    try:
        raw = _b64url_decode(vapid_private_key)
        if not raw or len(raw) != 32:
            return None
        from cryptography.hazmat.primitives.asymmetric import ec  # type: ignore
        from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat  # type: ignore

        num = int.from_bytes(raw, "big")
        key = ec.derive_private_key(num, ec.SECP256R1())
        # Prefer TraditionalOpenSSL (EC PRIVATE KEY) as some libs expect this format
        try:
            pem = key.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
        except Exception:
            pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        try:
            return pem.decode("utf-8")
        except Exception:
            return pem.decode(errors="ignore")
    except Exception:
        return None


def _vapid_key_candidates(vapid_private_key: str) -> list[str]:
    """Return candidate key encodings to try with pywebpush.

    Prefer PEM (EC PRIVATE KEY) when derivable; fall back to raw base64url.
    """
    out: list[str] = []
    try:
        pem = _vapid_private_to_pem(vapid_private_key)
        if pem:
            out.append(pem)
    except Exception:
        pass
    out.append(vapid_private_key)
    # de-dup while preserving order
    seen = set()
    uniq: list[str] = []
    for k in out:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return uniq
@push_bp.route("/diagnose", methods=["GET"])
def diagnose_connectivity():
    """Quick connectivity diagnostics to common Web Push endpoints.

    Returns HTTP status codes or error strings to help identify egress/TLS issues
    (for example on hosting platforms that block outbound traffic or miss CAs).
    """
    try:
        import requests  # type: ignore
    except Exception:
        return jsonify({
            "ok": False,
            "error": "requests_not_available"
        }), 500

    targets = [
        {"name": "google_fcm_root", "url": "https://fcm.googleapis.com"},
        {"name": "google_fcm_send", "url": "https://fcm.googleapis.com/fcm/send"},
        {"name": "mozilla_updates_root", "url": "https://updates.push.services.mozilla.com"},
        {"name": "mozilla_wpush_v2", "url": "https://updates.push.services.mozilla.com/wpush/v2"},
    ]
    results: list[dict[str, object]] = []
    for t in targets:
        name = str(t.get("name"))
        url = str(t.get("url"))
        rec: dict[str, object] = {"name": name, "url": url, "ok": False, "status": 0, "error": ""}
        try:
            # HEAD may be rejected by some providers; try GET with no redirects
            r = None
            try:
                r = requests.head(url, timeout=5, allow_redirects=False)
            except Exception:
                r = None
            if r is None:
                r = requests.get(url, timeout=7, allow_redirects=False)
            rec["status"] = int(getattr(r, "status_code", 0) or 0)
            # Consider any HTTP response as connectivity OK (even 404/405)
            rec["ok"] = bool(getattr(r, "status_code", 0))
        except Exception as e:
            try:
                rec["error"] = str(e)
            except Exception:
                rec["error"] = "unknown_error"
        results.append(rec)
    any_ok = any(bool(x.get("ok")) for x in results)
    return jsonify({"ok": any_ok, "results": results}), 200 if any_ok else 502


@push_bp.route("/subscribe", methods=["POST"])
@require_auth
def subscribe():
    try:
        _ensure_indexes()
        user_id = _session_user_id()
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"ok": False, "error": "Invalid subscription"}), 400
        # Normalize minimal fields we care about
        endpoint = str((payload or {}).get("endpoint") or "").strip()
        raw_keys = (payload or {}).get("keys")
        keys = raw_keys if isinstance(raw_keys, dict) else None
        if not endpoint or keys is None:
            return jsonify({"ok": False, "error": "Invalid subscription"}), 400

        now_utc = datetime.now(timezone.utc)
        # Optional content encoding hint ("aesgcm" / "aes128gcm"). Many browsers won't send it.
        _raw_enc = (payload.get("contentEncoding") or payload.get("content_encoding") or "")
        try:
            _raw_enc = str(_raw_enc).strip().lower()
        except Exception:
            _raw_enc = ""

        set_fields = {
            "user_id": user_id,
            "endpoint": endpoint,
            "keys": {"p256dh": keys.get("p256dh", ""), "auth": keys.get("auth", "")},
            "subscription": payload,  # store full object for sending
            "updated_at": now_utc,
        }
        if _raw_enc in ("aesgcm", "aes128gcm"):
            set_fields["content_encoding"] = _raw_enc
        db = get_db()
        # Upsert per (user, endpoint), normalizing user_id across int/str using variants.
        #
        # IMPORTANT: do not set the same field in $set and $setOnInsert (Mongo raises a conflict).
        try:
            db.push_subscriptions.update_one(
                {"user_id": {"$in": _user_id_variants(user_id)}, "endpoint": endpoint},
                {"$set": set_fields, "$setOnInsert": {"created_at": now_utc}},
                upsert=True,
            )
        except Exception:
            # Do not leak endpoint itself (PII-ish). Log a stable hash + metadata.
            try:
                logging.exception(
                    "push_api.subscribe failed to persist subscription",
                    extra={
                        "user_id": str(user_id),
                        "user_id_type": type(user_id).__name__,
                        "endpoint_hash": _hash_endpoint(endpoint),
                        "endpoint_len": len(endpoint or ""),
                        "has_p256dh": bool(keys.get("p256dh")),
                        "has_auth": bool(keys.get("auth")),
                        "content_encoding": (set_fields.get("content_encoding") or ""),
                    },
                )
            except Exception:
                pass
            return jsonify({"ok": False, "error": "Failed to save subscription"}), 500
        try:
            from observability import emit_event  # type: ignore

            emit_event("push_subscribed", severity="info", user_id=str(user_id))
        except Exception:
            pass
        return jsonify({"ok": True}), 201
    except Exception:
        return jsonify({"ok": False, "error": "Failed to save subscription"}), 500


@push_bp.route("/subscribe", methods=["DELETE"])
@require_auth
def unsubscribe():
    try:
        user_id = _session_user_id()
        payload = request.get_json(silent=True) or {}
        endpoint = str((payload or {}).get("endpoint") or request.args.get("endpoint") or "").strip()
        if not endpoint:
            return jsonify({"ok": False, "error": "endpoint required"}), 400
        db = get_db()
        db.push_subscriptions.delete_many({"user_id": {"$in": _user_id_variants(user_id)}, "endpoint": endpoint})
        try:
            from observability import emit_event  # type: ignore

            emit_event("push_unsubscribed", severity="info", user_id=str(user_id))
        except Exception:
            pass
        return jsonify({"ok": True}), 200
    except Exception:
        return jsonify({"ok": False, "error": "Failed to unsubscribe"}), 500


# --- Background sender (opt-in via env) ---
_sender_started = False
_sender_lock_fh = None  # type: ignore

# Legacy scan (documents without needs_push) is only required during migration windows.
# After backfilling needs_push for all documents, continuing to run the legacy branch
# can cause a COLLSCAN and produce 2 slow-query alerts per loop.
_legacy_scan_cached_has_missing: Optional[bool] = None
_legacy_scan_cached_at_ts: float = 0.0


def start_sender_if_enabled() -> None:
    global _sender_started
    if _sender_started:
        return
    enabled = (os.getenv("PUSH_NOTIFICATIONS_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"})
    if not enabled:
        return
    # Ensure only one sender loop runs across multiple Gunicorn workers/processes.
    # Using an OS-level flock means the lock is released automatically on process exit/crash.
    global _sender_lock_fh
    try:
        import fcntl
        lock_path = os.getenv("PUSH_SENDER_LOCK_FILE") or "/tmp/codebot-push-sender.lock"
        _sender_lock_fh = open(lock_path, "a+")
        try:
            fcntl.flock(_sender_lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            # Another process owns the sender lock; do not start a duplicate loop.
            return
    except Exception:
        # Fail-open: if locking isn't available, fall back to per-process behavior.
        pass
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

    Idempotency: send once per reminder schedule using the needs_push field.
    When a push succeeds, needs_push is set to False.
    When a reminder is rescheduled (snooze), needs_push is reset to True.

    Backward compatibility: documents without needs_push field use the old
    last_push_success_at logic to avoid duplicate sends on deployment.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    # IMPORTANT: do NOT use a single $or query here.
    # A partial index (ack_at=None, needs_push=True) is only usable when the query
    # *guarantees* needs_push=True. With a top-level $or (legacy branch), MongoDB
    # tends to fall back to COLLSCAN under load.
    #
    # Strategy:
    # 1) Query "new" documents (needs_push=True) — hits the partial index.
    # 2) If we still need items, query legacy documents without needs_push.
    base_filter = {
        "ack_at": None,
        "status": {"$in": ["pending", "snoozed"]},
        "remind_at": {"$lte": now},
    }
    total_needed = max_users * max_per_user
    # We still oversample to compensate for claim collisions / missing subscriptions, etc.
    raw_limit = max(10, int(total_needed * 3))
    # Keep projection minimal to reduce memory/network usage.
    projection = {
        "_id": 1,
        "user_id": 1,
        "note_id": 1,
        "file_id": 1,
        "remind_at": 1,
        "last_push_success_at": 1,
    }

    raw_due: list = []
    # 1) New documents (fast path, uses partial index)
    try:
        new_filter = dict(base_filter)
        new_filter["needs_push"] = True
        raw_due = list(db.note_reminders.find(new_filter, projection).sort("remind_at", 1).limit(raw_limit))
    except Exception:
        raw_due = []

    due: list[dict] = [r for r in raw_due if isinstance(r, dict)]

    # 2) Legacy documents (best-effort, limited)
    if len(due) < raw_limit:
        # Auto-disable legacy scan once the collection is migrated (no documents missing needs_push).
        # Cache the presence check so we don't add another frequent query.
        legacy_scan_enabled = True
        try:
            raw = (os.getenv("PUSH_LEGACY_SCAN_ENABLED") or "").strip().lower()
            if raw in {"0", "false", "no", "off"}:
                legacy_scan_enabled = False
        except Exception:
            pass

        if legacy_scan_enabled:
            global _legacy_scan_cached_has_missing, _legacy_scan_cached_at_ts
            try:
                import time
                ttl = max(30, int(os.getenv("PUSH_LEGACY_SCAN_CHECK_TTL_SECONDS", "600") or "600"))
                now_ts = float(time.time())
                if _legacy_scan_cached_has_missing is None or (now_ts - float(_legacy_scan_cached_at_ts or 0.0)) > float(ttl):
                    # Use find_one to minimize work; if no doc exists, migration is done.
                    missing = db.note_reminders.find_one({"needs_push": {"$exists": False}}, {"_id": 1})
                    _legacy_scan_cached_has_missing = bool(missing)
                    _legacy_scan_cached_at_ts = now_ts
                if _legacy_scan_cached_has_missing is False:
                    legacy_scan_enabled = False
            except Exception:
                # Fail-open: if we can't check, keep legacy scan enabled for safety.
                legacy_scan_enabled = True

        if not legacy_scan_enabled:
            # No legacy docs -> skip legacy query to avoid COLLSCAN and duplicate alerts.
            pass
        else:
            try:
                legacy_limit = max(1, raw_limit - len(due))
                legacy_filter = dict(base_filter)
                legacy_filter["needs_push"] = {"$exists": False}
                legacy_filter["$or"] = [
                    {"last_push_success_at": {"$exists": False}},
                    {"last_push_success_at": None},
                    {
                        "$and": [
                            {"last_push_success_at": {"$type": "date"}},
                            {"$expr": {"$gt": ["$remind_at", "$last_push_success_at"]}},
                        ]
                    },
                ]
                legacy_raw = list(
                    db.note_reminders.find(legacy_filter, projection).sort("remind_at", 1).limit(legacy_limit)
                )
                # Merge & de-dup by _id
                seen = {str(d.get("_id")) for d in due if d.get("_id") is not None}
                for r in legacy_raw:
                    if not isinstance(r, dict):
                        continue
                    rid = r.get("_id")
                    if rid is None:
                        continue
                    s = str(rid)
                    if s in seen:
                        continue
                    seen.add(s)
                    due.append(r)
            except Exception:
                pass

    # Keep global order by remind_at after merging new+legacy lists.
    # Otherwise, early legacy reminders can be pushed after later "new" reminders.
    def _due_sort_key(d: dict):
        ra = d.get("remind_at")
        if isinstance(ra, datetime):
            try:
                if ra.tzinfo is None:
                    ra = ra.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        else:
            try:
                ra = datetime.max.replace(tzinfo=timezone.utc)
            except Exception:
                ra = datetime.max
        return (ra, str(d.get("_id") or ""))

    try:
        due.sort(key=_due_sort_key)
    except Exception:
        pass

    due = due[:total_needed]
    if not due:
        return
    # Group by user (support string/int user_id transparently)
    by_user: Dict[str, list] = {}
    for r in due:
        uid = r.get("user_id")
        if uid is None:
            continue
        key = str(uid)
        by_user.setdefault(key, []).append(r)
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


def _send_for_user(user_id: int | str, reminders: list[dict]) -> None:
    db = get_db()
    subs = list(db.push_subscriptions.find({"user_id": {"$in": _user_id_variants(user_id)}}))
    if not subs:
        # Telemetry: no subscriptions for user
        try:
            from observability import emit_event  # type: ignore

            emit_event("push_send_no_subscriptions", severity="info", user_id=str(user_id))
        except Exception:
            pass
        return
    # Decide delivery path
    remote_cfg = _remote_delivery_cfg()
    use_remote = bool(remote_cfg.get("enabled"))
    if not use_remote:
        # Local pywebpush path requires private key
        _, vapid_private = _coerce_vapid_pair()
        vapid_email = (os.getenv("VAPID_SUB_EMAIL") or os.getenv("SUPPORT_EMAIL") or "").strip()
        if not vapid_private or not subs:
            try:
                from observability import emit_event  # type: ignore

                emit_event("push_send_missing_vapid_private", severity="warning", user_id=int(user_id))
            except Exception:
                pass
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
        title_text = "🔔 יש פתק ממתין"
        body_text = _coerce_preview(db, r)
        note_id_str = str(r.get("note_id") or "")
        file_id_str = str(r.get("file_id") or "")

        # Payload format: notification object at top level (FCM standard)
        # data object for custom handling in SW
        payload = {
            "notification": {
                "title": title_text,
                "body": body_text,
                "icon": "/static/icons/app-icon-512.png",
                "badge": "/static/icons/app-icon-512.png",
                "tag": f"reminder-{note_id_str}" if note_id_str else "reminder",
                "silent": False,
                "requireInteraction": False,
                "actions": [
                    {"action": "open_note", "title": "פתח פתק"},
                    {"action": "snooze_10", "title": "דחה 10 דק׳"},
                    {"action": "snooze_60", "title": "דחה שעה"},
                    {"action": "snooze_1440", "title": "דחה 24 שעות"},
                ],
            },
            "data": {
                "type": "reminder",
                "note_id": note_id_str,
                "file_id": file_id_str,
                "title": title_text,
                "body": body_text,
            },
        }
        success_any = False
        # Telemetry: attempt send for this reminder batch
        try:
            from observability import emit_event  # type: ignore

            emit_event(
                "push_send_attempt",
                severity="info",
                user_id=str(user_id),
                reminder_id=str(r.get("_id") or ""),
                subs=len(subs),
            )
        except Exception:
            pass

        for sub in subs:
            ep = str(sub.get("endpoint") or "")
            if ep and ep in endpoints_to_delete:
                continue
            info = sub.get("subscription") or {"endpoint": ep, "keys": sub.get("keys")}
            content_enc = (
                sub.get("content_encoding")
                or sub.get("contentEncoding")
                or (info.get("contentEncoding") if isinstance(info, dict) else None)
            )
            try:
                ce = str(content_enc).strip().lower() if content_enc is not None else ""
            except Exception:
                ce = ""
            if ce not in ("aesgcm", "aes128gcm"):
                ce = "aes128gcm"

            if use_remote:
                ok, status_code, _err = _post_to_worker(
                    info if isinstance(info, dict) else {},
                    payload,
                    content_encoding=ce,
                    idempotency_key=str(r.get("_id") or ""),
                    ttl=_PUSH_DELIVERY_TTL_SECONDS,
                    urgency=_PUSH_DELIVERY_URGENCY,
                )
                if ok:
                    success_any = True
                else:
                    if status_code in (404, 410) and ep:
                        endpoints_to_delete.add(ep)
                    try:
                        from observability import emit_event  # type: ignore

                        emit_event(
                            "push_send_error",
                            severity="warning",
                            user_id=str(user_id),
                            endpoint=str(ep or ""),
                            status_code=int(status_code or 0),
                        )
                    except Exception:
                        pass
                continue

            # Local pywebpush path
            try:
                delivered = False
                last_err: Exception | None = None
                urgency_headers = {"Urgency": _PUSH_DELIVERY_URGENCY} if _PUSH_DELIVERY_URGENCY else None
                for key_variant in _vapid_key_candidates(vapid_private):
                    try:
                        webpush(
                            subscription_info=info,
                            data=json.dumps(payload, ensure_ascii=False),
                            vapid_private_key=key_variant,
                            vapid_claims={"sub": (f"mailto:{vapid_email}" if vapid_email and not vapid_email.startswith("mailto:") else vapid_email) or "mailto:support@example.com"},
                            content_encoding=ce,
                            ttl=_PUSH_DELIVERY_TTL_SECONDS,
                            headers=urgency_headers,
                        )
                        delivered = True
                        last_err = None
                        break
                    except Exception as inner_ex:
                        last_err = inner_ex
                        continue
                if not delivered and last_err is not None:
                    raise last_err
                if delivered:
                    success_any = True
            except Exception as ex:
                try:
                    from pywebpush import WebPushException  # type: ignore

                    if isinstance(ex, WebPushException):
                        status = getattr(getattr(ex, "response", None), "status_code", 0)
                        if status in (404, 410):
                            if ep:
                                endpoints_to_delete.add(ep)
                        try:
                            from observability import emit_event  # type: ignore

                            emit_event(
                                "push_send_error",
                                severity="warning",
                                user_id=str(user_id),
                                endpoint=str(ep or ""),
                                status_code=int(status or 0),
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
                continue
        if success_any:
            try:
                # Race condition protection: only mark as sent if remind_at hasn't changed
                # (i.e., user didn't snooze during the push). If snoozed, the new remind_at
                # means we should NOT clear needs_push - the snoozed reminder needs its push.
                original_remind_at = r.get("remind_at")
                db.note_reminders.update_one(
                    {"_id": r.get("_id"), "remind_at": original_remind_at},
                    {"$set": {
                        "last_push_success_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                        "needs_push": False,
                    }},
                )
            except Exception:
                pass

    # After processing all reminders for this user, remove dead endpoints once
    if endpoints_to_delete:
        try:
            db.push_subscriptions.delete_many({"user_id": {"$in": _user_id_variants(user_id)}, "endpoint": {"$in": list(endpoints_to_delete)}})
            # Telemetry: cleaned dead endpoints
            try:
                from observability import emit_event  # type: ignore

                emit_event(
                    "push_deleted_dead_endpoints",
                    severity="info",
                    user_id=str(user_id),
                    deleted_count=int(len(endpoints_to_delete)),
                )
            except Exception:
                pass
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


@push_bp.route("/test", methods=["POST"])
@require_auth
def test_push():
    """Send a quick test push to current user's subscriptions.

    Returns JSON with send results to help debugging in environments.
    """
    try:
        user_id = _session_user_id()
        db = get_db()
        subs = list(db.push_subscriptions.find({"user_id": {"$in": _user_id_variants(user_id)}}))
        if not subs:
            return jsonify({"ok": False, "error": "no_subscriptions"}), 400

        runtime_versions: dict[str, str] = {}
        try:
            import sys

            runtime_versions["python"] = str(sys.version.split()[0])
        except Exception:
            pass

        def _dist_version(*names: str) -> str:
            try:
                from importlib import metadata  # py3.8+

                for n in names:
                    try:
                        v = metadata.version(n)
                        if v:
                            return str(v)
                    except metadata.PackageNotFoundError:
                        continue
                    except Exception:
                        continue
            except Exception:
                pass
            return "unknown"

        runtime_versions["cryptography"] = _dist_version("cryptography")
        runtime_versions["py_vapid"] = _dist_version("py-vapid", "py_vapid")
        runtime_versions["pywebpush"] = _dist_version("pywebpush")

        remote_cfg = _remote_delivery_cfg()
        use_remote = bool(remote_cfg.get("enabled"))
        if not use_remote:
            _, vapid_private = _coerce_vapid_pair()
            vapid_email = (os.getenv("VAPID_SUB_EMAIL") or os.getenv("SUPPORT_EMAIL") or "").strip()
            if not vapid_private:
                return jsonify({"ok": False, "error": "missing_vapid_private_key"}), 500
            try:
                from pywebpush import webpush, WebPushException  # type: ignore
                import json
            except Exception:
                return jsonify({"ok": False, "error": "pywebpush_not_available"}), 500

        title_text = "🔔 בדיקת פוש"
        body_text = "זוהי הודעת בדיקה"
        
        # Payload format: notification object at top level (FCM standard)
        # data object for custom handling in SW
        payload = {
            "notification": {
                "title": title_text,
                "body": body_text,
                "icon": "/static/icons/app-icon-512.png",
                "badge": "/static/icons/app-icon-512.png",
                "tag": "push-test",
                "silent": False,
                "requireInteraction": False,
            },
            "data": {
                "type": "test",
                "title": title_text,
                "body": body_text,
            },
        }
        sent = 0
        errors: list[dict[str, Any]] = []
        for sub in subs:
            ep = str(sub.get("endpoint") or "")
            info = sub.get("subscription") or {"endpoint": ep, "keys": sub.get("keys")}
            content_enc = (
                sub.get("content_encoding")
                or sub.get("contentEncoding")
                or (info.get("contentEncoding") if isinstance(info, dict) else None)
            )
            try:
                ce = str(content_enc).strip().lower() if content_enc is not None else ""
            except Exception:
                ce = ""
            if ce not in ("aesgcm", "aes128gcm"):
                ce = "aes128gcm"

            if use_remote:
                ok, status_code, err = _post_to_worker(
                    info if isinstance(info, dict) else {},
                    payload,
                    content_encoding=ce,
                    ttl=_PUSH_TEST_TTL_SECONDS,
                    urgency=_PUSH_DELIVERY_URGENCY,
                )
                if ok:
                    sent += 1
                else:
                    # Worker returned ok: false - log the exact error for debugging
                    errors.append({"endpoint": ep, "status": int(status_code or 0), "error": str(err or "")})
                    try:
                        from observability import emit_event  # type: ignore
                        emit_event(
                            "push_test_worker_error",
                            severity="warning",
                            user_id=str(user_id),
                            endpoint_hash=_hash_endpoint(ep),
                            status_code=int(status_code or 0),
                            error=str(err or ""),
                        )
                    except Exception:
                        pass
                continue

            # Local pywebpush path
            try:
                delivered = False
                last_err: Exception | None = None
                urgency_headers = {"Urgency": _PUSH_DELIVERY_URGENCY} if _PUSH_DELIVERY_URGENCY else None
                for key_variant in _vapid_key_candidates(vapid_private):
                    try:
                        webpush(
                            subscription_info=info,
                            data=json.dumps(payload, ensure_ascii=False),
                            vapid_private_key=key_variant,
                            vapid_claims={"sub": (f"mailto:{vapid_email}" if vapid_email and not vapid_email.startswith("mailto:") else vapid_email) or "mailto:support@example.com"},
                            content_encoding=ce,
                            ttl=_PUSH_TEST_TTL_SECONDS,
                            headers=urgency_headers,
                        )
                        delivered = True
                        last_err = None
                        break
                    except Exception as inner_ex:
                        last_err = inner_ex
                        continue
                if not delivered and last_err is not None:
                    raise last_err
                if delivered:
                    sent += 1
            except Exception as ex:
                status = 0
                try:
                    from pywebpush import WebPushException  # type: ignore

                    if isinstance(ex, WebPushException):
                        status = getattr(getattr(ex, "response", None), "status_code", 0) or 0
                except Exception:
                    pass
                err_str = ""
                try:
                    err_str = str(ex)
                except Exception:
                    err_str = ""
                errors.append({"endpoint": ep, "status": int(status or 0), "error": err_str})
        try:
            from observability import emit_event  # type: ignore

            emit_event(
                "push_test_result",
                severity=("info" if sent else "warning"),
                user_id=str(user_id),
                sent=int(sent),
                errors=len(errors),
            )
        except Exception:
            pass
        # Aggregate error codes for easier client display
        code_counts: dict[int, int] = {}
        for e in errors:
            c = int(e.get("status") or 0)
            code_counts[c] = code_counts.get(c, 0) + 1
        return jsonify({"ok": True, "sent": sent, "errors": errors, "codes": code_counts, "runtime": runtime_versions}), 200
    except Exception as ex:
        # Log full exception server-side; do not leak details to client
        try:
            import logging

            logging.exception("Unhandled exception in push_api.test_push")
        except Exception:
            pass
        return jsonify({"ok": False, "error": "internal_error"}), 500


@push_bp.route("/subscriptions", methods=["GET"])
@require_auth
def list_subscriptions():
    """List all push subscriptions for the current user.
    
    Helps debug stale subscription issues by showing all registered endpoints.
    """
    try:
        user_id = _session_user_id()
        db = get_db()
        subs = list(db.push_subscriptions.find({"user_id": {"$in": _user_id_variants(user_id)}}))
        
        # Build safe response without exposing full keys
        result = []
        for s in subs:
            ep = str(s.get("endpoint") or "")
            created = s.get("created_at")
            updated = s.get("updated_at")
            
            # Identify push service provider from endpoint URL
            provider = "unknown"
            if "fcm.googleapis.com" in ep:
                provider = "fcm_chrome"
            elif "updates.push.services.mozilla.com" in ep:
                provider = "mozilla_firefox"
            elif "wns.windows.com" in ep or "notify.windows.com" in ep:
                provider = "wns_edge"
            elif "push.apple.com" in ep:
                provider = "apns_safari"
            
            result.append({
                "endpoint_hash": _hash_endpoint(ep),
                "endpoint_preview": ep[:60] + "..." if len(ep) > 60 else ep,
                "provider": provider,
                "created_at": created.isoformat() if created else None,
                "updated_at": updated.isoformat() if updated else None,
                "content_encoding": s.get("content_encoding") or "aes128gcm",
            })
        
        return jsonify({
            "ok": True,
            "count": len(result),
            "subscriptions": result,
        }), 200
    except Exception:
        return jsonify({"ok": False, "error": "Failed to list subscriptions"}), 500


@push_bp.route("/subscriptions/cleanup", methods=["POST"])
@require_auth
def cleanup_subscriptions():
    """Remove all subscriptions for current user older than specified days.
    
    Body: { "older_than_days": 30 } (default: 30)
    This helps clean up stale subscriptions from old devices/browsers.
    """
    try:
        user_id = _session_user_id()
        db = get_db()
        payload = request.get_json(silent=True) or {}
        raw_days = payload.get("older_than_days")
        # Handle explicit 0 correctly - don't treat it as missing
        days = int(raw_days) if raw_days is not None else 30
        if days < 1:
            days = 1
        
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Find subscriptions to delete
        filt = {
            "user_id": {"$in": _user_id_variants(user_id)},
            "$or": [
                {"updated_at": {"$lt": cutoff}},
                {"updated_at": {"$exists": False}, "created_at": {"$lt": cutoff}},
            ]
        }
        count_before = db.push_subscriptions.count_documents({"user_id": {"$in": _user_id_variants(user_id)}})
        result = db.push_subscriptions.delete_many(filt)
        deleted = result.deleted_count if hasattr(result, "deleted_count") else 0
        count_after = db.push_subscriptions.count_documents({"user_id": {"$in": _user_id_variants(user_id)}})
        
        try:
            from observability import emit_event
            emit_event(
                "push_subscriptions_cleanup",
                severity="info",
                user_id=str(user_id),
                deleted=deleted,
                remaining=count_after,
            )
        except Exception:
            pass
        
        return jsonify({
            "ok": True,
            "deleted": deleted,
            "remaining": count_after,
            "cutoff_date": cutoff.isoformat(),
        }), 200
    except Exception:
        return jsonify({"ok": False, "error": "Cleanup failed"}), 500


@push_bp.route("/subscriptions/delete-all", methods=["DELETE"])
@require_auth
def delete_all_subscriptions():
    """Delete ALL push subscriptions for current user.
    
    Use this to completely reset and re-register fresh.
    """
    try:
        user_id = _session_user_id()
        db = get_db()
        
        result = db.push_subscriptions.delete_many({"user_id": {"$in": _user_id_variants(user_id)}})
        deleted = result.deleted_count if hasattr(result, "deleted_count") else 0
        
        try:
            from observability import emit_event
            emit_event(
                "push_subscriptions_delete_all",
                severity="info",
                user_id=str(user_id),
                deleted=deleted,
            )
        except Exception:
            pass
        
        return jsonify({
            "ok": True,
            "deleted": deleted,
            "message": "All subscriptions deleted. Please re-enable push notifications to create a fresh subscription.",
        }), 200
    except Exception:
        return jsonify({"ok": False, "error": "Delete failed"}), 500


@push_bp.route("/sw-report", methods=["POST"])
def sw_report():
    """Receive diagnostic reports from Service Worker.
    
    This endpoint allows the SW to "phone home" when it receives a push,
    so we can see in server logs whether the SW is getting the messages.
    No auth required - we want this to work even if session expired.
    """
    try:
        payload = request.get_json(silent=True) or {}
        event_type = str(payload.get("event") or "unknown")
        status = str(payload.get("status") or "unknown")
        error_msg = str(payload.get("error") or "")
        raw_data = str(payload.get("raw_data") or "")[:500]  # Truncate for safety
        timestamp = str(payload.get("timestamp") or "")
        endpoint_hash = str(payload.get("endpoint_hash") or "").strip().lower()
        if endpoint_hash and (len(endpoint_hash) != 12 or any(c not in "0123456789abcdef" for c in endpoint_hash)):
            endpoint_hash = ""

        now_iso = datetime.now(timezone.utc).isoformat()
        record: dict[str, Any] = {
            "ts": now_iso,
            "client_timestamp": timestamp,
            "event": event_type,
            "status": status,
            "error": (error_msg[:240] if error_msg else ""),
            "raw_data_preview": (raw_data[:160] if raw_data else ""),
        }
        if endpoint_hash:
            record["endpoint_hash"] = endpoint_hash

        # Try to attach user_id if session cookie exists (SW fetch is same-origin).
        try:
            uid = session.get("user_id")
        except Exception:
            uid = None
        try:
            if uid is not None and uid != "":
                record["user_id"] = uid
        except Exception:
            pass

        # Store in-memory (per worker) + persist to DB (cross-worker).
        try:
            _append_sw_report(record)
        except Exception:
            pass
        try:
            _persist_sw_report_to_db(
                {
                    "ts": datetime.now(timezone.utc),
                    "client_timestamp": timestamp,
                    "event": event_type,
                    "status": status,
                    "error": (error_msg[:240] if error_msg else ""),
                    "raw_data_preview": (raw_data[:160] if raw_data else ""),
                    "user_id": uid,
                    "endpoint_hash": endpoint_hash or None,
                }
            )
        except Exception:
            pass
        
        # Log with structlog if available, else standard logging
        try:
            from observability import emit_event
            emit_event(
                "sw_push_report",
                severity="info",
                event=event_type,
                status=status,
                error=error_msg,
                raw_data_preview=raw_data[:100] if raw_data else "",
                client_timestamp=timestamp,
            )
        except Exception:
            try:
                import structlog
                log = structlog.get_logger()
                log.info(
                    "sw_push_report",
                    event=event_type,
                    status=status,
                    error=error_msg,
                    raw_data_preview=raw_data[:100] if raw_data else "",
                    client_timestamp=timestamp,
                )
            except Exception:
                import logging
                logging.info(f"[SW-REPORT] event={event_type} status={status} error={error_msg}")
        
        return jsonify({"ok": True}), 200
    except Exception:
        return jsonify({"ok": True}), 200  # Always return OK to not break SW


@push_bp.route("/sw-reports", methods=["GET"])
@require_auth
def list_sw_reports():
    """Return last SW diagnostic reports for the current session (debug aid)."""
    try:
        user_id = _session_user_id()
        req_hash = str(request.args.get("endpoint_hash") or "").strip().lower()
        if req_hash and (len(req_hash) != 12 or any(c not in "0123456789abcdef" for c in req_hash)):
            req_hash = ""
        # Prefer DB (works across multiple Gunicorn workers/processes)
        try:
            db = get_db()
            coll = db.sw_push_reports
            variants = _user_id_variants(user_id)
            filt: dict[str, Any]
            if req_hash:
                filt = {"$or": [{"endpoint_hash": req_hash}, {"user_id": {"$in": variants}}]}
            else:
                filt = {"user_id": {"$in": variants}}
            docs = list(coll.find(filt).sort("ts", -1).limit(50))
            out: list[dict[str, Any]] = []
            for d in docs:
                if not isinstance(d, dict):
                    continue
                ts = d.get("ts")
                try:
                    ts_s = ts.isoformat() if isinstance(ts, datetime) else str(ts or "")
                except Exception:
                    ts_s = ""
                out.append(
                    {
                        "ts": ts_s,
                        "client_timestamp": str(d.get("client_timestamp") or ""),
                        "event": str(d.get("event") or ""),
                        "status": str(d.get("status") or ""),
                        "error": str(d.get("error") or ""),
                        "raw_data_preview": str(d.get("raw_data_preview") or ""),
                        "endpoint_hash": str(d.get("endpoint_hash") or ""),
                    }
                )
            return jsonify({"ok": True, "count": len(out), "reports": out}), 200
        except Exception:
            # Fallback to in-memory (single-worker environments)
            data = list(_SW_REPORTS)[-50:]
            variants = _user_id_variants(user_id)
            out_mem: list[dict[str, Any]] = []
            for r in data:
                if not isinstance(r, dict):
                    continue
                r_uid = r.get("user_id")
                r_hash = str(r.get("endpoint_hash") or "")
                # Match DB behavior:
                # - no req_hash: user_id only
                # - req_hash: endpoint_hash OR user_id
                try:
                    uid_match = r_uid in variants
                except Exception:
                    uid_match = False
                hash_match = bool(req_hash and r_hash == req_hash)
                if req_hash:
                    if not (hash_match or uid_match):
                        continue
                else:
                    if not uid_match:
                        continue
                out_mem.append(r)
            data = out_mem
            return jsonify({"ok": True, "count": len(data), "reports": data}), 200
    except Exception:
        return jsonify({"ok": False, "error": "Failed to load sw reports"}), 500

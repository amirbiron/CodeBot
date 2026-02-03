"""
Auth Routes - Authentication endpoints for WebApp.

This module implements auth endpoints migrated to the new layered architecture:
Route -> Facade/Container -> Service/Domain -> Repository -> DB

Issue: #2871 (Step 3 - The Great Split)

Endpoints:
- GET /login - Login page
- GET/POST /auth/telegram - Telegram widget authentication
- GET /auth/token - Token-based authentication from bot
- GET /logout - Logout
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


def _get_files_facade():
    """
    Lazy import of FilesFacade to avoid circular imports at module load time.
    """
    from src.infrastructure.composition.webapp_container import get_files_facade

    return get_files_facade()


def _get_bot_token() -> str:
    """Get BOT_TOKEN from environment."""
    return os.getenv("BOT_TOKEN", "")


def _get_bot_username_clean() -> str:
    """Get clean BOT_USERNAME (without @)."""
    return (os.getenv("BOT_USERNAME", "my_code_keeper_bot") or "").lstrip("@")


def _get_remember_cookie_name() -> str:
    """Get remember me cookie name."""
    return "remember_me"


def _verify_telegram_auth(auth_data: Dict[str, Any]) -> bool:
    """Verify data from Telegram Login Widget."""
    check_hash = auth_data.get("hash")
    if not check_hash:
        return False

    # Build data-check-string
    data_items = []
    for key, value in sorted(auth_data.items()):
        if key != "hash":
            data_items.append(f"{key}={value}")

    data_check_string = "\n".join(data_items)

    # Calculate hash
    bot_token = _get_bot_token()
    if not bot_token:
        # Refuse verification if server is misconfigured.
        # Otherwise we'd verify against a constant secret derived from an empty token.
        logger.error("BOT_TOKEN is not set; refusing Telegram auth verification")
        return False
    secret_key = hashlib.sha256(bot_token.encode()).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    # Verify hash
    if calculated_hash != check_hash:
        return False

    # Verify time (up to 1 hour from signature)
    auth_date = int(auth_data.get("auth_date", 0))
    if (time.time() - auth_date) > 3600:
        return False

    return True


def _is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    admin_ids_env = os.getenv("ADMIN_USER_IDS", "")
    admin_ids_list = admin_ids_env.split(",") if admin_ids_env else []
    admin_ids = [int(x.strip()) for x in admin_ids_list if x.strip().isdigit()]
    return user_id in admin_ids


def _is_premium(user_id: int) -> bool:
    """Check if user is premium."""
    try:
        premium_ids_env = os.getenv("PREMIUM_USER_IDS", "")
        premium_ids_list = premium_ids_env.split(",") if premium_ids_env else []
        premium_ids = [int(x.strip()) for x in premium_ids_list if x.strip().isdigit()]
        return user_id in premium_ids
    except Exception:
        return False


def _get_db_for_auth():
    """
    Get database connection for auth operations.
    Uses FilesFacade's internal db access for consistency.
    """
    facade = _get_files_facade()
    return facade.get_mongo_db()


@auth_bp.route("/login")
def login():
    """Login page."""
    return render_template("login.html", bot_username=_get_bot_username_clean())


@auth_bp.route("/auth/telegram", methods=["GET", "POST"])
def telegram_auth():
    """Handle Telegram widget authentication."""
    if request.method == "GET":
        auth_data: Any = dict(request.args)
    else:
        auth_data = request.get_json(silent=True) or {}

    if not isinstance(auth_data, dict):
        return jsonify({"error": "Invalid payload"}), 400

    if not _verify_telegram_auth(auth_data):
        return jsonify({"error": "Invalid authentication"}), 401

    # Save user data to session
    try:
        user_id = int(auth_data.get("id"))  # type: ignore[arg-type]
    except Exception:
        return jsonify({"error": "Invalid authentication"}), 401
    user_doc: Dict[str, Any] = {}

    try:
        db = _get_db_for_auth()
    except Exception:
        db = None

    now_utc = datetime.now(timezone.utc)
    if db is not None:
        try:
            users_coll = db.users if hasattr(db, "users") else db["users"]
            user_doc = users_coll.find_one({"user_id": user_id}) or {}
        except Exception:
            user_doc = {}
        try:
            users_coll = db.users if hasattr(db, "users") else db["users"]
            users_coll.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "user_id": user_id,
                        "first_name": auth_data.get("first_name", ""),
                        "last_name": auth_data.get("last_name", ""),
                        "username": auth_data.get("username", ""),
                        "photo_url": auth_data.get("photo_url", ""),
                        "updated_at": now_utc,
                    },
                    "$setOnInsert": {
                        "created_at": now_utc,
                        "has_seen_welcome_modal": False,
                    },
                },
                upsert=True,
            )
        except Exception:
            pass
        try:
            from database.collections_manager import CollectionsManager

            CollectionsManager(db).ensure_default_collections(user_id)
        except Exception:
            pass

    session["user_id"] = user_id
    session["user_data"] = {
        "id": user_id,
        "first_name": auth_data.get("first_name", ""),
        "last_name": auth_data.get("last_name", ""),
        "username": auth_data.get("username", ""),
        "photo_url": auth_data.get("photo_url", ""),
        "has_seen_welcome_modal": bool((user_doc or {}).get("has_seen_welcome_modal", False)),
        "is_admin": _is_admin(user_id),
        "is_premium": _is_premium(user_id),
    }

    # Make session permanent (30 days)
    session.permanent = True

    return redirect("/dashboard")


@auth_bp.route("/auth/token")
def token_auth():
    """Handle token-based authentication from bot."""
    token = request.args.get("token")
    user_id = request.args.get("user_id")
    bot_username = _get_bot_username_clean()

    if not token or not user_id:
        return render_template("404.html"), 404

    try:
        db = _get_db_for_auth()
        if db is None:
            return render_template(
                "login.html",
                bot_username=bot_username,
                error="שגיאה בהתחברות. אנא נסה שנית.",
            )

        # Find token in database
        tokens_coll = db.webapp_tokens if hasattr(db, "webapp_tokens") else db["webapp_tokens"]
        token_doc = tokens_coll.find_one({"token": token, "user_id": int(user_id)})

        if not token_doc:
            return render_template(
                "login.html",
                bot_username=bot_username,
                error="קישור ההתחברות לא תקף או פג תוקפו",
            )

        # Check expiration
        if token_doc["expires_at"] < datetime.now(timezone.utc):
            # Delete expired token
            tokens_coll.delete_one({"_id": token_doc["_id"]})
            return render_template(
                "login.html",
                bot_username=bot_username,
                error="קישור ההתחברות פג תוקף. אנא בקש קישור חדש מהבוט.",
            )

        # Delete token after use (one-time use)
        tokens_coll.delete_one({"_id": token_doc["_id"]})

        # Fetch user details
        now_utc = datetime.now(timezone.utc)
        users_coll = db.users if hasattr(db, "users") else db["users"]
        user = users_coll.find_one({"user_id": int(user_id)}) or {}

        try:
            users_coll.update_one(
                {"user_id": int(user_id)},
                {
                    "$set": {
                        "user_id": int(user_id),
                        "first_name": user.get("first_name") or token_doc.get("first_name", ""),
                        "last_name": user.get("last_name") or token_doc.get("last_name", ""),
                        "username": token_doc.get("username", user.get("username", "")),
                        "photo_url": user.get("photo_url", ""),
                        "updated_at": now_utc,
                    },
                    "$setOnInsert": {
                        "created_at": now_utc,
                        "has_seen_welcome_modal": False,
                    },
                },
                upsert=True,
            )
        except Exception:
            pass

        try:
            from database.collections_manager import CollectionsManager

            CollectionsManager(db).ensure_default_collections(int(user_id))
        except Exception:
            pass

        # Save user data to session
        user_id_int = int(user_id)
        session["user_id"] = user_id_int
        session["user_data"] = {
            "id": user_id_int,
            "first_name": user.get("first_name", token_doc.get("first_name", "")),
            "last_name": user.get("last_name", token_doc.get("last_name", "")),
            "username": token_doc.get("username", ""),
            "photo_url": user.get("photo_url", ""),
            "has_seen_welcome_modal": bool(user.get("has_seen_welcome_modal", False)),
            "is_admin": _is_admin(user_id_int),
            "is_premium": _is_premium(user_id_int),
        }

        # Make session permanent (30 days)
        session.permanent = True

        return redirect("/dashboard")

    except Exception:
        logger.exception("Error in token auth")
        return render_template(
            "login.html",
            bot_username=bot_username,
            error="שגיאה בהתחברות. אנא נסה שנית.",
        )


@auth_bp.route("/logout")
def logout():
    """Logout."""
    cookie_name = _get_remember_cookie_name()
    try:
        token = request.cookies.get(cookie_name)
        if token:
            try:
                db = _get_db_for_auth()
                if db is not None:
                    tokens_coll = db.remember_tokens if hasattr(db, "remember_tokens") else db["remember_tokens"]
                    tokens_coll.delete_one({"token": token})
            except Exception:
                pass
    except Exception:
        pass

    resp = redirect(url_for("index"))
    try:
        resp.delete_cookie(cookie_name)
    except Exception:
        pass
    session.clear()
    return resp

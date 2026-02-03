"""
Dashboard Routes - Dashboard and related endpoints for WebApp.

This module implements dashboard endpoints migrated to the new layered architecture:
Route -> Facade/Container -> Service/Domain -> Repository -> DB

Issue: #2871 (Step 3 - The Great Split)

Endpoints:
- GET /dashboard - Main dashboard page
- GET /api/dashboard/last-commit-files - Last commit files (admin only)
- GET /api/dashboard/activity/files - Activity files feed
- GET /api/dashboard/whats-new - What's new feed
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, redirect, render_template, request, session
from pymongo import DESCENDING

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


def _get_files_facade():
    """Lazy import of FilesFacade to avoid circular imports."""
    from src.infrastructure.composition.webapp_container import get_files_facade

    return get_files_facade()


def _get_app_helpers():
    """
    Lazy import of helper functions from app.py.
    """
    from webapp.app import (
        _build_activity_timeline,
        _build_files_need_attention,
        _build_notes_snapshot,
        _build_push_card,
        _build_timeline_event,
        _finalize_events,
        _get_active_dismissals,
        _load_whats_new,
        _MIN_DT,
        BOT_USERNAME_CLEAN,
        format_file_size,
        get_db,
        get_language_icon,
        is_admin,
        is_impersonating_safe,
        is_premium,
        resolve_file_language,
    )

    return SimpleNamespace(
        is_admin=is_admin,
        is_premium=is_premium,
        is_impersonating_safe=is_impersonating_safe,
        get_db=get_db,
        format_file_size=format_file_size,
        get_language_icon=get_language_icon,
        resolve_file_language=resolve_file_language,
        _build_activity_timeline=_build_activity_timeline,
        _build_push_card=_build_push_card,
        _build_notes_snapshot=_build_notes_snapshot,
        _load_whats_new=_load_whats_new,
        _get_active_dismissals=_get_active_dismissals,
        _build_files_need_attention=_build_files_need_attention,
        _build_timeline_event=_build_timeline_event,
        _finalize_events=_finalize_events,
        _MIN_DT=_MIN_DT,
        BOT_USERNAME_CLEAN=BOT_USERNAME_CLEAN,
    )


@dashboard_bp.route("/dashboard")
def dashboard():
    """Dashboard with statistics."""
    if "user_id" not in session:
        return redirect("/login")

    helpers = _get_app_helpers()

    try:
        db = helpers.get_db()
        user_id = session["user_id"]

        # Check if user is admin (effective status)
        actual_is_admin = False
        try:
            actual_is_admin = bool(helpers.is_admin(int(user_id)))
        except Exception:
            actual_is_admin = False
        if helpers.is_impersonating_safe():
            user_is_admin = False
        else:
            user_is_admin = actual_is_admin

        # Fetch statistics - only active files
        active_query = {"user_id": user_id, "is_active": True}
        total_files = db.code_snippets.count_documents(active_query)

        # Calculate total size
        pipeline = [
            {"$match": {"user_id": user_id, "is_active": True}},
            {
                "$project": {
                    "code_size": {
                        "$cond": {
                            "if": {
                                "$and": [
                                    {"$ne": ["$code", None]},
                                    {"$eq": [{"$type": "$code"}, "string"]},
                                ]
                            },
                            "then": {"$strLenBytes": "$code"},
                            "else": 0,
                        }
                    }
                }
            },
            {"$group": {"_id": None, "total_size": {"$sum": "$code_size"}}},
        ]
        size_result = list(db.code_snippets.aggregate(pipeline))
        total_size = size_result[0]["total_size"] if size_result else 0

        # Popular languages
        languages_pipeline = [
            {"$match": {"user_id": user_id, "is_active": True}},
            {"$group": {"_id": "$programming_language", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        top_languages = list(db.code_snippets.aggregate(languages_pipeline))

        # Recent activity
        recent_files = list(
            db.code_snippets.find(
                {"user_id": user_id, "is_active": True},
                {"file_name": 1, "programming_language": 1, "created_at": 1},
            )
            .sort("created_at", DESCENDING)
            .limit(5)
        )

        # Process data for display
        for file in recent_files:
            file["_id"] = str(file["_id"])
            language = helpers.resolve_file_language(
                file.get("programming_language"), file.get("file_name", "")
            )
            file["language"] = language
            file["icon"] = helpers.get_language_icon(language)
            if "created_at" in file:
                file["created_at_formatted"] = file["created_at"].strftime(
                    "%d/%m/%Y %H:%M"
                )

        stats = {
            "total_files": total_files,
            "total_size": helpers.format_file_size(total_size),
            "top_languages": [
                {
                    "name": lang["_id"] or "לא מוגדר",
                    "count": lang["count"],
                    "icon": helpers.get_language_icon(lang["_id"] or ""),
                }
                for lang in top_languages
            ],
            "recent_files": recent_files,
        }

        # Pinned files for dashboard
        pinned_files = []
        max_pinned = 8
        try:
            from database.manager import (
                MAX_PINNED_FILES,
                get_pinned_files as _get_pinned_files,
            )

            pin_manager = SimpleNamespace(collection=db.code_snippets)
            pinned_files = _get_pinned_files(pin_manager, user_id)
            max_pinned = MAX_PINNED_FILES
        except Exception:
            pinned_files = []
        pinned_data = []
        for p in pinned_files:
            pinned_data.append(
                {
                    "id": str(p.get("_id", "")),
                    "file_name": p.get("file_name", ""),
                    "language": p.get("programming_language", ""),
                    "icon": helpers.get_language_icon(p.get("programming_language", "")),
                    "tags": (p.get("tags") or [])[:3],
                    "description": (p.get("description", "") or "")[:50],
                    "lines": p.get("lines_count", 0),
                }
            )

        # Last commit (admin only)
        last_commit = None
        if user_is_admin:
            try:
                from services.git_mirror_service import get_mirror_service

                repo_name = os.getenv("REPO_NAME", "CodeBot")
                git_service = get_mirror_service()

                if git_service.mirror_exists(repo_name):
                    last_commit = git_service.get_last_commit_info(repo_name)

                    if last_commit:
                        metadata = db.repo_metadata.find_one({"repo_name": repo_name})
                        if metadata:
                            last_commit["sync_time"] = metadata.get("last_sync_time")
                            last_commit["sync_status"] = metadata.get(
                                "sync_status", "unknown"
                            )
                        try:
                            raw_date = str(last_commit.get("date") or "").strip()
                        except Exception:
                            raw_date = ""
                        if raw_date:
                            local_dt = None
                            try:
                                normalized = raw_date.replace("Z", "+00:00")
                                parsed = datetime.fromisoformat(normalized)
                                if parsed.tzinfo is None:
                                    parsed = parsed.replace(tzinfo=timezone.utc)
                                local_dt = parsed.astimezone(ZoneInfo("Asia/Jerusalem"))
                            except Exception:
                                local_dt = None
                            if local_dt is not None:
                                last_commit["date_israel"] = local_dt
                                last_commit["date_israel_str"] = local_dt.strftime(
                                    "%d/%m/%Y %H:%M"
                                )
            except Exception as e:
                logger.warning(f"Failed to get last commit info: {e}")
                last_commit = None

        activity_timeline = helpers._build_activity_timeline(db, user_id, active_query)
        push_card = helpers._build_push_card(db, user_id)
        notes_snapshot = helpers._build_notes_snapshot(db, user_id)
        whats_new = helpers._load_whats_new(limit=5)

        # Widget: files that need attention
        dismissed_ids = helpers._get_active_dismissals(db, user_id)
        files_need_attention = helpers._build_files_need_attention(
            db,
            user_id,
            max_items=10,
            stale_days=60,
            dismissed_ids=dismissed_ids,
        )

        return render_template(
            "dashboard.html",
            user=session["user_data"],
            stats=stats,
            activity_timeline=activity_timeline,
            push_card=push_card,
            notes_snapshot=notes_snapshot,
            whats_new=whats_new,
            files_need_attention=files_need_attention,
            bot_username=helpers.BOT_USERNAME_CLEAN,
            pinned_files=pinned_data,
            max_pinned=max_pinned,
            user_is_admin=user_is_admin,
            last_commit=last_commit,
            repo_name=os.getenv("REPO_NAME", "CodeBot"),
        )

    except Exception:
        logger.exception("Error in dashboard")
        # Try to show empty dashboard on error
        fallback_timeline = {
            "groups": [],
            "feed": [],
            "filters": [{"id": "all", "label": "הכול", "count": 0}],
            "compact_limit": 5,
            "has_events": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        fallback_card = {
            "feature_enabled": False,
            "subscriptions": 0,
            "status_text": "לא זמין",
            "status_variant": "danger",
            "pending_count": 0,
            "last_push": None,
            "next_reminder": None,
            "cta_href": "/settings#push",
            "cta_label": "נהל התראות",
        }
        fallback_notes = {"notes": [], "total": 0, "has_notes": False}
        fallback_attention = {
            "missing_metadata": [],
            "stale_files": [],
            "total_missing": 0,
            "total_stale": 0,
            "shown_missing": 0,
            "shown_stale": 0,
            "has_items": False,
            "settings": {"stale_days": 60, "max_items": 10},
        }

        helpers = _get_app_helpers()

        return render_template(
            "dashboard.html",
            user=session.get("user_data", {}),
            stats={
                "total_files": 0,
                "total_size": "0 B",
                "top_languages": [],
                "recent_files": [],
            },
            pinned_files=[],
            max_pinned=8,
            activity_timeline=fallback_timeline,
            push_card=fallback_card,
            notes_snapshot=fallback_notes,
            whats_new={"features": [], "has_features": False, "total": 0},
            files_need_attention=fallback_attention,
            error="אירעה שגיאה בטעינת הנתונים. אנא נסה שוב.",
            bot_username=helpers.BOT_USERNAME_CLEAN,
            user_is_admin=False,
            last_commit=None,
            repo_name=os.getenv("REPO_NAME", "CodeBot"),
        )


@dashboard_bp.route("/api/dashboard/last-commit-files", methods=["GET"])
def api_dashboard_last_commit_files():
    """Get files from last commit (admin only)."""
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    helpers = _get_app_helpers()
    user_id = session["user_id"]

    try:
        if not helpers.is_admin(int(user_id)):
            return jsonify({"ok": False, "error": "forbidden"}), 403
    except Exception:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    try:
        from services.git_mirror_service import get_mirror_service

        repo_name = os.getenv("REPO_NAME", "CodeBot")
        git_service = get_mirror_service()

        if not git_service.mirror_exists(repo_name):
            return jsonify({"ok": False, "error": "mirror_not_found"}), 404

        last_commit = git_service.get_last_commit_info(repo_name)
        if not last_commit:
            return jsonify({"ok": False, "error": "no_commits"}), 404

        commit_sha = last_commit.get("sha", "")
        if not commit_sha:
            return jsonify({"ok": False, "error": "no_sha"}), 404

        files = git_service.get_commit_files(repo_name, commit_sha)

        return jsonify(
            {
                "ok": True,
                "commit": {
                    "sha": commit_sha[:7],
                    "message": last_commit.get("message", ""),
                    "date": last_commit.get("date", ""),
                },
                "files": files,
            }
        )

    except Exception:
        logger.exception("Error fetching last commit files")
        return jsonify({"ok": False, "error": "internal_error"}), 500


@dashboard_bp.route("/api/dashboard/activity/files", methods=["GET"])
def api_dashboard_activity_files():
    """API: Load more file events for the activity feed (up to 7 days back)."""
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    helpers = _get_app_helpers()
    user_id = session["user_id"]

    try:
        user_id_int = int(user_id) if user_id is not None else None
    except Exception:
        user_id_int = None
    if not user_id_int:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    raw_offset = request.args.get("offset", "0")
    raw_limit = request.args.get("limit", "12")
    try:
        offset = int(raw_offset)
    except Exception:
        offset = 0
    try:
        limit = int(raw_limit)
    except Exception:
        limit = 12

    offset = max(0, offset)
    limit = max(1, min(50, limit))

    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(days=7)

    db = helpers.get_db()
    base_query = {
        "user_id": user_id_int,
        "is_active": True,
    }
    recent_query: Dict[str, Any] = dict(base_query)
    recent_query["$or"] = [
        {"updated_at": {"$gte": recent_cutoff}},
        {"updated_at": {"$exists": False}, "created_at": {"$gte": recent_cutoff}},
        {"updated_at": None, "created_at": {"$gte": recent_cutoff}},
    ]

    try:
        total_recent = int(db.code_snippets.count_documents(recent_query))
    except Exception:
        total_recent = 0

    try:
        cursor = (
            db.code_snippets.find(
                recent_query,
                {
                    "file_name": 1,
                    "programming_language": 1,
                    "updated_at": 1,
                    "created_at": 1,
                    "version": 1,
                    "description": 1,
                },
            )
            .sort("updated_at", DESCENDING)
            .skip(offset)
            .limit(limit)
        )
        docs = list(cursor or [])
    except Exception:
        logger.warning("Failed to fetch timeline files")
        return jsonify({"ok": False, "error": "load_failed"}), 500

    items: List[Dict[str, Any]] = []
    for doc in docs:
        dt = doc.get("updated_at") or doc.get("created_at")
        version = doc.get("version") or 1
        is_new = version == 1
        action = "נוצר" if is_new else "עודכן"
        file_name = doc.get("file_name") or "ללא שם"
        language = helpers.resolve_file_language(
            doc.get("programming_language"), file_name
        )
        title = f"{action} {file_name}"
        details: List[str] = []
        if doc.get("programming_language"):
            details.append(doc["programming_language"])
        elif language and language != "text":
            details.append(language)
        if version:
            details.append(f"גרסה {version}")
        description = (doc.get("description") or "").strip()
        subtitle = (
            description
            if description
            else (" · ".join(details) if details else "ללא פרטים נוספים")
        )
        href = f"/file/{doc.get('_id')}"
        file_badge = doc.get("programming_language") or (
            language if language and language != "text" else None
        )
        items.append(
            helpers._build_timeline_event(
                "files",
                title=title,
                subtitle=subtitle,
                dt=dt,
                icon=helpers.get_language_icon(language),
                badge=file_badge,
                badge_variant="code",
                href=href,
                meta={"details": " · ".join(details)},
            )
        )

    # Maintain format consistency with dashboard
    finalized = helpers._finalize_events(
        sorted(items, key=lambda ev: ev.get("_dt") or helpers._MIN_DT, reverse=True)
    )
    next_offset = offset + len(finalized)
    remaining = max(0, total_recent - next_offset)

    return jsonify(
        {
            "ok": True,
            "events": finalized,
            "total_recent": total_recent,
            "offset": offset,
            "next_offset": next_offset,
            "remaining": remaining,
            "has_more": bool(remaining > 0),
        }
    )


@dashboard_bp.route("/api/dashboard/whats-new", methods=["GET"])
def api_dashboard_whats_new():
    """API: Load more new features (pagination)."""
    if "user_id" not in session:
        return jsonify({"ok": False, "error": "not_logged_in"}), 401

    helpers = _get_app_helpers()

    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = min(10, max(1, int(request.args.get("limit", 5))))
        max_days = min(180, max(7, int(request.args.get("max_days", 30))))
    except (ValueError, TypeError):
        offset = 0
        limit = 5
        max_days = 30

    try:
        data = helpers._load_whats_new(limit=limit, offset=offset, max_days=max_days)
        return jsonify(
            {
                "ok": True,
                "features": data["features"],
                "total": data["total"],
                "offset": data["offset"],
                "next_offset": data["next_offset"],
                "remaining": data["remaining"],
                "has_more": data["has_more"],
            }
        )
    except Exception:
        logger.exception("Error fetching what's new")
        return jsonify({"ok": False, "error": "internal_error"}), 500

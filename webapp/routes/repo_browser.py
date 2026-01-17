"""
Repository Browser Routes

UI לגלישה בקוד הריפו
"""

from __future__ import annotations

import logging
import re  # חשוב! לצורך re.escape
from functools import lru_cache

from flask import Blueprint, abort, jsonify, render_template, request

from database.db_manager import get_db
from services.git_mirror_service import get_mirror_service
from services.repo_search_service import create_search_service

logger = logging.getLogger(__name__)

repo_bp = Blueprint("repo", __name__, url_prefix="/repo")


@repo_bp.route("/")
def repo_index():
    """דף ראשי של דפדפן הקוד"""
    db = get_db()
    git_service = get_mirror_service()

    # מידע על הריפו
    repo_name = "CodeBot"  # או מ-config

    metadata = db.repo_metadata.find_one({"repo_name": repo_name})
    mirror_info = git_service.get_mirror_info(repo_name)

    return render_template("repo/index.html", repo_name=repo_name, metadata=metadata, mirror_info=mirror_info)


@repo_bp.route("/browse")
@repo_bp.route("/browse/<path:dir_path>")
def browse_directory(dir_path: str = ""):
    """גלישה בתיקיות"""
    db = get_db()
    repo_name = "CodeBot"

    # בניית שאילתה לקבצים בתיקייה
    # חובה לעשות escape לתווים מיוחדים ב-regex!
    # בלי זה, תיקיות כמו ".github" ישברו (הנקודה = "any char")
    if dir_path:
        # קבצים בתיקייה ספציפית
        safe_path = re.escape(dir_path)  # .github -> \.github
        pattern = f"^{safe_path}/[^/]+$"
    else:
        # קבצים ב-root
        pattern = "^[^/]+$"

    # שליפת קבצים
    files = list(
        db.repo_files.find(
            {"repo_name": repo_name, "path": {"$regex": pattern}},
            {"path": 1, "language": 1, "size": 1, "lines": 1},
        ).sort("path", 1)
    )

    # שליפת תיקיות (גם כאן צריך escape!)
    if dir_path:
        safe_path = re.escape(dir_path)
        dir_pattern = f"^{safe_path}/[^/]+/"
    else:
        dir_pattern = "^[^/]+/"

    # שימוש ב-regex כבר ב-DB כדי לא למשוך את כל הנתיבים לריפו גדול
    all_paths = db.repo_files.distinct(
        "path",
        {
            "repo_name": repo_name,
            "path": {"$regex": dir_pattern},
        },
    )

    # חילוץ תיקיות ייחודיות
    directories = set()
    for path in all_paths:
        if dir_path:
            if path.startswith(dir_path + "/"):
                remaining = path[len(dir_path) + 1 :]
                if "/" in remaining:
                    directories.add(remaining.split("/")[0])
        else:
            if "/" in path:
                directories.add(path.split("/")[0])

    return render_template(
        "repo/browse.html",
        repo_name=repo_name,
        current_path=dir_path,
        files=files,
        directories=sorted(directories),
        breadcrumbs=_build_breadcrumbs(dir_path),
    )


@repo_bp.route("/file/<path:file_path>")
def view_file(file_path: str):
    """הצגת קובץ"""
    db = get_db()
    git_service = get_mirror_service()
    repo_name = "CodeBot"

    # metadata מ-MongoDB
    metadata = db.repo_files.find_one({"repo_name": repo_name, "path": file_path})

    if not metadata:
        abort(404)

    # תוכן מ-git mirror
    content = git_service.get_file_content(repo_name, file_path)

    if content is None:
        abort(404)

    return render_template(
        "repo/file.html",
        repo_name=repo_name,
        file_path=file_path,
        content=content,
        metadata=metadata,
        breadcrumbs=_build_breadcrumbs(file_path),
    )


@repo_bp.route("/search")
def search():
    """חיפוש בקוד"""
    query = request.args.get("q", "")
    search_type = request.args.get("type", "content")
    file_pattern = request.args.get("pattern", "")
    repo_name = "CodeBot"

    if not query:
        return render_template(
            "repo/search.html",
            repo_name=repo_name,
            query="",
            search_type=search_type,
            results=[],
            total=0,
            truncated=False,
            error=None,
        )

    db = get_db()
    search_service = create_search_service(db)

    result = search_service.search(
        repo_name=repo_name,
        query=query,
        search_type=search_type,
        file_pattern=file_pattern or None,
        max_results=100,
    )

    return render_template(
        "repo/search.html",
        repo_name=repo_name,
        query=query,
        search_type=search_type,
        results=result.get("results", []),
        total=result.get("total", 0),
        truncated=result.get("truncated", False),
        error=result.get("error"),
    )


@repo_bp.route("/api/file/<path:file_path>")
def api_get_file(file_path: str):
    """API לקבלת תוכן קובץ"""
    git_service = get_mirror_service()
    repo_name = "CodeBot"

    content = git_service.get_file_content(repo_name, file_path)

    if content is None:
        return jsonify({"error": "File not found"}), 404

    return jsonify({"path": file_path, "content": content})


@repo_bp.route("/api/search")
def api_search():
    """API לחיפוש"""
    query = request.args.get("q", "")
    search_type = request.args.get("type", "content")

    if not query:
        return jsonify({"error": "Query required"}), 400

    db = get_db()
    search_service = create_search_service(db)
    repo_name = "CodeBot"

    result = search_service.search(repo_name=repo_name, query=query, search_type=search_type, max_results=50)

    return jsonify(result)


@repo_bp.route("/api/stats")
def api_stats():
    """API לסטטיסטיקות"""
    git_service = get_mirror_service()
    repo_name = "CodeBot"

    stats = git_service.get_repo_stats(repo_name)

    if stats is None:
        return jsonify({"error": "Stats not available"}), 404

    return jsonify(stats)


def _build_breadcrumbs(path: str) -> list:
    """בניית breadcrumbs לניווט"""
    if not path:
        return []

    parts = path.split("/")
    breadcrumbs = []

    for i, part in enumerate(parts):
        breadcrumbs.append({"name": part, "path": "/".join(parts[: i + 1]), "is_last": i == len(parts) - 1})

    return breadcrumbs


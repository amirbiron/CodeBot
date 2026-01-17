"""
Repository Browser Routes - Extended API

UI לגלישה בקוד הריפו עם API מתקדם
"""

import logging
import re
from flask import Blueprint, render_template, request, jsonify, abort
from functools import lru_cache

from services.git_mirror_service import get_mirror_service
from services.repo_search_service import create_search_service
from database.db_manager import get_db

logger = logging.getLogger(__name__)

repo_bp = Blueprint('repo', __name__, url_prefix='/repo')


@repo_bp.route('/')
def repo_index():
    """דף ראשי של דפדפן הקוד"""
    db = get_db()
    git_service = get_mirror_service()
    
    repo_name = "CodeBot"
    
    metadata = db.repo_metadata.find_one({"repo_name": repo_name})
    mirror_info = git_service.get_mirror_info(repo_name)
    
    # Get file type stats
    if metadata:
        file_types = {}
        cursor = db.repo_files.aggregate([
            {"$match": {"repo_name": repo_name}},
            {"$group": {"_id": "$language", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ])
        for doc in cursor:
            if doc["_id"]:
                file_types[doc["_id"]] = doc["count"]
        metadata["file_types"] = file_types
    
    return render_template(
        'repo/index.html',
        repo_name=repo_name,
        metadata=metadata,
        mirror_info=mirror_info
    )


@repo_bp.route('/api/tree')
def api_tree():
    """
    API לקבלת עץ הקבצים
    
    Query params:
        path: נתיב לתיקייה ספציפית (אופציונלי)
    """
    db = get_db()
    repo_name = "CodeBot"
    path = request.args.get('path', '')
    
    # Build tree from MongoDB
    if path:
        # Get children of specific folder
        safe_path = re.escape(path)
        pattern = f"^{safe_path}/[^/]+$"
    else:
        # Get root level
        pattern = "^[^/]+$"
    
    # Get files matching pattern
    files = list(db.repo_files.find(
        {
            "repo_name": repo_name,
            "path": {"$regex": pattern}
        },
        {"path": 1, "language": 1, "size": 1, "lines": 1}
    ).sort("path", 1))
    
    # Get all paths to find directories
    all_paths = db.repo_files.distinct("path", {"repo_name": repo_name})
    
    # Extract unique directories at this level
    directories = set()
    prefix = path + "/" if path else ""
    prefix_len = len(prefix)
    
    for p in all_paths:
        if p.startswith(prefix):
            remaining = p[prefix_len:]
            if "/" in remaining:
                dir_name = remaining.split("/")[0]
                directories.add(dir_name)
    
    # Build result
    result = []
    
    # Add directories first
    for dir_name in sorted(directories):
        dir_path = f"{path}/{dir_name}" if path else dir_name
        result.append({
            "name": dir_name,
            "path": dir_path,
            "type": "directory"
        })
    
    # Add files
    for f in files:
        name = f["path"].split("/")[-1]
        result.append({
            "name": name,
            "path": f["path"],
            "type": "file",
            "language": f.get("language", "text"),
            "size": f.get("size", 0),
            "lines": f.get("lines", 0)
        })
    
    return jsonify(result)


@repo_bp.route('/api/file/<path:file_path>')
def api_get_file(file_path: str):
    """API לקבלת תוכן קובץ"""
    db = get_db()
    git_service = get_mirror_service()
    repo_name = "CodeBot"
    
    # Get metadata from MongoDB
    metadata = db.repo_files.find_one({
        "repo_name": repo_name,
        "path": file_path
    })
    
    # Get content from git mirror
    content = git_service.get_file_content(repo_name, file_path)
    
    if content is None:
        return jsonify({"error": "File not found"}), 404
    
    return jsonify({
        "path": file_path,
        "content": content,
        "language": metadata.get("language", "text") if metadata else "text",
        "size": metadata.get("size", len(content)) if metadata else len(content),
        "lines": metadata.get("lines", content.count("\n") + 1) if metadata else content.count("\n") + 1
    })


@repo_bp.route('/api/search')
def api_search():
    """API לחיפוש משופר"""
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'content')
    file_pattern = request.args.get('pattern', '')
    language = request.args.get('language', '')
    
    if not query or len(query) < 2:
        return jsonify({"error": "Query too short", "results": []})
    
    db = get_db()
    search_service = create_search_service(db)
    repo_name = "CodeBot"
    
    result = search_service.search(
        repo_name=repo_name,
        query=query,
        search_type=search_type,
        file_pattern=file_pattern or None,
        language=language or None,
        max_results=50
    )
    
    return jsonify(result)


@repo_bp.route('/api/stats')
def api_stats():
    """API לסטטיסטיקות"""
    db = get_db()
    git_service = get_mirror_service()
    repo_name = "CodeBot"
    
    # Get from git service
    stats = git_service.get_repo_stats(repo_name)
    
    if stats is None:
        return jsonify({"error": "Stats not available"}), 404
    
    # Enrich with MongoDB stats
    metadata = db.repo_metadata.find_one({"repo_name": repo_name})
    if metadata:
        stats["last_sync"] = metadata.get("last_sync_time")
        stats["sync_status"] = metadata.get("sync_status")
    
    return jsonify(stats)


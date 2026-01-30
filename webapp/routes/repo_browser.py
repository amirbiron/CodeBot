"""
Repository Browser Routes - Extended API

UI לגלישה בקוד הריפו עם API מתקדם
"""

import logging
import re
from flask import Blueprint, render_template, request, jsonify, abort, redirect, url_for, current_app
from functools import lru_cache

from services.git_mirror_service import get_mirror_service
from services.repo_search_service import create_search_service
from database.db_manager import get_db

logger = logging.getLogger(__name__)

repo_bp = Blueprint('repo', __name__, url_prefix='/repo')

# הגדרות
DEFAULT_REPO_NAME = "CodeBot"


def get_git_service():
    """Helper לקבלת ה-Git service."""
    service = current_app.extensions.get('git_mirror_service')
    if not service:
        service = get_mirror_service()
        current_app.extensions['git_mirror_service'] = service
    return service


def get_current_repo_name(return_source: bool = False):
    """
    מחזיר את שם הריפו הנוכחי לפי סדר עדיפויות:
    1. Query parameter 'repo' מה-URL
    2. Session (אם המשתמש מחובר)
    3. ברירת מחדל: CodeBot
    """
    from flask_login import current_user
    from database import db as repo_manager

    # 1. מ-query parameter
    repo_from_query = request.args.get('repo', '').strip()
    if repo_from_query:
        # ולידציה בסיסית של שם ריפו
        if re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$', repo_from_query):
            return (repo_from_query, "query") if return_source else repo_from_query

    # 2. מה-session (למשתמש מחובר)
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        try:
            saved_repo = repo_manager.get_selected_repo(current_user.id)
            if saved_repo:
                return (saved_repo, "user") if return_source else saved_repo
        except Exception as e:
            logger.warning(f"Could not get saved repo: {e}")

    # 3. ברירת מחדל
    return (DEFAULT_REPO_NAME, "default") if return_source else DEFAULT_REPO_NAME


# ========================================
# Legacy Routes Redirects (מ-גרסה ישנה)
# ========================================

@repo_bp.route('/browse')
@repo_bp.route('/browse/')
@repo_bp.route('/browse/<path:subpath>')
def legacy_browse(subpath: str = ''):
    """Redirect from legacy /browse to new repo index"""
    return redirect(url_for('repo.repo_index'))


@repo_bp.route('/search')
def legacy_search():
    """Redirect from legacy /search to new repo index with search"""
    query = request.args.get('q', '')
    if query:
        # Pass query to frontend via fragment
        return redirect(url_for('repo.repo_index') + f'#search={query}')
    return redirect(url_for('repo.repo_index'))


@repo_bp.route('/')
def repo_index():
    """דף ראשי של דפדפן הקוד"""
    try:
        db = get_db()
        git_service = get_mirror_service()
        
        repo_name = get_current_repo_name()
        
        metadata = None
        mirror_info = None
        file_types = {}
        
        try:
            metadata = db.repo_metadata.find_one({"repo_name": repo_name})
            mirror_info = git_service.get_mirror_info(repo_name)
        except Exception as e:
            logger.warning(f"Could not fetch repo info: {e}")
        
        # Get file type stats
        if metadata:
            try:
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
            except Exception as e:
                logger.warning(f"Could not fetch file types: {e}")
        
        return render_template(
            'repo/index.html',
            repo_name=repo_name,
            metadata=metadata,
            mirror_info=mirror_info
        )
    except Exception as e:
        logger.exception(f"Repo index error: {e}")
        return render_template(
            'repo/index.html',
            repo_name=get_current_repo_name(),
            metadata=None,
            mirror_info=None,
            error=str(e)
        )


@repo_bp.route('/api/tree')
def api_tree():
    """
    API לקבלת עץ הקבצים
    
    Query params:
        path: נתיב לתיקייה ספציפית (אופציונלי)
        types: סינון לפי סוגי קבצים, מופרד בפסיקים (אופציונלי)
               לדוגמה: types=python,javascript,html
    """
    db = get_db()
    repo_name = get_current_repo_name()
    path = request.args.get('path', '')
    types_param = request.args.get('types', '').strip()
    
    # Build tree from MongoDB
    if path:
        # Get children of specific folder
        safe_path = re.escape(path)
        pattern = f"^{safe_path}/[^/]+$"
    else:
        # Get root level
        pattern = "^[^/]+$"
    
    # Build query
    query = {
        "repo_name": repo_name,
        "path": {"$regex": pattern}
    }
    
    # Add language filter if specified
    if types_param:
        types_list = [t.strip() for t in types_param.split(',') if t.strip()]
        if types_list:
            query["language"] = {"$in": types_list}
    
    # Get files matching pattern
    files = list(db.repo_files.find(
        query,
        {"path": 1, "language": 1, "size": 1, "lines": 1}
    ).sort("path", 1))
    
    # Get all paths to find directories
    # ביצועים: לא מושכים את כל הנתיבים לריפו גדול.
    # מביאים distinct רק על נתיבים תחת ה-prefix הרלוונטי (כולל nested) כדי להפיק תיקיות.
    if path:
        safe_prefix = re.escape(path)
        dir_pattern = f"^{safe_prefix}/"
    else:
        dir_pattern = "^[^/]+/"

    # Build query for directories (same filters apply)
    dir_query: dict = {
        "repo_name": repo_name,
        "path": {"$regex": dir_pattern},
    }
    if types_param:
        types_list = [t.strip() for t in types_param.split(',') if t.strip()]
        if types_list:
            dir_query["language"] = {"$in": types_list}

    all_paths = db.repo_files.distinct(
        "path",
        dir_query,
    )
    
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
    repo_name = get_current_repo_name()
    
    # Get metadata from MongoDB
    metadata = db.repo_files.find_one({
        "repo_name": repo_name,
        "path": file_path
    })
    
    # Get content from git mirror
    # חשוב: ב-bare mirror לא מסתמכים על HEAD (יכול להצביע למשהו לא צפוי).
    # נעדיף commit_sha שאונדקס (עקביות מול תוצאות חיפוש), ואם חסר - origin/<default_branch>.
    commit_sha = metadata.get("commit_sha") if metadata else None
    ref = commit_sha
    if not ref:
        meta = db.repo_metadata.find_one({"repo_name": repo_name}) or {}
        default_branch = str(meta.get("default_branch") or "").strip() or "main"
        ref = f"origin/{default_branch}"

    content = git_service.get_file_content(repo_name, file_path, ref=ref)
    
    if content is None:
        return jsonify({"error": "File not found"}), 404
    
    return jsonify({
        "path": file_path,
        "content": content,
        "language": metadata.get("language", "text") if metadata else "text",
        "size": metadata.get("size", len(content)) if metadata else len(content),
        "lines": metadata.get("lines", content.count("\n") + 1) if metadata else content.count("\n") + 1
    })


# ============================================
# Routes חדשים - היסטוריה ו-Diff
# ============================================

@repo_bp.route('/api/history', methods=['GET'])
def get_file_history():
    """
    שליפת היסטוריית commits לקובץ ספציפי.

    Query params:
        - file: נתיב הקובץ (required)
        - limit: מספר commits מקסימלי (default: 20, max: 100)
        - skip: כמה commits לדלג (default: 0)
        - ref: branch/tag/commit להתחיל ממנו (default: HEAD)
    """
    try:
        # שליפת file_path מ-query parameter
        file_path = request.args.get('file', '')
        if not file_path:
            return jsonify({
                "success": False,
                "error": "missing_file",
                "message": "חסר פרמטר file"
            }), 400

        git_service = get_git_service()
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

        if not git_service._validate_repo_file_path(file_path):
            return jsonify({
                "success": False,
                "error": "invalid_file_path",
                "message": "נתיב קובץ לא תקין"
            }), 400

        limit = request.args.get('limit', 20, type=int)
        skip = request.args.get('skip', 0, type=int)
        ref = request.args.get('ref', 'HEAD')

        result = git_service.get_file_history(
            repo_name=get_current_repo_name(),
            file_path=file_path,
            ref=ref,
            limit=limit,
            skip=skip
        )

        if "error" in result:
            status_codes = {
                "invalid_repo_name": 400,
                "invalid_file_path": 400,
                "invalid_ref": 400,
                "repo_not_found": 404,
                "file_not_found": 404,
                "timeout": 504,
                "git_error": 500,
                "internal_error": 500
            }
            return jsonify({
                "success": False,
                **result
            }), status_codes.get(result["error"], 500)

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error in get_file_history: {e}")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "שגיאה פנימית"
        }), 500


@repo_bp.route('/api/file-at-commit/<commit>', methods=['GET'])
def get_file_at_commit(commit):
    """
    שליפת תוכן קובץ ב-commit ספציפי.

    Query params:
        - file: נתיב הקובץ (required)
    """
    try:
        file_path = request.args.get('file', '')
        if not file_path:
            return jsonify({
                "success": False,
                "error": "missing_file",
                "message": "חסר פרמטר file"
            }), 400

        git_service = get_git_service()
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

        if not git_service._validate_repo_file_path(file_path):
            return jsonify({
                "success": False,
                "error": "invalid_file_path",
                "message": "נתיב קובץ לא תקין"
            }), 400

        result = git_service.get_file_at_commit(
            repo_name=get_current_repo_name(),
            file_path=file_path,
            commit=commit
        )

        if "error" in result:
            status_codes = {
                "invalid_repo_name": 400,
                "invalid_file_path": 400,
                "invalid_commit": 400,
                "repo_not_found": 404,
                "file_not_in_commit": 404,
                "file_too_large": 413,
                "timeout": 504,
                "git_error": 500,
                "internal_error": 500
            }
            return jsonify({
                "success": False,
                **result
            }), status_codes.get(result["error"], 500)

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error in get_file_at_commit: {e}")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "שגיאה פנימית"
        }), 500


@repo_bp.route('/api/diff/<path:commit1>/<path:commit2>', methods=['GET'])
def get_diff(commit1, commit2):
    """
    שליפת diff בין שני commits.

    Semantics: מראה מה השתנה מ-commit1 (ישן) ל-commit2 (חדש).

    Query params:
        - file: נתיב קובץ ספציפי (optional)
        - context: מספר שורות הקשר (default: 3, max: 20)
        - format: 'raw', 'parsed', או 'both' (default: 'parsed')
        - max_bytes: הגבלת גודל (default: 1MB)
    """
    try:
        file_path = request.args.get('file')
        context_lines = request.args.get('context', 3, type=int)
        output_format = request.args.get('format', 'parsed')
        max_bytes = request.args.get('max_bytes', 1024 * 1024, type=int)
        if max_bytes is None:
            max_bytes = 1024 * 1024

        # Limit max_bytes to reasonable value
        max_bytes = max(1, min(max_bytes, 10 * 1024 * 1024))  # Max 10MB

        git_service = get_git_service()
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

        if file_path and not git_service._validate_repo_file_path(file_path):
            return jsonify({
                "success": False,
                "error": "invalid_file_path",
                "message": "נתיב קובץ לא תקין"
            }), 400

        result = git_service.get_diff(
            repo_name=get_current_repo_name(),
            commit1=commit1,
            commit2=commit2,
            file_path=file_path,
            context_lines=context_lines,
            output_format=output_format,
            max_bytes=max_bytes
        )

        if "error" in result:
            status_codes = {
                "invalid_repo_name": 400,
                "invalid_commit1": 400,
                "invalid_commit2": 400,
                "invalid_file_path": 400,
                "invalid_commits": 404,
                "repo_not_found": 404,
                "timeout": 504,
                "git_error": 500,
                "internal_error": 500
            }
            return jsonify({
                "success": False,
                **result
            }), status_codes.get(result["error"], 500)

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error in get_diff: {e}")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "שגיאה פנימית"
        }), 500


@repo_bp.route('/api/commit/<commit>', methods=['GET'])
def get_commit_info(commit):
    """
    שליפת פרטי commit בודד.
    """
    try:
        git_service = get_git_service()
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

        result = git_service.get_commit_info(
            repo_name=get_current_repo_name(),
            commit=commit
        )

        if "error" in result:
            status_codes = {
                "invalid_repo_name": 400,
                "invalid_commit": 400,
                "commit_not_found": 404,
                "timeout": 504,
                "git_error": 500,
                "parse_error": 500,
                "internal_error": 500
            }
            return jsonify({
                "success": False,
                **result
            }), status_codes.get(result["error"], 500)

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error in get_commit_info: {e}")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "שגיאה פנימית"
        }), 500


@repo_bp.route('/api/search-history', methods=['GET'])
def api_search_history():
    """
    חיפוש בהיסטוריית commits.

    Query params:
        - q: מילת החיפוש (required, min 2 chars)
        - type: סוג החיפוש - "message" (ברירת מחדל) או "code"
        - file: הגבלה לקובץ ספציפי (optional)
        - limit: מספר תוצאות מקסימלי (default: 20, max: 50)
    """
    try:
        query = request.args.get('q', '').strip()
        if not query or len(query) < 2:
            return jsonify({
                "success": False,
                "error": "invalid_query",
                "message": "מילת החיפוש קצרה מדי (מינימום 2 תווים)"
            }), 400

        search_type = request.args.get('type', 'message')
        file_path = request.args.get('file')
        limit = request.args.get('limit', 20, type=int)

        git_service = get_git_service()
        if not git_service:
            return jsonify({
                "success": False,
                "error": "service_unavailable",
                "message": "שירות Git לא זמין"
            }), 503

        # וולידציה לנתיב קובץ אם צוין
        if file_path and not git_service._validate_repo_file_path(file_path):
            return jsonify({
                "success": False,
                "error": "invalid_file_path",
                "message": "נתיב קובץ לא תקין"
            }), 400

        result = git_service.search_history(
            repo_name=get_current_repo_name(),
            query=query,
            search_type=search_type,
            file_path=file_path,
            limit=limit
        )

        if "error" in result:
            status_codes = {
                "invalid_repo_name": 400,
                "invalid_query": 400,
                "invalid_search_type": 400,
                "invalid_file_path": 400,
                "repo_not_found": 404,
                "timeout": 504,
                "git_error": 500,
                "internal_error": 500
            }
            return jsonify({
                "success": False,
                **result
            }), status_codes.get(result["error"], 500)

        return jsonify(result)

    except Exception as e:
        current_app.logger.error(f"Error in search_history: {e}")
        return jsonify({
            "success": False,
            "error": "internal_error",
            "message": "שגיאה פנימית"
        }), 500


@repo_bp.route('/api/search')
def api_search():
    """API לחיפוש משופר"""
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'content')
    file_pattern = request.args.get('pattern', '')
    language = request.args.get('language', '')
    
    if not query or len(query) < 2:
        return jsonify({"error": "Query too short", "results": []})
    
    try:
        db = get_db()
        git_service = get_mirror_service()
        repo_name = get_current_repo_name()
        
        # בדיקה אם ה-mirror קיים
        if not git_service.mirror_exists(repo_name):
            return jsonify({
                "error": "Repository mirror not initialized",
                "message": "Please run initial_import first",
                "results": []
            })
        
        search_service = create_search_service(db)
        
        result = search_service.search(
            repo_name=repo_name,
            query=query,
            search_type=search_type,
            file_pattern=file_pattern or None,
            language=language or None,
            max_results=50
        )
        
        return jsonify(result)
    except Exception as e:
        logger.exception(f"Search API error: {e}")
        error_msg = str(e)
        if "mirror_not_found" in error_msg.lower():
            return jsonify({
                "error": "Repository not synced yet",
                "message": "The code mirror needs to be initialized",
                "results": []
            })
        return jsonify({
            "error": "Search service error",
            "message": error_msg[:200],
            "results": []
        }), 500


@repo_bp.route('/api/file-types')
def api_file_types():
    """
    API לקבלת רשימת סוגי קבצים עם כמויות
    
    Returns:
        רשימת סוגי קבצים וכמותם, ממוינת לפי כמות יורדת
    """
    db = get_db()
    repo_name = get_current_repo_name()
    
    try:
        # Aggregate by language
        cursor = db.repo_files.aggregate([
            {"$match": {"repo_name": repo_name}},
            {"$group": {"_id": "$language", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ])
        
        file_types = []
        for doc in cursor:
            if doc["_id"]:
                file_types.append({
                    "language": doc["_id"],
                    "count": doc["count"]
                })
        
        return jsonify(file_types)
    except Exception as e:
        logger.exception(f"File types API error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@repo_bp.route('/api/stats')
def api_stats():
    """API לסטטיסטיקות"""
    db = get_db()
    git_service = get_mirror_service()
    repo_name = get_current_repo_name()
    
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


@repo_bp.route('/api/repos')
def api_list_repos():
    """
    API לקבלת רשימת כל הריפויים הזמינים.

    Returns:
        רשימת ריפויים עם מטא-דאטה בסיסי
    """
    db = get_db()

    try:
        repos = list(db.repo_metadata.find(
            {},  # כל הריפויים
            {
                "repo_name": 1,
                "repo_url": 1,
                "default_branch": 1,
                "total_files": 1,
                "last_sync_time": 1,
                "sync_status": 1,
                "_id": 0
            }
        ).sort("repo_name", 1))

        current_repo, current_source = get_current_repo_name(return_source=True)

        return jsonify({
            "success": True,
            "repos": repos,
            "current": current_repo,
            "current_source": current_source
        })
    except Exception as e:
        logger.exception(f"List repos API error: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to fetch repos",
            "repos": []
        }), 500


@repo_bp.route('/api/select-repo', methods=['POST'])
def api_select_repo():
    """
    API לשמירת הריפו הנבחר למשתמש מחובר.
    """
    from flask_login import current_user
    from database import db as repo_manager

    if not hasattr(current_user, 'is_authenticated') or not current_user.is_authenticated:
        return jsonify({
            "success": False,
            "error": "Authentication required"
        }), 401

    data = request.get_json() or {}
    repo_name = data.get('repo_name', '').strip()

    if not repo_name or not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$', repo_name):
        return jsonify({
            "success": False,
            "error": "Invalid repo name"
        }), 400

    # בדיקה שהריפו קיים
    db = get_db()
    if not db.repo_metadata.find_one({"repo_name": repo_name}):
        return jsonify({
            "success": False,
            "error": "Repo not found"
        }), 404

    try:
        success = repo_manager.save_selected_repo(current_user.id, repo_name)

        return jsonify({
            "success": success,
            "repo_name": repo_name
        })
    except Exception as e:
        logger.exception(f"Select repo error: {e}")
        return jsonify({
            "success": False,
            "error": "Failed to save selection"
        }), 500

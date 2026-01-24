from __future__ import annotations

from flask import Blueprint, Response, render_template, request, session
from datetime import datetime, timezone
from pathlib import Path
from werkzeug.http import http_date
import hashlib
import json
import os
import time as _time

from webapp.activity_tracker import log_user_event

snippet_library_ui = Blueprint('snippet_library_ui', __name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_SNIPPETS_TEMPLATE = _TEMPLATES_DIR / "snippets.html"
_BASE_TEMPLATE = _TEMPLATES_DIR / "base.html"
_MANIFEST_PATH = Path(__file__).parent / "static" / "manifest.json"


def _compute_static_version_for_etag() -> str:
    candidates = (
        "ASSET_VERSION",
        "APP_VERSION",
        "RENDER_GIT_COMMIT",
        "SOURCE_VERSION",
        "GIT_COMMIT",
        "HEROKU_SLUG_COMMIT",
    )
    for name in candidates:
        value = os.getenv(name)
        if value:
            return str(value)[:8]
    try:
        if _MANIFEST_PATH.is_file():
            digest = hashlib.sha1(_MANIFEST_PATH.read_bytes()).hexdigest()  # nosec - not for security
            return digest[:8]
    except Exception:
        pass
    try:
        return str(int(_time.time() // 3600))
    except Exception:
        return "dev"


def _collect_templates_mtime() -> int:
    mtimes: list[int] = []
    for template in (_SNIPPETS_TEMPLATE, _BASE_TEMPLATE):
        try:
            if template.is_file():
                mtimes.append(int(template.stat().st_mtime))
        except Exception:
            continue
    return max(mtimes) if mtimes else 0


def _compute_snippets_page_etag(is_admin: bool) -> tuple[str, int]:
    template_mtime = _collect_templates_mtime()
    payload = json.dumps(
        {
            "admin": bool(is_admin),
            "template_mtime": template_mtime,
            "static_version": _compute_static_version_for_etag(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    tag = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f'W/"{tag}"', template_mtime


@snippet_library_ui.route('/snippets')
def snippets_page():
    # רישום פעילות "כניסה לספריית הסניפטים" (Best-effort)
    try:
        user_id = session.get('user_id')
    except Exception:
        user_id = None
    if user_id:
        username = None
        try:
            user_data = session.get('user_data') or {}
            if isinstance(user_data, dict):
                username = user_data.get('username')
        except Exception:
            username = None
        try:
            log_user_event(int(user_id), username=username)
        except Exception:
            pass

    # Determine admin from ENV list
    is_admin = False
    try:
        uid = int(session.get('user_id')) if session.get('user_id') is not None else 0
        admin_ids_env = os.getenv('ADMIN_USER_IDS', '')
        admin_ids = [int(x.strip()) for x in admin_ids_env.split(',') if x.strip().isdigit()]
        is_admin = uid in admin_ids
    except Exception:
        is_admin = False
    etag, template_mtime = _compute_snippets_page_etag(is_admin)
    inm = request.headers.get("If-None-Match")
    if inm and inm == etag:
        resp = Response(status=304)
        resp.headers["ETag"] = etag
        if template_mtime:
            resp.headers["Last-Modified"] = http_date(datetime.fromtimestamp(template_mtime, timezone.utc))
        return resp
    html = render_template('snippets.html', is_admin=is_admin)
    resp = Response(html, mimetype='text/html; charset=utf-8')
    resp.headers["ETag"] = etag
    if template_mtime:
        resp.headers["Last-Modified"] = http_date(datetime.fromtimestamp(template_mtime, timezone.utc))
    return resp


@snippet_library_ui.route('/snippets/submit')
def snippet_submit_page():
    """עמוד הגשת סניפט חדש (Web).

    מציג טופס עם: כותרת, תיאור קצר, שפה, וקטע קוד, וכפתור שליחה.
    לאחר שליחה יופיע אישור למשתמש שהסניפט ממתין לאישור מנהל.
    """
    # זיהוי משתמש מחובר (לא חובה להצגה, אבל יועיל בצד הלקוח אם צריך)
    try:
        user = session.get('user_data', {}) or {}
    except Exception:
        user = {}
    return render_template('snippet_submit.html', user=user)


@snippet_library_ui.route('/snippets/submit/thanks')
def snippet_submit_thanks_page():
    """עמוד תודה לאחר שליחת סניפט (Web)."""
    return render_template('snippet_thanks.html')

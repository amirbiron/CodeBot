from __future__ import annotations

from flask import Blueprint, jsonify, request, session
from typing import List
import logging

from cache_manager import dynamic_cache
import datetime as _dt
from services.snippet_library_service import list_public_snippets, submit_snippet as _svc_submit
from config import config as _cfg
import os as _os
import threading as _threading

try:
    # Prefer sync HTTP helper if available
    from http_sync import request as _http_request  # type: ignore
except Exception:  # pragma: no cover
    _http_request = None  # type: ignore

logger = logging.getLogger(__name__)

snippets_bp = Blueprint('snippets_api', __name__, url_prefix='/api/snippets')


def _parse_int(val: str | None, default: int, lo: int, hi: int) -> int:
    try:
        v = int(val) if val not in (None, "") else default
        return max(lo, min(hi, v))
    except Exception:
        return default


@snippets_bp.route('', methods=['GET'])
@dynamic_cache(content_type='snippets_library', key_prefix='snippets')
def get_public_snippets():
    try:
        q = request.args.get('q') or request.args.get('title')
        language = request.args.get('language') or request.args.get('lang')
        page = _parse_int(request.args.get('page'), 1, 1, 10000)
        per_page = _parse_int(request.args.get('per_page'), 30, 1, 60)
        items, total = list_public_snippets(q=q, language=language, page=page, per_page=per_page)
        # Serialize datetimes to ISO strings to avoid Flask jsonify TypeError
        def _iso(val):
            try:
                if isinstance(val, _dt.datetime):
                    return val.isoformat()
            except Exception:
                pass
            return val
        safe_items = []
        for it in items or []:
            try:
                d = dict(it)
            except Exception:
                d = {}
            if 'approved_at' in d:
                d['approved_at'] = _iso(d.get('approved_at'))
            safe_items.append(d)
        return jsonify({
            'ok': True,
            'items': safe_items,
            'page': page,
            'per_page': per_page,
            'total': total,
        })
    except Exception as e:
        try:
            logger.error("snippets_library_api_error: %s", e, exc_info=True)
        except Exception:
            pass
        return jsonify({'ok': False, 'error': 'internal_error'}), 500


@snippets_bp.route('/languages', methods=['GET'])
@dynamic_cache(content_type='snippets_library', key_prefix='snippets_languages')
def get_snippet_languages():
    """החזרת רשימת שפות נתמכות בספריית הסניפטים (distinct מתוך פריטים זמינים).

    כדי להימנע מעומס, נסרוק עד כ-1000 פריטים (60 לדף × עד 20 דפים) או עד שנגמרים הפריטים.
    """
    try:
        languages: set[str] = set()
        page = 1
        per_page = 60
        safety = 0
        while True:
            items, total = list_public_snippets(q=None, language=None, page=page, per_page=per_page)
            if not items:
                break
            for it in items:
                try:
                    lang = str(it.get('language') or '').strip()
                    if lang:
                        languages.add(lang)
                except Exception:
                    continue
            page += 1
            safety += 1
            if len(items) < per_page or safety > 20:
                break
        return jsonify({
            'ok': True,
            'languages': sorted(languages),
        })
    except Exception as e:
        try:
            logger.error("snippets_languages_api_error: %s", e, exc_info=True)
        except Exception:
            pass
        return jsonify({'ok': False, 'languages': []}), 200


def _notify_admins_new_snippet(snippet_id: str, *, title: str, language: str, username: str | None, base_url: str | None = None) -> None:
    """שליחת הודעה למנהלים על הצעת סניפט חדשה, ברקע (fire-and-forget).

    מסתמך על ENV: BOT_TOKEN, ADMIN_USER_IDS (CSV). לא מעלה חריגות.
    """
    def _worker() -> None:
        try:
            bot_token = _os.getenv('BOT_TOKEN', '')
            admins_raw = _os.getenv('ADMIN_USER_IDS', '')
            if not bot_token or not admins_raw or not snippet_id:
                return
            try:
                admin_ids = [int(x.strip()) for x in admins_raw.split(',') if x.strip().isdigit()]
            except Exception:
                admin_ids = []
            if not admin_ids:
                return
            base = (base_url or getattr(_cfg, 'PUBLIC_BASE_URL', None) or getattr(_cfg, 'WEBAPP_URL', None) or '').rstrip('/')
            view_url = f"{base}/admin/snippets/view?id={snippet_id}" if base else f"/admin/snippets/view?id={snippet_id}"
            api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "✅ אישור", "callback_data": f"snippet_approve:{snippet_id}"},
                        {"text": "❌ דחייה", "callback_data": f"snippet_reject:{snippet_id}"},
                    ],
                    [
                        {"text": "👁️ הצג סניפט", "url": view_url},
                    ],
                ]
            }
            text = (
                "🆕 הצעת סניפט חדשה\n\n"
                f"כותרת: {title}\n"
                f"שפה: {language}\n"
                f"מאת: @{(username or '').strip()}"
            )
            for aid in admin_ids:
                payload = {"chat_id": int(aid), "text": text, "reply_markup": kb}
                try:
                    if _http_request is not None:
                        _http_request('POST', api, json=payload, timeout=5)
                    else:  # pragma: no cover
                        import requests as _requests  # type: ignore
                        _requests.post(api, json=payload, timeout=5)
                except Exception:
                    continue
        except Exception:
            return

    try:
        _threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        # במקרה קצה שבו יצירת חוט נכשלת — אל תעצור את הזרימה
        pass


@snippets_bp.route('/submit', methods=['POST'])
def submit_snippet_api():
    """קבלת הצעת סניפט מהווב‑אפ, שמירה ב־DB ושליחת התראה למנהלים."""
    try:
        user_id = int(session.get('user_id') or 0)
        user = session.get('user_data', {}) or {}
    except Exception:
        user_id = 0
        user = {}
    if user_id <= 0:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}

    title = str(data.get('title') or '')
    description = str(data.get('description') or '')
    language = str(data.get('language') or '')
    code = str(data.get('code') or '')

    res = _svc_submit(title=title, description=description, code=code, language=language, user_id=int(user_id), username=(user.get('username') or None))
    if not res.get('ok'):
        # אל תחזירו פרטים טכניים למשתמש
        return jsonify({"ok": False, "error": str(res.get('error') or 'submit_failed')}), 400

    # הצלחה – שליחת התראה למנהלים ברקע (best‑effort, non-blocking)
    try:
        base = (getattr(_cfg, 'PUBLIC_BASE_URL', None) or getattr(_cfg, 'WEBAPP_URL', None) or (request.url_root or '')).rstrip('/')
    except Exception:
        base = ''
    _notify_admins_new_snippet(str(res.get('id') or ''), title=title, language=language, username=(user.get('username') or None), base_url=base)

    return jsonify({"ok": True, "id": res.get('id')})

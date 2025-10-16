#!/usr/bin/env python3
"""
Code Keeper Bot - Web Application
אפליקציית ווב לניהול וצפייה בקטעי קוד
"""

import os
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Optional, Dict, Any, List

from flask import Flask, render_template, jsonify, request, session, redirect, url_for, send_file, abort, Response
from werkzeug.http import http_date, parse_date
from flask_compress import Compress
from pymongo import MongoClient, DESCENDING
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
from bson import ObjectId
import requests
from datetime import timedelta
import re
import sys
from pathlib import Path
import secrets
import threading
import base64


# הוספת נתיב ה-root של הפרויקט ל-PYTHONPATH כדי לאפשר import ל-"database" כשהסקריפט רץ מתוך webapp/
ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# נרמול טקסט/קוד לפני שמירה (הסרת תווים נסתרים, כיווניות, אחידות שורות)
from utils import normalize_code  # noqa: E402
# Cache (Redis) – שימוש במנהל הקאש המרכזי של הפרויקט
try:
    from cache_manager import cache  # noqa: E402
except Exception:  # Fallback בטוח אם Redis לא זמין בזמן ריצה
    class _NoCache:
        is_enabled = False
        def get(self, key):
            return None
        def set(self, key, value, expire_seconds=60):
            return False
    cache = _NoCache()  # type: ignore

# יצירת האפליקציה
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.permanent_session_lifetime = timedelta(days=30)  # סשן נשמר ל-30 יום
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # שנה לסטטיקה
app.config['COMPRESS_ALGORITHM'] = ['br', 'gzip']
app.config['COMPRESS_LEVEL'] = 6
app.config['COMPRESS_BR_LEVEL'] = 5
Compress(app)

# --- Bookmarks API blueprint ---
try:
    from webapp.bookmarks_api import bookmarks_bp  # noqa: E402
    app.register_blueprint(bookmarks_bp)
except Exception:
    # אם יש כשל בייבוא (למשל בזמן דוקס/CI בלי תלותים), אל תפיל את השרת
    pass

# הגדרות
MONGODB_URL = os.getenv('MONGODB_URL')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'code_keeper_bot')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'my_code_keeper_bot')
BOT_USERNAME_CLEAN = (BOT_USERNAME or '').lstrip('@')
WEBAPP_URL = os.getenv('WEBAPP_URL', 'https://code-keeper-webapp.onrender.com')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '')
_ttl_env = os.getenv('PUBLIC_SHARE_TTL_DAYS', '7')
FA_SRI_HASH = (os.getenv('FA_SRI_HASH') or '').strip()
# URL בסיסי לתיעוד (לשימוש בקישורי עזרה מה-UI)
# מנרמל תמיד לסלאש מסיים כדי למנוע חיבור URL שבור
_DOCS_URL_RAW = (os.getenv('DOCUMENTATION_URL') or 'https://amirbiron.github.io/CodeBot/')
DOCUMENTATION_URL = (_DOCS_URL_RAW.rstrip('/') + '/')

# --- Cache TTLs (seconds) for heavy endpoints/pages ---
def _int_env(name: str, default: int, lo: int = 30, hi: int = 180) -> int:
    try:
        val = int(os.getenv(name, str(default)))
        return max(lo, min(hi, val))
    except Exception:
        return default

FILES_PAGE_CACHE_TTL = _int_env('FILES_PAGE_CACHE_TTL', 90, lo=30, hi=180)
MD_PREVIEW_CACHE_TTL = _int_env('MD_PREVIEW_CACHE_TTL', 120, lo=60, hi=180)
API_STATS_CACHE_TTL = _int_env('API_STATS_CACHE_TTL', 120, lo=60, hi=180)

# --- External uptime monitoring (Option 2 from issue #730) ---
# Provider options: 'betteruptime' (Better Stack), 'uptimerobot', 'statuscake', 'pingdom'
UPTIME_PROVIDER = (os.getenv('UPTIME_PROVIDER') or '').strip().lower()  # e.g., 'betteruptime'
UPTIME_API_KEY = os.getenv('UPTIME_API_KEY', '')
UPTIME_MONITOR_ID = os.getenv('UPTIME_MONITOR_ID', '')
# Public status page URL (if you have one externally)
UPTIME_STATUS_URL = os.getenv('UPTIME_STATUS_URL', '')
# Optional widget (Better Uptime / Better Stack announcement widget)
UPTIME_WIDGET_SCRIPT_URL = os.getenv('UPTIME_WIDGET_SCRIPT_URL', 'https://uptime.betterstack.com/widgets/announcement.js')
UPTIME_WIDGET_ID = os.getenv('UPTIME_WIDGET_ID', '')  # the widget data-id
# Cache TTL (seconds) for external uptime API calls
try:
    UPTIME_CACHE_TTL_SECONDS = max(30, int(os.getenv('UPTIME_CACHE_TTL_SECONDS', '120')))
except Exception:
    UPTIME_CACHE_TTL_SECONDS = 120
try:
    PUBLIC_SHARE_TTL_DAYS = max(1, int(_ttl_env))
except Exception:
    PUBLIC_SHARE_TTL_DAYS = 7

# ברירת מחדל לימי שהות בסל מחזור עבור מחיקה רכה בווב
try:
    RECYCLE_TTL_DAYS_DEFAULT = max(1, int(os.getenv('RECYCLE_TTL_DAYS', '7') or '7'))
except Exception:
    RECYCLE_TTL_DAYS_DEFAULT = 7

# הגדרת חיבור קבוע (Remember Me)
try:
    PERSISTENT_LOGIN_DAYS = max(30, int(os.getenv('PERSISTENT_LOGIN_DAYS', '180')))
except Exception:
    PERSISTENT_LOGIN_DAYS = 180
REMEMBER_COOKIE_NAME = 'remember_me'

 

# חיבור ל-MongoDB
client = None
db = None
@app.context_processor
def inject_globals():
    """הזרקת משתנים גלובליים לכל התבניות"""
    # קביעת גודל גופן מהעדפות משתמש/קוקי
    font_scale = 1.0
    try:
        # Cookie קודם
        cookie_val = request.cookies.get('ui_font_scale')
        if cookie_val:
            try:
                v = float(cookie_val)
                if 0.85 <= v <= 1.6:
                    font_scale = v
            except Exception:
                pass
        # אם מחובר - העדפת DB גוברת
        if 'user_id' in session:
            try:
                _db = get_db()
                u = _db.users.find_one({'user_id': session['user_id']}) or {}
                v = float(((u.get('ui_prefs') or {}).get('font_scale')) or font_scale)
                if 0.85 <= v <= 1.6:
                    font_scale = v
            except Exception:
                pass
    except Exception:
        pass
    # ערכת נושא
    theme = 'classic'
    try:
        cookie_theme = (request.cookies.get('ui_theme') or '').strip().lower()
        if cookie_theme:
            theme = cookie_theme
        if 'user_id' in session:
            try:
                _db = get_db()
                u = _db.users.find_one({'user_id': session['user_id']}) or {}
                t = ((u.get('ui_prefs') or {}).get('theme') or '').strip().lower()
                if t:
                    theme = t
            except Exception:
                pass
    except Exception:
        pass
    if theme not in {'classic','ocean','forest'}:
        theme = 'classic'
    # SRI map (optional): only set if provided via env to avoid mismatches
    sri_map = {}
    try:
        if FA_SRI_HASH:
            sri_map['fa'] = FA_SRI_HASH
    except Exception:
        sri_map = {}

    return {
        'bot_username': BOT_USERNAME_CLEAN,
        'ui_font_scale': font_scale,
        'ui_theme': theme,
        # קישור לתיעוד (לשימוש בתבניות)
        'documentation_url': DOCUMENTATION_URL,
        # External uptime config for templates (non-sensitive only)
        'uptime_provider': UPTIME_PROVIDER,
        'uptime_status_url': UPTIME_STATUS_URL,
        'uptime_widget_script_url': UPTIME_WIDGET_SCRIPT_URL,
        'uptime_widget_id': UPTIME_WIDGET_ID,
        # SRI hashes for CDN assets (optional; provided via env)
        'cdn_sri': sri_map if sri_map else None,
    }

 


def get_db():
    """מחזיר חיבור למסד הנתונים"""
    global client, db
    if client is None:
        if not MONGODB_URL:
            raise Exception("MONGODB_URL is not configured")
        try:
            # החזר אובייקטי זמן tz-aware כדי למנוע השוואות naive/aware
            client = MongoClient(
                MONGODB_URL,
                serverSelectionTimeoutMS=5000,
                tz_aware=True,
                tzinfo=timezone.utc,
            )
            # בדיקת חיבור
            client.server_info()
            db = client[DATABASE_NAME]
            # קריאה חד-פעמית להבטחת אינדקסים באוספים
            try:
                ensure_recent_opens_indexes()
            except Exception:
                pass
            try:
                ensure_code_snippets_indexes()
            except Exception:
                pass
        except Exception as e:
            print(f"Failed to connect to MongoDB: {e}")
            raise
    return db

# --- Ensure indexes for recent_opens once per process ---
_recent_opens_indexes_ready = False

def ensure_recent_opens_indexes() -> None:
    """יוצר אינדקסים נחוצים לאוסף recent_opens פעם אחת בתהליך."""
    global _recent_opens_indexes_ready
    if _recent_opens_indexes_ready:
        return
    try:
        _db = get_db()
        coll = _db.recent_opens
        try:
            from pymongo import ASCENDING, DESCENDING
            coll.create_index([('user_id', ASCENDING), ('file_name', ASCENDING)], name='user_file_unique', unique=True)
            coll.create_index([('user_id', ASCENDING), ('last_opened_at', DESCENDING)], name='user_last_opened_idx')
        except Exception:
            # גם אם יצירת אינדקס נכשלה, לא נכשיל את היישום
            pass
        _recent_opens_indexes_ready = True
    except Exception:
        # אין להפיל את השרת במקרה של בעיית DB בתחילת חיים
        pass


# --- HTTP caching helpers (ETag / Last-Modified) ---
def _safe_dt_from_doc(value) -> datetime:
    """Normalize a datetime-like value from Mongo into tz-aware datetime (UTC)."""
    try:
        if isinstance(value, datetime):
            dt = value
        elif value is not None:
            # ISO string or other repr
            dt = datetime.fromisoformat(str(value))
        else:
            dt = datetime.now(timezone.utc)
    except Exception:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _compute_file_etag(doc: Dict[str, Any]) -> str:
    """Compute a weak ETag for a file document based on updated_at and raw content.

    We intentionally include only fields that impact the rendered output to keep
    the validator stable but sensitive to relevant changes.
    """
    try:
        updated_at = doc.get('updated_at')
        if isinstance(updated_at, datetime):
            updated_str = updated_at.isoformat()
        elif updated_at is not None:
            updated_str = str(updated_at)
        else:
            updated_str = ''
    except Exception:
        updated_str = ''
    raw_code = (doc.get('code') or '')
    file_name = (doc.get('file_name') or '')
    version = str(doc.get('version') or '')
    # Hash a compact JSON string of identifying fields + content digest
    try:
        payload = json.dumps({
            'u': updated_str,
            'n': file_name,
            'v': version,
            'sha': hashlib.sha256(raw_code.encode('utf-8')).hexdigest(),
        }, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        tag = hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]
        return f'W/"{tag}"'
    except Exception:
        # Fallback: time-based weak tag
        return f'W/"{int(time.time())}"'


# --- Ensure indexes for code_snippets once per process ---
_code_snippets_indexes_ready = False

def ensure_code_snippets_indexes() -> None:
    """יוצר אינדקסים קריטיים עבור אוסף code_snippets פעם אחת בתהליך.

    אינדקסים:
    - (user_id, created_at)
    - (user_id, programming_language)
    - (user_id, tags)
    - (user_id, is_favorite)
    - Text index על (file_name, description, tags) – אם אין כבר.
    """
    global _code_snippets_indexes_ready
    if _code_snippets_indexes_ready:
        return
    try:
        _db = get_db()
        coll = _db.code_snippets
        try:
            from pymongo import ASCENDING, DESCENDING
            # זוגות פשוטים
            try:
                coll.create_index([('user_id', ASCENDING), ('created_at', DESCENDING)], name='user_created_at', background=True)
            except Exception:
                pass
            try:
                coll.create_index([('user_id', ASCENDING), ('programming_language', ASCENDING)], name='user_lang', background=True)
            except Exception:
                pass
            try:
                coll.create_index([('user_id', ASCENDING), ('tags', ASCENDING)], name='user_tags', background=True)
            except Exception:
                pass
            try:
                coll.create_index([('user_id', ASCENDING), ('is_favorite', ASCENDING)], name='user_favorite', background=True)
            except Exception:
                pass

            # Text index – רק אם לא קיים כבר אינדקס מסוג text
            try:
                has_text = False
                try:
                    for ix in coll.list_indexes():
                        for k, spec in ix.to_dict().get('key', {}).items():
                            if str(spec).lower() == 'text':
                                has_text = True
                                break
                        if has_text:
                            break
                except Exception:
                    # Fallback ל-index_information()
                    try:
                        for _name, info in (coll.index_information() or {}).items():
                            key = info.get('key') or []
                            for pair in key:
                                if isinstance(pair, (list, tuple)) and len(pair) >= 2 and str(pair[1]).lower() == 'text':
                                    has_text = True
                                    break
                            if has_text:
                                break
                    except Exception:
                        has_text = False
                if not has_text:
                    coll.create_index([
                        ('file_name', 'text'),
                        ('description', 'text'),
                        ('tags', 'text'),
                    ], name='text_file_desc_tags', background=True)
            except Exception:
                pass
        except Exception:
            # אם pymongo לא נטען/סביבת Docs – לא נכשיל
            pass
        _code_snippets_indexes_ready = True
    except Exception:
        # אין להפיל את האפליקציה במקרה של בעיית DB בתחילת חיים
        pass

# (הוסר שימוש ב-before_first_request; ראה הקריאה בתוך get_db למניעת שגיאה בפלאסק 3)


# --- Cursor encoding helpers for pagination ---
def _encode_cursor(created_at: datetime, oid: ObjectId) -> str:
    try:
        dt = created_at if isinstance(created_at, datetime) else _safe_dt_from_doc(created_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts = int(dt.timestamp())
    except Exception:
        ts = int(time.time())
    try:
        raw = json.dumps({'t': ts, 'id': str(oid)}, separators=(',', ':'), sort_keys=True).encode('utf-8')
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')
    except Exception:
        return ''


def _decode_cursor(cursor: str) -> tuple[datetime | None, ObjectId | None]:
    if not cursor:
        return (None, None)
    try:
        padding = '=' * (-len(cursor) % 4)
        data = base64.urlsafe_b64decode((cursor + padding).encode('ascii'))
        obj = json.loads(data.decode('utf-8'))
        ts = int(obj.get('t'))
        oid_str = str(obj.get('id') or '')
        last_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        last_oid = ObjectId(oid_str) if oid_str else None
        return (last_dt, last_oid)
    except Exception:
        return (None, None)

# --- Simple in-process cache for external uptime calls ---
_uptime_cache_lock = threading.Lock()
_uptime_cache: Dict[str, Any] = {
    'data': None,
    'provider': None,
    'fetched_at': 0.0,
}

def _get_uptime_cached() -> Optional[Dict[str, Any]]:
    now_ts = time.time()
    with _uptime_cache_lock:
        data = _uptime_cache.get('data')
        ts = float(_uptime_cache.get('fetched_at') or 0)
        if data and (now_ts - ts) < UPTIME_CACHE_TTL_SECONDS:
            return data
    return None

def _set_uptime_cache(payload: Dict[str, Any]) -> None:
    with _uptime_cache_lock:
        _uptime_cache['data'] = payload
        _uptime_cache['provider'] = UPTIME_PROVIDER
        _uptime_cache['fetched_at'] = time.time()

def _fetch_uptime_from_betteruptime() -> Optional[Dict[str, Any]]:
    if not (UPTIME_API_KEY and UPTIME_MONITOR_ID):
        return None
    try:
        # SLA endpoint per issue suggestion
        url = f'https://uptime.betterstack.com/api/v2/monitors/{UPTIME_MONITOR_ID}/sla'
        headers = {'Authorization': f'Bearer {UPTIME_API_KEY}'}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
        body = resp.json() if resp.content else {}
        # Normalize output
        availability = None
        try:
            availability = float(((body or {}).get('data') or {}).get('availability'))
        except Exception:
            availability = None
        result = {
            'provider': 'betteruptime',
            'uptime_percentage': round(availability, 2) if isinstance(availability, (int, float)) else None,
            'raw': body,
            'status_url': UPTIME_STATUS_URL or None,
        }
        return result
    except Exception:
        return None

def _fetch_uptime_from_uptimerobot() -> Optional[Dict[str, Any]]:
    """Fetch uptime from UptimeRobot.

    Notes:
    - UptimeRobot v2 מחזיר שדה custom_uptime_ratios (לא ranges) כשמבקשים יחסי זמינות
      עבור X ימים אחרונים. ערך '1' משמע 24 שעות אחרונות.
    - נתמוך גם ב-custom_uptime_ranges אם יוחזר (תאימות עתידית/ישנה).
    """
    if not UPTIME_API_KEY:
        return None
    try:
        url = 'https://api.uptimerobot.com/v2/getMonitors'
        payload = {
            'api_key': UPTIME_API_KEY,
            # יחס זמינות ל-1 יום (24 שעות)
            'custom_uptime_ratios': '1',
            'format': 'json',
        }
        # אם זה לא מפתח monitor‑specific (שמתחיל ב-'m'), ונמסר מזהה monitor – נשלח אותו
        try:
            api_key_is_monitor_specific = str(UPTIME_API_KEY).strip().lower().startswith('m')
        except Exception:
            api_key_is_monitor_specific = False
        if UPTIME_MONITOR_ID and not api_key_is_monitor_specific:
            payload['monitors'] = UPTIME_MONITOR_ID
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code != 200:
            return None
        body = resp.json() if resp.content else {}
        monitors = (body or {}).get('monitors') or []
        uptime_percentage = None
        if (body or {}).get('stat') == 'fail':
            return None
        if monitors:
            # נסה את כל הוריאציות הידועות
            val = (
                monitors[0].get('custom_uptime_ratio') or
                monitors[0].get('custom_uptime_ratios') or
                monitors[0].get('custom_uptime_range') or
                monitors[0].get('custom_uptime_ranges')
            )
            try:
                if isinstance(val, str):
                    # custom_uptime_ratios יכול להיות "99.99" או "99.99-..." – ניקח את הראשון
                    first = val.split('-')[0].strip()
                    uptime_percentage = round(float(first), 2)
                elif isinstance(val, (int, float)):
                    uptime_percentage = round(float(val), 2)
            except Exception:
                uptime_percentage = None
        return {
            'provider': 'uptimerobot',
            'uptime_percentage': uptime_percentage,
            'raw': body,
            'status_url': UPTIME_STATUS_URL or None,
        }
    except Exception:
        return None

def fetch_external_uptime() -> Optional[Dict[str, Any]]:
    """Fetch uptime according to configured provider with basic caching."""
    # Return from cache if fresh
    cached = _get_uptime_cached()
    if cached is not None:
        return cached
    result: Optional[Dict[str, Any]] = None
    provider = (UPTIME_PROVIDER or '').strip().lower()
    if provider == 'betteruptime':
        result = _fetch_uptime_from_betteruptime()
    elif provider == 'uptimerobot':
        result = _fetch_uptime_from_uptimerobot()
    elif provider in {'statuscake', 'pingdom'}:
        # Not implemented: fall back to None to avoid errors
        result = None
    if result is not None:
        _set_uptime_cache(result)
    return result

def get_internal_share(share_id: str) -> Optional[Dict[str, Any]]:
    """שליפת שיתוף פנימי מה-DB (internal_shares) עם בדיקת תוקף."""
    try:
        db = get_db()
        coll = db.internal_shares
        doc = coll.find_one({"share_id": share_id})
        if not doc:
            return None
        # TTL אמור לטפל במחיקה, אבל אם עדיין לא נמחק — נבדוק תוקף ידנית באופן חסין tz
        exp = doc.get("expires_at")
        if isinstance(exp, datetime):
            exp_aware = exp if exp.tzinfo is not None else exp.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            if exp_aware < now_utc:
                return None
        elif isinstance(exp, str):
            try:
                exp_dt = datetime.fromisoformat(exp)
                exp_aware = exp_dt if exp_dt.tzinfo is not None else exp_dt.replace(tzinfo=timezone.utc)
                if exp_aware < datetime.now(timezone.utc):
                    return None
            except Exception:
                pass
        try:
            coll.update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}})
        except Exception:
            pass
        return doc
    except Exception as e:
        print(f"Error fetching internal share: {e}")
        return None

# Telegram Login Widget Verification
def verify_telegram_auth(auth_data: Dict[str, Any]) -> bool:
    """מאמת את הנתונים מ-Telegram Login Widget"""
    check_hash = auth_data.get('hash')
    if not check_hash:
        return False
    
    # יצירת data-check-string
    data_items = []
    for key, value in sorted(auth_data.items()):
        if key != 'hash':
            data_items.append(f"{key}={value}")
    
    data_check_string = '\n'.join(data_items)
    
    # חישוב hash
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # בדיקת תוקף
    if calculated_hash != check_hash:
        return False
    
    # בדיקת זמן (עד שעה מהחתימה)
    auth_date = int(auth_data.get('auth_date', 0))
    if (time.time() - auth_date) > 3600:
        return False
    
    return True

def login_required(f):
    """דקורטור לבדיקת התחברות"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# before_request: אם אין סשן אבל יש cookie "remember_me" תקף — נבצע התחברות שקופה
@app.before_request
def try_persistent_login():
    try:
        if 'user_id' in session:
            return
        token = request.cookies.get(REMEMBER_COOKIE_NAME)
        if not token:
            return
        db = get_db()
        doc = db.remember_tokens.find_one({
            'token': token
        })
        if not doc:
            return
        # בדיקת תוקף
        exp = doc.get('expires_at')
        now = datetime.now(timezone.utc)
        if isinstance(exp, datetime):
            if exp < now:
                return
        else:
            try:
                if datetime.fromisoformat(str(exp)) < now:
                    return
            except Exception:
                return
        # שחזור סשן בסיסי
        user_id = int(doc.get('user_id'))
        user = db.users.find_one({'user_id': user_id}) or {}
        session['user_id'] = user_id
        session['user_data'] = {
            'id': user_id,
            'first_name': user.get('first_name', ''),
            'last_name': user.get('last_name', ''),
            'username': user.get('username', ''),
            'photo_url': ''
        }
        session.permanent = True
    except Exception:
        # אל תכשיל בקשות בגלל כשל חיבור/פרסר
        pass

def admin_required(f):
    """דקורטור לבדיקת הרשאות אדמין"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        # בדיקה אם המשתמש הוא אדמין
        admin_ids = os.getenv('ADMIN_USER_IDS', '').split(',')
        admin_ids = [int(id.strip()) for id in admin_ids if id.strip().isdigit()]
        
        if session['user_id'] not in admin_ids:
            abort(403)  # Forbidden
        
        return f(*args, **kwargs)
    return decorated_function

def is_admin(user_id: int) -> bool:
    """בודק אם משתמש הוא אדמין"""
    admin_ids = os.getenv('ADMIN_USER_IDS', '').split(',')
    admin_ids = [int(id.strip()) for id in admin_ids if id.strip().isdigit()]
    return user_id in admin_ids


def format_file_size(size_bytes: int) -> str:
    """מעצב גודל קובץ לתצוגה ידידותית"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

def is_binary_file(content: str, filename: str = "") -> bool:
    """בודק אם קובץ הוא בינארי"""
    # רשימת סיומות בינאריות
    binary_extensions = {
        '.exe', '.dll', '.so', '.dylib', '.bin', '.dat',
        '.pdf', '.doc', '.docx', '.xls', '.xlsx',
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.ico',
        '.mp3', '.mp4', '.avi', '.mov', '.wav',
        '.zip', '.rar', '.7z', '.tar', '.gz',
        '.pyc', '.pyo', '.class', '.o', '.a'
    }
    
    # בדיקה לפי סיומת
    if filename:
        ext = os.path.splitext(filename.lower())[1]
        if ext in binary_extensions:
            return True
    
    # בדיקה לפי תוכן
    if content:
        try:
            # נסיון לקרוא כ-UTF-8
            if isinstance(content, bytes):
                content.decode('utf-8')
            # בדיקת תווים בינאריים
            null_count = content.count('\0') if isinstance(content, str) else content.count(b'\0')
            if null_count > 0:
                return True
        except UnicodeDecodeError:
            return True
    
    return False

def get_language_icon(language: str) -> str:
    """מחזיר אייקון עבור שפת תכנות"""
    icons = {
        'python': '🐍',
        'javascript': '📜',
        'typescript': '📘',
        'java': '☕',
        'cpp': '⚙️',
        'c': '🔧',
        'csharp': '🎯',
        'go': '🐹',
        'rust': '🦀',
        'ruby': '💎',
        'php': '🐘',
        'swift': '🦉',
        'kotlin': '🎨',
        'html': '🌐',
        'css': '🎨',
        'sql': '🗄️',
        'bash': '🖥️',
        'shell': '🐚',
        'dockerfile': '🐳',
        'yaml': '📋',
        'json': '📊',
        'xml': '📄',
        'markdown': '📝',
    }
    return icons.get(language.lower(), '📄')

# עיצוב תאריך בטוח לתצוגה ללא נפילה לברירת מחדל של עכשיו
def format_datetime_display(value) -> str:
    try:
        if isinstance(value, datetime):
            dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
            return dt.strftime('%d/%m/%Y %H:%M')
        if isinstance(value, str) and value:
            try:
                dtp = datetime.fromisoformat(value)
                dtp = dtp if dtp.tzinfo is not None else dtp.replace(tzinfo=timezone.utc)
                return dtp.strftime('%d/%m/%Y %H:%M')
            except Exception:
                return ''
        return ''
    except Exception:
        return ''
# Routes

@app.route('/')
def index():
    """דף הבית"""
    # Try resolve external uptime (non-blocking semantics: short timeout + cache inside helper)
    uptime_summary: Optional[Dict[str, Any]] = None
    try:
        uptime_summary = fetch_external_uptime()
    except Exception:
        uptime_summary = None
    return render_template(
        'index.html',
        bot_username=BOT_USERNAME_CLEAN,
        logged_in=('user_id' in session),
        user=session.get('user_data', {}),
        uptime=uptime_summary,
    )

@app.route('/login')
def login():
    """דף התחברות"""
    return render_template('login.html', bot_username=BOT_USERNAME_CLEAN)

@app.route('/auth/telegram', methods=['GET', 'POST'])
def telegram_auth():
    """טיפול באימות Telegram"""
    auth_data = dict(request.args) if request.method == 'GET' else request.get_json()
    
    if not verify_telegram_auth(auth_data):
        return jsonify({'error': 'Invalid authentication'}), 401
    
    # שמירת נתוני המשתמש בסשן
    user_id = int(auth_data['id'])
    session['user_id'] = user_id
    session['user_data'] = {
        'id': user_id,
        'first_name': auth_data.get('first_name', ''),
        'last_name': auth_data.get('last_name', ''),
        'username': auth_data.get('username', ''),
        'photo_url': auth_data.get('photo_url', '')
    }
    
    # הפוך את הסשן לקבוע לכל המשתמשים (30 יום)
    session.permanent = True
    
    # אפשר להוסיף כאן הגדרות נוספות לאדמינים בעתיד
    
    return redirect(url_for('dashboard'))

@app.route('/auth/token')
def token_auth():
    """טיפול באימות עם טוקן מהבוט"""
    token = request.args.get('token')
    user_id = request.args.get('user_id')
    
    if not token or not user_id:
        return render_template('404.html'), 404
    
    try:
        db = get_db()
        # חיפוש הטוקן במסד נתונים
        token_doc = db.webapp_tokens.find_one({
            'token': token,
            'user_id': int(user_id)
        })
        
        if not token_doc:
            return render_template('login.html', 
                                 bot_username=BOT_USERNAME_CLEAN,
                                 error="קישור ההתחברות לא תקף או פג תוקפו")
        
        # בדיקת תוקף
        if token_doc['expires_at'] < datetime.now(timezone.utc):
            # מחיקת טוקן שפג תוקפו
            db.webapp_tokens.delete_one({'_id': token_doc['_id']})
            return render_template('login.html', 
                                 bot_username=BOT_USERNAME_CLEAN,
                                 error="קישור ההתחברות פג תוקף. אנא בקש קישור חדש מהבוט.")
        
        # מחיקת הטוקן לאחר שימוש (חד פעמי)
        db.webapp_tokens.delete_one({'_id': token_doc['_id']})
        
        # שליפת פרטי המשתמש
        user = db.users.find_one({'user_id': int(user_id)})
        
        # שמירת נתוני המשתמש בסשן
        user_id_int = int(user_id)
        session['user_id'] = user_id_int
        session['user_data'] = {
            'id': user_id_int,
            'first_name': user.get('first_name', ''),
            'last_name': user.get('last_name', ''),
            'username': token_doc.get('username', ''),
            'photo_url': ''
        }
        
        # הפוך את הסשן לקבוע לכל המשתמשים (30 יום)
        session.permanent = True
        
        # אפשר להוסיף כאן הגדרות נוספות לאדמינים בעתיד
        
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"Error in token auth: {e}")
        return render_template('login.html', 
                             bot_username=BOT_USERNAME_CLEAN,
                             error="שגיאה בהתחברות. אנא נסה שנית.")

@app.route('/logout')
def logout():
    """התנתקות"""
    try:
        token = request.cookies.get(REMEMBER_COOKIE_NAME)
        if token:
            try:
                db = get_db()
                db.remember_tokens.delete_one({'token': token})
            except Exception:
                pass
    except Exception:
        pass
    resp = redirect(url_for('index'))
    try:
        resp.delete_cookie(REMEMBER_COOKIE_NAME)
    except Exception:
        pass
    session.clear()
    return resp

@app.route('/dashboard')
@login_required
def dashboard():
    """דשבורד עם סטטיסטיקות"""
    try:
        db = get_db()
        user_id = session['user_id']
        
        # שליפת סטטיסטיקות - רק קבצים פעילים
        active_query = {
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        total_files = db.code_snippets.count_documents(active_query)
        
        # חישוב נפח כולל
        pipeline = [
            {'$match': {
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }},
            {'$project': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$group': {
                '_id': None,
                'total_size': {'$sum': '$code_size'}
            }}
        ]
        size_result = list(db.code_snippets.aggregate(pipeline))
        total_size = size_result[0]['total_size'] if size_result else 0
        
        # שפות פופולריות
        languages_pipeline = [
            {'$match': {
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }},
            {'$group': {
                '_id': '$programming_language',
                'count': {'$sum': 1}
            }},
            {'$sort': {'count': -1}},
            {'$limit': 5}
        ]
        top_languages = list(db.code_snippets.aggregate(languages_pipeline))
        
        # פעילות אחרונה
        recent_files = list(db.code_snippets.find(
            {
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            },
            {'file_name': 1, 'programming_language': 1, 'created_at': 1}
        ).sort('created_at', DESCENDING).limit(5))
        
        # עיבוד הנתונים לתצוגה
        for file in recent_files:
            file['_id'] = str(file['_id'])
            file['icon'] = get_language_icon(file.get('programming_language', ''))
            if 'created_at' in file:
                file['created_at_formatted'] = file['created_at'].strftime('%d/%m/%Y %H:%M')
        
        stats = {
            'total_files': total_files,
            'total_size': format_file_size(total_size),
            'top_languages': [
                {
                    'name': lang['_id'] or 'לא מוגדר',
                    'count': lang['count'],
                    'icon': get_language_icon(lang['_id'] or '')
                }
                for lang in top_languages
            ],
            'recent_files': recent_files
        }
        
        return render_template('dashboard.html', 
                             user=session['user_data'],
                             stats=stats,
                             bot_username=BOT_USERNAME_CLEAN)
                             
    except Exception as e:
        print(f"Error in dashboard: {e}")
        import traceback
        traceback.print_exc()
        # נסה להציג דשבורד ריק במקרה של שגיאה
        return render_template('dashboard.html', 
                             user=session.get('user_data', {}),
                             stats={
                                 'total_files': 0,
                                 'total_size': '0 B',
                                 'top_languages': [],
                                 'recent_files': []
                             },
                             error="אירעה שגיאה בטעינת הנתונים. אנא נסה שוב.",
                             bot_username=BOT_USERNAME_CLEAN)

@app.route('/files')
@login_required
def files():
    """רשימת כל הקבצים של המשתמש"""
    db = get_db()
    user_id = session['user_id']
    # --- Cache: בדיקת HTML שמור לפי משתמש ופרמטרים ---
    should_cache = getattr(cache, 'is_enabled', False)
    
    # פרמטרים לחיפוש ומיון
    search_query = request.args.get('q', '')
    language_filter = request.args.get('lang', '')
    category_filter = request.args.get('category', '')
    sort_by = request.args.get('sort', 'created_at')
    repo_name = request.args.get('repo', '').strip()
    page = int(request.args.get('page', 1))
    cursor_token = (request.args.get('cursor') or '').strip()
    per_page = 20
    # הכנת מפתח Cache ייחודי לפרמטרים
    try:
        _params = {
            'q': search_query,
            'lang': language_filter,
            'category': category_filter,
            'sort': sort_by,
            'repo': repo_name,
            'page': page,
            'cursor': (cursor_token[:32] if cursor_token else ''),
        }
        _raw = json.dumps(_params, sort_keys=True, ensure_ascii=False)
        _hash = hashlib.sha256(_raw.encode('utf-8')).hexdigest()[:24]
        files_cache_key = f"web:files:user:{user_id}:{_hash}"
    except Exception:
        files_cache_key = f"web:files:user:{user_id}:fallback"

    if should_cache:
        try:
            cached_html = cache.get(files_cache_key)
            if isinstance(cached_html, str) and cached_html:
                return cached_html
        except Exception:
            pass
    # ברירת מחדל למיון בקטגוריית "נפתחו לאחרונה": לפי זמן פתיחה אחרון
    try:
        if (category_filter or '').strip().lower() == 'recent' and not (request.args.get('sort') or '').strip():
            sort_by = '-last_opened_at'
    except Exception:
        pass
    
    # בניית שאילתה - כולל סינון קבצים פעילים בלבד
    query = {
        'user_id': user_id,
        '$and': [
            {
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}  # תמיכה בקבצים ישנים ללא השדה
                ]
            }
        ]
    }
    
    if search_query:
        query['$and'].append(
            {'$or': [
                {'file_name': {'$regex': search_query, '$options': 'i'}},
                {'description': {'$regex': search_query, '$options': 'i'}},
                {'tags': {'$in': [search_query.lower()]}}
            ]}
        )
    
    if language_filter:
        query['programming_language'] = language_filter
    
    # סינון לפי קטגוריה
    if category_filter:
        if category_filter == 'repo':
            # תצוגת "לפי ריפו":
            # אם נבחר ריפו ספציפי -> מסנן לקבצים של אותו ריפו; אחרת -> נציג רשימת ריפואים ונחזור מיד
            if repo_name:
                query['$and'].append({'tags': f'repo:{repo_name}'})
            else:
                # הפקה של רשימת ריפואים מתוך תגיות שמתחילות ב- repo:
                # חשוב: לא מושפעת מחיפוש/שפה כדי להציג את כל הריפואים של המשתמש
                base_active_query = {
                    'user_id': user_id,
                    '$or': [
                        {'is_active': True},
                        {'is_active': {'$exists': False}}
                    ]
                }
                # מיישר ללוגיקה של הבוט: קבוצה לפי file_name (הגרסה האחרונה בלבד), ואז חילוץ תגית repo: אחת
                repo_pipeline = [
                    {'$match': base_active_query},
                    {'$sort': {'file_name': 1, 'version': -1}},
                    {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
                    {'$replaceRoot': {'newRoot': '$latest'}},
                    {'$match': {'tags': {'$elemMatch': {'$regex': r'^repo:', '$options': 'i'}}}},
                    {'$project': {
                        'repo_tag': {
                            '$arrayElemAt': [
                                {
                                    '$filter': {
                                        'input': '$tags',
                                        'as': 't',
                                        'cond': {'$regexMatch': {'input': '$$t', 'regex': '^repo:', 'options': 'i'}}
                                    }
                                },
                                -1
                            ]
                        }
                    }},
                    {'$group': {'_id': '$repo_tag', 'count': {'$sum': 1}}},
                    {'$sort': {'_id': 1}},
                ]
                repos_raw = list(db.code_snippets.aggregate(repo_pipeline))
                repos_list = []
                for r in repos_raw:
                    try:
                        repo_full = str(r.get('_id') or '')
                        # strip leading 'repo:' if present
                        name = repo_full.split(':', 1)[1] if ':' in repo_full else repo_full
                        repos_list.append({'name': name, 'count': int(r.get('count') or 0)})
                    except Exception:
                        continue
                # רשימת שפות לפילטר - רק מקבצים פעילים
                languages = db.code_snippets.distinct(
                    'programming_language',
                    {
                        'user_id': user_id,
                        '$or': [
                            {'is_active': True},
                            {'is_active': {'$exists': False}}
                        ]
                    }
                )
                languages = sorted([lang for lang in languages if lang]) if languages else []
                html = render_template('files.html',
                                     user=session['user_data'],
                                     files=[],
                                     repos=repos_list,
                                     total_count=len(repos_list),
                                     languages=languages,
                                     search_query=search_query,
                                     language_filter=language_filter,
                                     category_filter=category_filter,
                                     selected_repo='',
                                     sort_by=sort_by,
                                     page=1,
                                     total_pages=1,
                                     has_prev=False,
                                     has_next=False,
                                     bot_username=BOT_USERNAME_CLEAN)
                if should_cache:
                    try:
                        cache.set(files_cache_key, html, FILES_PAGE_CACHE_TTL)
                    except Exception:
                        pass
                return html
        elif category_filter == 'zip':
            # הוסר מה‑UI; נשיב מיד לרשימת קבצים רגילה כדי למנוע שימוש ב‑Mongo לאחסון גיבויים
            return redirect(url_for('files'))
        elif category_filter == 'large':
            # קבצים גדולים (מעל 100KB)
            # נצטרך להוסיף שדה size אם אין
            pipeline = [
                {'$match': query},
                {'$addFields': {
                    'code_size': {
                        '$cond': {
                            'if': {'$and': [
                                {'$ne': ['$code', None]},
                                {'$eq': [{'$type': '$code'}, 'string']}
                            ]},
                            'then': {'$strLenBytes': '$code'},
                            'else': 0
                        }
                    }
                }},
                {'$match': {'code_size': {'$gte': 102400}}}  # 100KB
            ]
            # נשתמש ב-aggregation במקום find רגיל
            files_cursor = db.code_snippets.aggregate(pipeline + [
                {'$sort': {sort_by.lstrip('-'): -1 if sort_by.startswith('-') else 1}},
                {'$skip': (page - 1) * per_page},
                {'$limit': per_page}
            ])
            count_result = list(db.code_snippets.aggregate(pipeline + [{'$count': 'total'}]))
            total_count = count_result[0]['total'] if count_result else 0
        elif category_filter == 'favorites':
            # קטגוריית "מועדפים" – השתמש בשדה is_favorite
            query['$and'].append({'is_favorite': True})
        elif category_filter == 'other':
            # שאר הקבצים (לא מסומנים כריפו/גיטהאב, לא ZIP)
            query['$and'].append({
                '$nor': [
                    {'tags': 'source:github'},
                    {'tags': {'$elemMatch': {'$regex': r'^repo:', '$options': 'i'}}}
                ]
            })
            query['$and'].append({'file_name': {'$not': {'$regex': r'\.zip$', '$options': 'i'}}})
            query['$and'].append({'is_archive': {'$ne': True}})
        elif category_filter == 'recent':
            # תצוגת "נפתחו לאחרונה" – נשתמש באוסף recent_opens
            # נחזיר מוקדם תבנית שמחכה ל-files_list שנבנה מטבלת recent_opens
            pass
    
    # ספירת סך הכל (אם לא חושב כבר)
    if not category_filter:
        # "כל הקבצים": ספירה distinct לפי שם קובץ לאחר סינון (תוכן >0)
        count_pipeline = [
            {'$match': query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
            {'$group': {'_id': '$file_name'}},
            {'$count': 'total'}
        ]
        count_result = list(db.code_snippets.aggregate(count_pipeline))
        total_count = count_result[0]['total'] if count_result else 0
    elif category_filter == 'other':
        # ספירת קבצים ייחודיים לפי שם קובץ לאחר סינון (תוכן >0), עם עקביות ל-query הכללי
        count_pipeline = [
            {'$match': query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
            {'$group': {'_id': '$file_name'}},
            {'$count': 'total'}
        ]
        count_result = list(db.code_snippets.aggregate(count_pipeline))
        total_count = count_result[0]['total'] if count_result else 0
    elif category_filter != 'large':
        total_count = db.code_snippets.count_documents(query)
    
    # שליפת הקבצים
    sort_order = DESCENDING if sort_by.startswith('-') else 1
    sort_field = sort_by.lstrip('-')
    
    # קטגוריה מיוחדת: recent
    if category_filter == 'recent':
        # שליפת שמות קבצים אחרונים לפי user_id והזמן האחרון שנפתחו
        try:
            recent_docs = list(db.recent_opens.find({'user_id': user_id}, {'file_name': 1, 'last_opened_at': 1, '_id': 0}))
        except Exception:
            recent_docs = []

        if not recent_docs:
            # אין קבצים שנפתחו לאחרונה
            languages = db.code_snippets.distinct(
                'programming_language',
                {
                    'user_id': user_id,
                    '$or': [
                        {'is_active': True},
                        {'is_active': {'$exists': False}}
                    ]
                }
            )
            languages = sorted([lang for lang in languages if lang]) if languages else []
            html = render_template('files.html',
                                 user=session['user_data'],
                                 files=[],
                                 total_count=0,
                                 languages=languages,
                                 search_query=search_query,
                                 language_filter=language_filter,
                                 category_filter=category_filter,
                                 sort_by=sort_by,
                                 page=page,
                                 total_pages=1,
                                 has_prev=False,
                                 has_next=False,
                                 bot_username=BOT_USERNAME_CLEAN)
            if should_cache:
                try:
                    cache.set(files_cache_key, html, FILES_PAGE_CACHE_TTL)
                except Exception:
                    pass
            return html

        # מיפוי שם->זמן פתיחה אחרון ומערך שמות
        recent_map = {}
        file_names = []
        for r in recent_docs:
            fname = (r.get('file_name') or '').strip()
            if not fname:
                continue
            file_names.append(fname)
            recent_map[fname] = r.get('last_opened_at')

        # בניית שאילתה עם כל המסננים שכבר חושבו + סינון לשמות שנפתחו לאחרונה
        recent_query = {
            'user_id': user_id,
            '$and': [{
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }]
        }
        # לשמור עקביות עם החיפוש/מסננים הכלליים
        if search_query:
            recent_query['$and'].append({'$or': [
                {'file_name': {'$regex': search_query, '$options': 'i'}},
                {'description': {'$regex': search_query, '$options': 'i'}},
                {'tags': {'$in': [search_query.lower()]}}
            ]})
        if language_filter:
            recent_query['programming_language'] = language_filter
        # צמצום לשמות שנפתחו לאחרונה
        recent_query['file_name'] = {'$in': file_names or ['__none__']}

        # אגרגציה: גרסה אחרונה לכל שם קובץ + פלטר לתוכן לא ריק
        sort_field_local = sort_by.lstrip('-') if sort_by else 'last_opened_at'
        sort_dir = -1 if (sort_by or '').startswith('-') else 1

        pipeline = [
            {'$match': recent_query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
        ]

        # מיון: אם מיון לפי last_opened_at – נטפל בפייתון; אחרת נמיין ב-DB
        if sort_field_local in {'file_name', 'created_at', 'updated_at'}:
            pipeline.append({'$sort': {sort_field_local: sort_dir}})

        try:
            latest_items = list(db.code_snippets.aggregate(pipeline))
        except Exception:
            latest_items = []

        # מיון לפי זמן פתיחה אחרון (במידה ונדרש)
        if sort_field_local not in {'file_name', 'created_at', 'updated_at'}:
            # treat as last_opened_at
            latest_items.sort(key=lambda d: (recent_map.get(d.get('file_name') or ''), (d.get('file_name') or '')), reverse=(sort_dir == -1))

        # פג'ינציה
        total_count = len(latest_items)
        total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
        page = max(1, min(page, total_pages))
        start = (page - 1) * per_page
        end = start + per_page
        page_items = latest_items[start:end]

        # המרה לפורמט תבנית
        files_list = []
        for latest in page_items:
            fname = latest.get('file_name') or ''
            code_str = latest.get('code') or ''
            lang_raw = (latest.get('programming_language') or '').lower() or 'text'
            lang_display = 'markdown' if (lang_raw in {'', 'text'} and fname.lower().endswith('.md')) else lang_raw
            files_list.append({
                'id': str(latest.get('_id')),
                'file_name': fname,
                'language': lang_display,
                'icon': get_language_icon(lang_display),
                'description': latest.get('description', ''),
                'tags': latest.get('tags', []),
                'size': format_file_size(len(code_str.encode('utf-8'))),
                'lines': len(code_str.splitlines()),
                'created_at': format_datetime_display(latest.get('created_at')),
                'updated_at': format_datetime_display(latest.get('updated_at')),
                'last_opened_at': format_datetime_display(recent_map.get(fname)),
            })

        # רשימת שפות לפילטר - רק מקבצים פעילים
        languages = db.code_snippets.distinct(
            'programming_language',
            {
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }
        )
        languages = sorted([lang for lang in languages if lang]) if languages else []

        return render_template('files.html',
                             user=session['user_data'],
                             files=files_list,
                             total_count=total_count,
                             languages=languages,
                             search_query=search_query,
                             language_filter=language_filter,
                             category_filter=category_filter,
                             sort_by=sort_by,
                             page=page,
                             total_pages=total_pages,
                             has_prev=page > 1,
                             has_next=page < total_pages,
                             bot_username=BOT_USERNAME_CLEAN)

    # אם לא עשינו aggregation כבר (בקטגוריות large/other) — עבור all נשתמש גם באגרגציה
    if not category_filter:
        sort_dir = -1 if sort_by.startswith('-') else 1
        sort_field_local = sort_by.lstrip('-')
        # בסיס הפייפליין: גרסה אחרונה לכל file_name ותוכן לא ריק
        base_pipeline = [
            {'$match': query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
        ]
        next_cursor_token = None
        use_cursor = (sort_field_local == 'created_at')
        if use_cursor:
            last_dt, last_oid = _decode_cursor(cursor_token)
            pipeline = list(base_pipeline)
            if last_dt is not None and last_oid is not None:
                if sort_dir == -1:
                    # דפדוף קדימה (חדש->ישן): הביא ישנים יותר מ-anchor
                    pipeline.append({'$match': {
                        '$or': [
                            {'created_at': {'$lt': last_dt}},
                            {'$and': [
                                {'created_at': {'$eq': last_dt}},
                                {'_id': {'$lt': last_oid}},
                            ]}
                        ]
                    }})
                else:
                    # דפדוף קדימה (ישן->חדש)
                    pipeline.append({'$match': {
                        '$or': [
                            {'created_at': {'$gt': last_dt}},
                            {'$and': [
                                {'created_at': {'$eq': last_dt}},
                                {'_id': {'$gt': last_oid}},
                            ]}
                        ]
                    }})
            # מיון יציב + חיתוך ל-page+1 כדי לזהות אם יש עוד
            pipeline.append({'$sort': {'created_at': sort_dir, '_id': sort_dir}})
            pipeline.append({'$limit': per_page + 1})
            docs = list(db.code_snippets.aggregate(pipeline))
            if len(docs) > per_page:
                anchor = docs[per_page - 1]
                try:
                    next_cursor_token = _encode_cursor(anchor.get('created_at') or datetime.now(timezone.utc), anchor.get('_id'))
                except Exception:
                    next_cursor_token = None
                docs = docs[:per_page]
            files_cursor = docs
        else:
            pipeline = list(base_pipeline)
            pipeline.append({'$sort': {sort_field_local: sort_dir}})
            pipeline.append({'$skip': (page - 1) * per_page})
            pipeline.append({'$limit': per_page})
            files_cursor = db.code_snippets.aggregate(pipeline)
    elif category_filter not in ('large', 'other'):
        files_cursor = db.code_snippets.find(query).sort(sort_field, sort_order).skip((page - 1) * per_page).limit(per_page)
    elif category_filter == 'other':
        # "שאר קבצים": בעלי תוכן (>0 בתים), מציגים גרסה אחרונה לכל file_name; עקבי עם ה-query הכללי
        sort_dir = -1 if sort_by.startswith('-') else 1
        sort_field_local = sort_by.lstrip('-')
        base_pipeline = [
            {'$match': query},
            {'$addFields': {
                'code_size': {
                    '$cond': {
                        'if': {'$and': [
                            {'$ne': ['$code', None]},
                            {'$eq': [{'$type': '$code'}, 'string']}
                        ]},
                        'then': {'$strLenBytes': '$code'},
                        'else': 0
                    }
                }
            }},
            {'$match': {'code_size': {'$gt': 0}}},
        ]
        pipeline = base_pipeline + [
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
            {'$sort': {sort_field_local: sort_dir}},
            {'$skip': (page - 1) * per_page},
            {'$limit': per_page},
        ]
        files_cursor = db.code_snippets.aggregate(pipeline)
    
    files_list = []
    for file in files_cursor:
        code_str = file.get('code') or ''
        fname = file.get('file_name') or ''
        lang_raw = (file.get('programming_language') or '').lower() or 'text'
        # Fallback: אם שמור כ-text אבל הסיומת היא .md – נתייג כ-markdown לתצוגה
        lang_display = 'markdown' if (lang_raw in {'', 'text'} and fname.lower().endswith('.md')) else lang_raw
        files_list.append({
            'id': str(file['_id']),
            'file_name': fname,
            'language': lang_display,
            'icon': get_language_icon(lang_display),
            'description': file.get('description', ''),
            'tags': file.get('tags', []),
            'size': format_file_size(len(code_str.encode('utf-8'))),
            'lines': len(code_str.splitlines()),
            'created_at': format_datetime_display(file.get('created_at')),
            'updated_at': format_datetime_display(file.get('updated_at'))
        })
    
    # רשימת שפות לפילטר - רק מקבצים פעילים
    languages = db.code_snippets.distinct(
        'programming_language',
        {
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
    )
    # סינון None וערכים ריקים ומיון
    languages = sorted([lang for lang in languages if lang]) if languages else []
    
    # חישוב עמודים
    total_pages = (total_count + per_page - 1) // per_page
    
    # שמירה על הקשר ריפו שנבחר (אם קיים) כדי לא לשבור עימוד/מסננים
    selected_repo_value = repo_name if (category_filter == 'repo' and repo_name) else ''

    html = render_template('files.html',
                         user=session['user_data'],
                         files=files_list,
                         total_count=total_count,
                         languages=languages,
                         search_query=search_query,
                         language_filter=language_filter,
                         category_filter=category_filter,
                         sort_by=sort_by,
                         page=page,
                         total_pages=total_pages,
                         has_prev=page > 1,
                         has_next=page < total_pages,
                         next_cursor=(next_cursor_token if 'next_cursor_token' in locals() else None),
                         selected_repo=selected_repo_value,
                         bot_username=BOT_USERNAME_CLEAN)
    if should_cache:
        try:
            cache.set(files_cache_key, html, FILES_PAGE_CACHE_TTL)
        except Exception:
            pass
    return html

@app.route('/file/<file_id>')
@login_required
def view_file(file_id):
    """צפייה בקובץ בודד"""
    db = get_db()
    user_id = session['user_id']
    
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except:
        abort(404)
    
    if not file:
        abort(404)
    # עדכון רשימת "נפתחו לאחרונה" (MRU) עבור המשתמש הנוכחי — לפני בדיקות Cache
    try:
        ensure_recent_opens_indexes()
        coll = db.recent_opens
        now = datetime.now(timezone.utc)
        coll.update_one(
            {'user_id': user_id, 'file_name': file.get('file_name')},
            {'$set': {
                'user_id': user_id,
                'file_name': file.get('file_name'),
                'last_opened_at': now,
                'last_opened_file_id': file.get('_id'),
                'language': (file.get('programming_language') or 'text'),
                'updated_at': now,
            }, '$setOnInsert': {'created_at': now}},
            upsert=True
        )
    except Exception:
        # אין לכשיל את הדף אם אין DB או אם יש כשל אינדקס/עדכון
        pass
    # HTTP cache validators (ETag / Last-Modified)
    etag = _compute_file_etag(file)
    last_modified_dt = _safe_dt_from_doc(file.get('updated_at') or file.get('created_at'))
    last_modified_str = http_date(last_modified_dt)
    inm = request.headers.get('If-None-Match')
    if inm and inm == etag:
        resp = Response(status=304)
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_str
        return resp
    ims = request.headers.get('If-Modified-Since')
    if ims:
        try:
            ims_dt = parse_date(ims)
        except Exception:
            ims_dt = None
        if ims_dt is not None and last_modified_dt.replace(microsecond=0) <= ims_dt:
            resp = Response(status=304)
            resp.headers['ETag'] = etag
            resp.headers['Last-Modified'] = last_modified_str
            return resp


    # הדגשת syntax
    code = file.get('code', '')
    language = (file.get('programming_language') or 'text').lower()
    # תקן תיוג: אם נשמר כ-text אך הסיומת .md – תייג כ-markdown לתצוגה וכפתור 🌐
    try:
        if (not language or language == 'text') and str(file.get('file_name') or '').lower().endswith('.md'):
            language = 'markdown'
    except Exception:
        pass
    
    # הגבלת גודל תצוגה - 1MB
    MAX_DISPLAY_SIZE = 1024 * 1024  # 1MB
    if len(code.encode('utf-8')) > MAX_DISPLAY_SIZE:
        html = render_template('view_file.html',
                             user=session['user_data'],
                             file={
                                 'id': str(file['_id']),
                                 'file_name': file['file_name'],
                                 'language': language,
                                 'icon': get_language_icon(language),
                                 'description': file.get('description', ''),
                                 'tags': file.get('tags', []),
                                 'size': format_file_size(len(code.encode('utf-8'))),
                                 'lines': len(code.splitlines()),
                                 'created_at': format_datetime_display(file.get('created_at')),
                                 'updated_at': format_datetime_display(file.get('updated_at')),
                                 'version': file.get('version', 1)
                             },
                             highlighted_code='<div class="alert alert-info" style="text-align: center; padding: 3rem;"><i class="fas fa-file-alt" style="font-size: 3rem; margin-bottom: 1rem;"></i><br>הקובץ גדול מדי לתצוגה (' + format_file_size(len(code.encode('utf-8'))) + ')<br><br>ניתן להוריד את הקובץ לצפייה מקומית</div>',
                             syntax_css='')
        resp = Response(html, mimetype='text/html; charset=utf-8')
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_str
        return resp
    
    # בדיקה אם הקובץ בינארי
    if is_binary_file(code, file.get('file_name', '')):
        html = render_template('view_file.html',
                             user=session['user_data'],
                             file={
                                 'id': str(file['_id']),
                                 'file_name': file['file_name'],
                                 'language': 'binary',
                                 'icon': '🔒',
                                 'description': 'קובץ בינארי - לא ניתן להציג',
                                 'tags': file.get('tags', []),
                                 'size': format_file_size(len(code.encode('utf-8')) if code else 0),
                                 'lines': 0,
                                 'created_at': format_datetime_display(file.get('created_at')),
                                 'updated_at': format_datetime_display(file.get('updated_at')),
                                 'version': file.get('version', 1)
                             },
                             highlighted_code='<div class="alert alert-warning" style="text-align: center; padding: 3rem;"><i class="fas fa-lock" style="font-size: 3rem; margin-bottom: 1rem;"></i><br>קובץ בינארי - לא ניתן להציג את התוכן<br><br>ניתן להוריד את הקובץ בלבד</div>',
                             syntax_css='')
        resp = Response(html, mimetype='text/html; charset=utf-8')
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_str
        return resp
    
    try:
        lexer = get_lexer_by_name(language, stripall=True)
    except:
        try:
            lexer = guess_lexer(code)
        except:
            lexer = get_lexer_by_name('text')
    
    formatter = HtmlFormatter(
        style='github-dark',
        linenos=True,
        cssclass='source',
        lineanchors='line',
        anchorlinenos=True
    )
    
    highlighted_code = highlight(code, lexer, formatter)
    css = formatter.get_style_defs('.source')
    
    file_data = {
        'id': str(file['_id']),
        'file_name': file['file_name'],
        'language': language,
        'icon': get_language_icon(language),
        'description': file.get('description', ''),
        'tags': file.get('tags', []),
        'size': format_file_size(len(code.encode('utf-8'))),
        'lines': len(code.splitlines()),
        'created_at': format_datetime_display(file.get('created_at')),
        'updated_at': format_datetime_display(file.get('updated_at')),
        'version': file.get('version', 1),
        'is_favorite': bool(file.get('is_favorite', False)),
    }
    
    html = render_template('view_file.html',
                         user=session['user_data'],
                         file=file_data,
                         highlighted_code=highlighted_code,
                         syntax_css=css,
                         raw_code=code)
    resp = Response(html, mimetype='text/html; charset=utf-8')
    resp.headers['ETag'] = etag
    resp.headers['Last-Modified'] = last_modified_str
    return resp

@app.route('/edit/<file_id>', methods=['GET', 'POST'])
@login_required
def edit_file_page(file_id):
    """עריכת קובץ קיים: טופס עריכה ושמירת גרסה חדשה."""
    db = get_db()
    user_id = session['user_id']
    try:
        file = db.code_snippets.find_one({'_id': ObjectId(file_id), 'user_id': user_id})
    except Exception:
        file = None
    if not file:
        abort(404)

    error = None
    success = None

    if request.method == 'POST':
        try:
            file_name = (request.form.get('file_name') or '').strip()
            code = request.form.get('code') or ''
            # נרמול התוכן כדי להסיר תווים נסתרים וליישר פורמט עוד לפני שמירה
            code = normalize_code(code)
            language = (request.form.get('language') or '').strip() or (file.get('programming_language') or 'text')
            description = (request.form.get('description') or '').strip()
            raw_tags = (request.form.get('tags') or '').strip()
            tags = [t.strip() for t in re.split(r'[,#\n]+', raw_tags) if t.strip()] if raw_tags else list(file.get('tags') or [])

            if not file_name:
                error = 'יש להזין שם קובץ'
            elif not code:
                error = 'יש להזין תוכן קוד'
            else:
                # זיהוי שפה בסיסי אם לא סופק
                if not language or language == 'text':
                    try:
                        from utils import detect_language_from_filename as _dl
                        language = _dl(file_name) or 'text'
                    except Exception:
                        language = 'text'

                # נסיון ניחוש שפה לפי תוכן כאשר נותר text
                if language == 'text' and code:
                    try:
                        lex = None
                        try:
                            lex = guess_lexer(code)
                        except Exception:
                            lex = None
                        if lex is not None:
                            lex_name = (getattr(lex, 'name', '') or '').lower()
                            aliases = [a.lower() for a in getattr(lex, 'aliases', []) or []]
                            cand = lex_name or (aliases[0] if aliases else '')
                            def _normalize_lang(name: str) -> str:
                                n = name.lower()
                                if 'python' in n or n in {'py'}:
                                    return 'python'
                                if n in {'javascript', 'js', 'node', 'nodejs'} or 'javascript' in n:
                                    return 'javascript'
                                if n in {'typescript', 'ts'}:
                                    return 'typescript'
                                if n in {'c++', 'cpp', 'cxx'}:
                                    return 'cpp'
                                if n == 'c':
                                    return 'c'
                                if n in {'c#', 'csharp'}:
                                    return 'csharp'
                                if n in {'go', 'golang'}:
                                    return 'go'
                                if n in {'rust', 'rs'}:
                                    return 'rust'
                                if 'java' in n:
                                    return 'java'
                                if 'kotlin' in n:
                                    return 'kotlin'
                                if n in {'ruby', 'rb'}:
                                    return 'ruby'
                                if n in {'php'}:
                                    return 'php'
                                if n in {'swift'}:
                                    return 'swift'
                                if n in {'html', 'htm'}:
                                    return 'html'
                                if n in {'css', 'scss', 'sass', 'less'}:
                                    return 'css'
                                if n in {'bash', 'sh', 'shell', 'zsh'}:
                                    return 'bash'
                                if n in {'sql'}:
                                    return 'sql'
                                if n in {'yaml', 'yml'}:
                                    return 'yaml'
                                if n in {'json'}:
                                    return 'json'
                                if n in {'xml'}:
                                    return 'xml'
                                if 'markdown' in n or n in {'md'}:
                                    return 'markdown'
                                return 'text'
                            guessed = _normalize_lang(cand)
                            if guessed != 'text':
                                language = guessed
                    except Exception:
                        pass

                # חיזוק מיפוי: אם הסיומת .md והשפה עדיין לא זוהתה כ-markdown – תיוג כ-markdown
                try:
                    if isinstance(file_name, str) and file_name.lower().endswith('.md') and (not language or language.lower() == 'text'):
                        language = 'markdown'
                except Exception:
                    pass

                # עדכון שם קובץ לפי השפה (אם אין סיומת או .txt)
                try:
                    lang_to_ext = {
                        'python': 'py',
                        'javascript': 'js',
                        'typescript': 'ts',
                        'java': 'java',
                        'cpp': 'cpp',
                        'c': 'c',
                        'csharp': 'cs',
                        'go': 'go',
                        'rust': 'rs',
                        'ruby': 'rb',
                        'php': 'php',
                        'swift': 'swift',
                        'kotlin': 'kt',
                        'html': 'html',
                        'css': 'css',
                        'sql': 'sql',
                        'bash': 'sh',
                        'shell': 'sh',
                        'yaml': 'yaml',
                        'json': 'json',
                        'xml': 'xml',
                        'markdown': 'md',
                        'scss': 'scss',
                        'sass': 'sass',
                        'less': 'less',
                    }
                    lang_key = (language or 'text').lower()
                    target_ext = lang_to_ext.get(lang_key)
                    if target_ext:
                        base, curr_ext = os.path.splitext(file_name or '')
                        curr_ext_lower = curr_ext.lower()
                        wanted_dot_ext = f'.{target_ext}'
                        if base:
                            if curr_ext_lower == '':
                                file_name = f"{base}{wanted_dot_ext}"
                            elif curr_ext_lower in {'.txt', '.text'} and curr_ext_lower != wanted_dot_ext:
                                file_name = f"{base}{wanted_dot_ext}"
                except Exception:
                    pass

                # קבע גרסה חדשה על סמך שם הקובץ לאחר העדכון
                try:
                    prev = db.code_snippets.find_one(
                        {
                            'user_id': user_id,
                            'file_name': file_name,
                            '$or': [
                                {'is_active': True},
                                {'is_active': {'$exists': False}}
                            ]
                        },
                        sort=[('version', -1)]
                    )
                except Exception:
                    prev = None
                version = int((prev or {}).get('version', 0) or 0) + 1
                if not description:
                    try:
                        description = (prev or file or {}).get('description') or ''
                    except Exception:
                        description = ''
                if not tags:
                    try:
                        tags = list((prev or file or {}).get('tags') or [])
                    except Exception:
                        tags = []

                now = datetime.now(timezone.utc)
                new_doc = {
                    'user_id': user_id,
                    'file_name': file_name,
                    'code': code,
                    'programming_language': language,
                    'description': description,
                    'tags': tags,
                    'version': version,
                    'created_at': now,
                    'updated_at': now,
                    'is_active': True,
                }
                try:
                    res = db.code_snippets.insert_one(new_doc)
                    if res and getattr(res, 'inserted_id', None):
                        return redirect(url_for('view_file', file_id=str(res.inserted_id)))
                    error = 'שמירת הקובץ נכשלה'
                except Exception as _e:
                    error = f'שמירת הקובץ נכשלה: {_e}'
        except Exception as e:
            error = f'שגיאה בעריכה: {e}'

    # טופס עריכה (GET או POST עם שגיאה)
    try:
        languages = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []
        languages = sorted([l for l in languages if l]) if languages else []
    except Exception:
        languages = []

    # המרה לנתונים לתבנית
    code_value = file.get('code') or ''
    file_data = {
        'id': str(file.get('_id')),
        'file_name': file.get('file_name') or '',
        'language': file.get('programming_language') or 'text',
        'description': file.get('description') or '',
        'tags': file.get('tags') or [],
        'version': file.get('version', 1),
    }

    return render_template('edit_file.html',
                         user=session['user_data'],
                         file=file_data,
                         code_value=code_value,
                         languages=languages,
                         error=error,
                         success=success,
                         bot_username=BOT_USERNAME_CLEAN)

@app.route('/download/<file_id>')
@login_required
def download_file(file_id):
    """הורדת קובץ"""
    db = get_db()
    user_id = session['user_id']
    
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except:
        abort(404)
    
    if not file:
        abort(404)
    
    # קביעת סיומת קובץ
    language = file.get('programming_language', 'txt')
    extensions = {
        'python': 'py',
        'javascript': 'js',
        'typescript': 'ts',
        'java': 'java',
        'cpp': 'cpp',
        'c': 'c',
        'csharp': 'cs',
        'go': 'go',
        'rust': 'rs',
        'ruby': 'rb',
        'php': 'php',
        'swift': 'swift',
        'kotlin': 'kt',
        'html': 'html',
        'css': 'css',
        'sql': 'sql',
        'bash': 'sh',
        'shell': 'sh',
        'dockerfile': 'dockerfile',
        'yaml': 'yaml',
        'json': 'json',
        'xml': 'xml',
        'markdown': 'md'
    }
    
    ext = extensions.get(language.lower(), 'txt')
    filename = file['file_name']
    if not filename.endswith(f'.{ext}'):
        filename = f"{filename}.{ext}"
    
    # יצירת קובץ זמני והחזרתו
    from io import BytesIO
    file_content = BytesIO(file['code'].encode('utf-8'))
    file_content.seek(0)
    
    return send_file(
        file_content,
        as_attachment=True,
        download_name=filename,
        mimetype='text/plain'
    )

@app.route('/html/<file_id>')
@login_required
def html_preview(file_id):
    """תצוגת דפדפן לקובץ HTML בתוך iframe עם sandbox."""
    db = get_db()
    user_id = session['user_id']
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except Exception:
        abort(404)
    if not file:
        abort(404)

    language = (file.get('programming_language') or '').lower()
    file_name = file.get('file_name') or 'index.html'
    # מציגים תצוגת דפדפן רק לקבצי HTML
    if language != 'html' and not (isinstance(file_name, str) and file_name.lower().endswith(('.html', '.htm'))):
        return redirect(url_for('view_file', file_id=file_id))

    file_data = {
        'id': str(file.get('_id')),
        'file_name': file_name,
        'language': language or 'html',
    }
    return render_template('html_preview.html', user=session.get('user_data', {}), file=file_data, bot_username=BOT_USERNAME_CLEAN)

@app.route('/raw_html/<file_id>')
@login_required
def raw_html(file_id):
    """מחזיר את ה-HTML הגולמי להצגה בתוך ה-iframe (אותו דומיין)."""
    db = get_db()
    user_id = session['user_id']
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except Exception:
        abort(404)
    if not file:
        abort(404)

    code = file.get('code') or ''
    # קביעת מצב הרצה: ברירת מחדל ללא סקריפטים
    allow = (request.args.get('allow') or request.args.get('mode') or '').strip().lower()
    scripts_enabled = allow in {'1', 'true', 'yes', 'scripts', 'js'}
    if scripts_enabled:
        csp = \
            "sandbox allow-scripts; " \
            "default-src 'none'; " \
            "base-uri 'none'; " \
            "form-action 'none'; " \
            "connect-src 'none'; " \
            "img-src data:; " \
            "style-src 'unsafe-inline'; " \
            "font-src data:; " \
            "object-src 'none'; " \
            "frame-ancestors 'self'; " \
            "script-src 'unsafe-inline'"
        # שים לב: גם במצב זה ה-iframe נשאר בסנדבוקס ללא allow-forms/allow-popups/allow-same-origin
    else:
        csp = \
            "sandbox; " \
            "default-src 'none'; " \
            "base-uri 'none'; " \
            "form-action 'none'; " \
            "connect-src 'none'; " \
            "img-src data:; " \
            "style-src 'unsafe-inline'; " \
            "font-src data:; " \
            "object-src 'none'; " \
            "frame-ancestors 'self'; " \
            "script-src 'none'"

    resp = Response(code, mimetype='text/html; charset=utf-8')
    resp.headers['Content-Security-Policy'] = csp
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['Referrer-Policy'] = 'no-referrer'
    resp.headers['Cache-Control'] = 'no-store'
    return resp

@app.route('/md/<file_id>')
@login_required
def md_preview(file_id):
    """תצוגת Markdown מעוצבת ועשירה, עם הרחבות GFM/KaTeX/Mermaid.

    מציג קבצי Markdown (.md) בדפדפן ברינדור עשיר. לא מבצע הרצת סקריפטים מהתוכן.
    הרינדור עצמו מתבצע בצד הלקוח באמצעות ספריות CDN (markdown-it + plugins),
    ומופעלות תוספות ביצועים כגון טעינה עצלה לתמונות ו-render מדורג למסמכים ארוכים.
    """
    db = get_db()
    user_id = session['user_id']
    try:
        file = db.code_snippets.find_one({
            '_id': ObjectId(file_id),
            'user_id': user_id
        })
    except Exception:
        abort(404)
    if not file:
        abort(404)

    file_name = (file.get('file_name') or '').strip()
    language = (file.get('programming_language') or '').strip().lower()
    # אם סומן כ-text אך הסיומת .md – התייחס אליו כ-markdown
    if (not language or language == 'text') and file_name.lower().endswith('.md'):
        language = 'markdown'
    code = file.get('code') or ''

    # --- HTTP cache validators (ETag / Last-Modified) ---
    etag = _compute_file_etag(file)
    last_modified_dt = _safe_dt_from_doc(file.get('updated_at') or file.get('created_at'))
    last_modified_str = http_date(last_modified_dt)
    inm = request.headers.get('If-None-Match')
    if inm and inm == etag:
        resp = Response(status=304)
        resp.headers['ETag'] = etag
        resp.headers['Last-Modified'] = last_modified_str
        return resp
    ims = request.headers.get('If-Modified-Since')
    if ims:
        try:
            ims_dt = parse_date(ims)
        except Exception:
            ims_dt = None
        if ims_dt is not None and last_modified_dt.replace(microsecond=0) <= ims_dt:
            resp = Response(status=304)
            resp.headers['ETag'] = etag
            resp.headers['Last-Modified'] = last_modified_str
            return resp

    # --- Cache: תוצר ה-HTML של תצוגת Markdown (תבנית) ---
    should_cache = getattr(cache, 'is_enabled', False)
    md_cache_key = None
    if should_cache:
        try:
            # בתצוגה זו התוכן מגיע כתוכן גולמי ומעובד בצד לקוח; ה-HTML תלוי רק בפרמטרים הללו
            _params = {
                'file_name': file_name,
                'lang': 'markdown',
            }
            _raw = json.dumps(_params, sort_keys=True, ensure_ascii=False)
            _hash = hashlib.sha256(_raw.encode('utf-8')).hexdigest()[:24]
            md_cache_key = f"web:md_preview:user:{user_id}:{file_id}:{_hash}"
            cached_html = cache.get(md_cache_key)
            if isinstance(cached_html, str) and cached_html:
                resp = Response(cached_html, mimetype='text/html; charset=utf-8')
                resp.headers['ETag'] = etag
                resp.headers['Last-Modified'] = last_modified_str
                return resp
        except Exception:
            md_cache_key = f"web:md_preview:user:{user_id}:{file_id}:fallback"

    # הצג תצוגת Markdown רק אם זה אכן Markdown
    is_md = language == 'markdown' or file_name.lower().endswith('.md')
    if not is_md:
        return redirect(url_for('view_file', file_id=file_id))

    file_data = {
        'id': str(file.get('_id')),
        'file_name': file_name or 'README.md',
        'language': 'markdown',
    }
    # העבר את התוכן ללקוח בתור JSON כדי למנוע בעיות escaping
    html = render_template('md_preview.html', user=session.get('user_data', {}), file=file_data, md_code=code, bot_username=BOT_USERNAME_CLEAN)
    if should_cache and md_cache_key:
        try:
            cache.set(md_cache_key, html, MD_PREVIEW_CACHE_TTL)
        except Exception:
            pass
    resp = Response(html, mimetype='text/html; charset=utf-8')
    resp.headers['ETag'] = etag
    resp.headers['Last-Modified'] = last_modified_str
    return resp

@app.route('/api/share/<file_id>', methods=['POST'])
@login_required
def create_public_share(file_id):
    """יוצר קישור ציבורי לשיתוף הקובץ ומחזיר את ה-URL."""
    try:
        db = get_db()
        user_id = session['user_id']
        try:
            file = db.code_snippets.find_one({
                '_id': ObjectId(file_id),
                'user_id': user_id
            })
        except Exception:
            return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

        if not file:
            return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

        share_id = secrets.token_urlsafe(12)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=PUBLIC_SHARE_TTL_DAYS)

        doc = {
            'share_id': share_id,
            'file_name': file.get('file_name') or 'snippet.txt',
            'code': file.get('code') or '',
            'language': (file.get('programming_language') or 'text'),
            'description': file.get('description') or '',
            'created_at': now,
            'views': 0,
            'expires_at': expires_at,
        }

        coll = db.internal_shares
        # ניסיון ליצור אינדקסים רלוונטיים (בטוח לקרוא מספר פעמים)
        try:
            from pymongo import ASCENDING, DESCENDING
            coll.create_index([('share_id', ASCENDING)], name='share_id_unique', unique=True)
            coll.create_index([('created_at', DESCENDING)], name='created_at_desc')
            coll.create_index([('expires_at', ASCENDING)], name='expires_ttl', expireAfterSeconds=0)
        except Exception:
            pass

        try:
            coll.insert_one(doc)
        except Exception as e:
            return jsonify({'ok': False, 'error': f'שגיאה בשמירה: {e}'}), 500

        # בסיס ליצירת URL ציבורי: קודם PUBLIC_BASE_URL, אחר כך WEBAPP_URL, ולבסוף host_url מהבקשה
        base = (PUBLIC_BASE_URL or WEBAPP_URL or request.host_url or '').rstrip('/')
        share_url = f"{base}/share/{share_id}" if base else f"/share/{share_id}"
        return jsonify({'ok': True, 'url': share_url, 'share_id': share_id, 'expires_at': expires_at.isoformat()})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_file_web():
    """העלאת קובץ חדש דרך הווב-אפליקציה."""
    db = get_db()
    user_id = session['user_id']
    error = None
    success = None
    if request.method == 'POST':
        try:
            file_name = (request.form.get('file_name') or '').strip()
            code = request.form.get('code') or ''
            language = (request.form.get('language') or '').strip() or 'text'
            description = (request.form.get('description') or '').strip()
            raw_tags = (request.form.get('tags') or '').strip()
            tags = [t.strip() for t in re.split(r'[,#\n]+', raw_tags) if t.strip()] if raw_tags else []

            # אם הועלה קובץ — נקרא ממנו ונשתמש בשמו אם אין שם קובץ בשדה
            try:
                uploaded = request.files.get('code_file')
            except Exception:
                uploaded = None
            if uploaded and hasattr(uploaded, 'filename') and uploaded.filename:
                # הגבלת גודל בסיסית (עד ~2MB)
                data = uploaded.read()
                if data and len(data) > 2 * 1024 * 1024:
                    error = 'קובץ גדול מדי (עד 2MB)'
                else:
                    try:
                        code = data.decode('utf-8')
                    except Exception:
                        try:
                            code = data.decode('latin-1')
                        except Exception:
                            code = ''
                    if not file_name:
                        file_name = uploaded.filename or ''

            # נרמול התוכן (בין אם הגיע מהטופס או מקובץ שהועלה)
            code = normalize_code(code)

            if not file_name:
                error = 'יש להזין שם קובץ'
            elif not code:
                error = 'יש להזין תוכן קוד'
            else:
                # זיהוי שפה בסיסי אם לא סופק
                if not language or language == 'text':
                    try:
                        from utils import detect_language_from_filename as _dl
                        language = _dl(file_name) or 'text'
                    except Exception:
                        language = 'text'

                # אם עדיין לא זוהתה שפה (או הוגדרה כ-text) ננסה לנחש לפי התוכן
                if language == 'text' and code:
                    try:
                        lex = None
                        try:
                            lex = guess_lexer(code)
                        except Exception:
                            lex = None
                        if lex is not None:
                            lex_name = (getattr(lex, 'name', '') or '').lower()
                            aliases = [a.lower() for a in getattr(lex, 'aliases', []) or []]
                            cand = lex_name or (aliases[0] if aliases else '')
                            # מיפוי שמות/כינויים של Pygments לשפה פנימית
                            def _normalize_lang(name: str) -> str:
                                n = name.lower()
                                if 'python' in n or n in {'py'}:
                                    return 'python'
                                if n in {'javascript', 'js', 'node', 'nodejs'} or 'javascript' in n:
                                    return 'javascript'
                                if n in {'typescript', 'ts'}:
                                    return 'typescript'
                                if n in {'c++', 'cpp', 'cxx'}:
                                    return 'cpp'
                                if n == 'c':
                                    return 'c'
                                if n in {'c#', 'csharp'}:
                                    return 'csharp'
                                if n in {'go', 'golang'}:
                                    return 'go'
                                if n in {'rust', 'rs'}:
                                    return 'rust'
                                if 'java' in n:
                                    return 'java'
                                if 'kotlin' in n:
                                    return 'kotlin'
                                if n in {'ruby', 'rb'}:
                                    return 'ruby'
                                if n in {'php'}:
                                    return 'php'
                                if n in {'swift'}:
                                    return 'swift'
                                if n in {'html', 'htm'}:
                                    return 'html'
                                if n in {'css', 'scss', 'sass', 'less'}:
                                    # נעדיף css כשלא ברור
                                    return 'css'
                                if n in {'bash', 'sh', 'shell', 'zsh'}:
                                    return 'bash'
                                if n in {'sql'}:
                                    return 'sql'
                                if n in {'yaml', 'yml'}:
                                    return 'yaml'
                                if n in {'json'}:
                                    return 'json'
                                if n in {'xml'}:
                                    return 'xml'
                                if 'markdown' in n or n in {'md'}:
                                    return 'markdown'
                                return 'text'
                            guessed = _normalize_lang(cand)
                            if guessed != 'text':
                                language = guessed
                    except Exception:
                        pass

                # חיזוק מיפוי: אם הסיומת .md והשפה עדיין לא זוהתה כ-markdown – תיוג כ-markdown
                try:
                    if isinstance(file_name, str) and file_name.lower().endswith('.md') and (not language or language.lower() == 'text'):
                        language = 'markdown'
                except Exception:
                    pass

                # עדכון שם קובץ כך שיתאם את השפה (סיומת מתאימה)
                try:
                    lang_to_ext = {
                        'python': 'py',
                        'javascript': 'js',
                        'typescript': 'ts',
                        'java': 'java',
                        'cpp': 'cpp',
                        'c': 'c',
                        'csharp': 'cs',
                        'go': 'go',
                        'rust': 'rs',
                        'ruby': 'rb',
                        'php': 'php',
                        'swift': 'swift',
                        'kotlin': 'kt',
                        'html': 'html',
                        'css': 'css',
                        'sql': 'sql',
                        'bash': 'sh',
                        'shell': 'sh',
                        'yaml': 'yaml',
                        'json': 'json',
                        'xml': 'xml',
                        'markdown': 'md',
                        'scss': 'scss',
                        'sass': 'sass',
                        'less': 'less',
                        # שפות נוספות יישארו ללא שינוי
                    }
                    lang_key = (language or 'text').lower()
                    target_ext = lang_to_ext.get(lang_key)
                    if target_ext:
                        base, curr_ext = os.path.splitext(file_name or '')
                        curr_ext_lower = curr_ext.lower()
                        wanted_dot_ext = f'.{target_ext}'
                        if not base:
                            # שם ריק – לא נשנה כאן
                            pass
                        elif curr_ext_lower == '':
                            file_name = f"{base}{wanted_dot_ext}"
                        elif curr_ext_lower in {'.txt', '.text'} and curr_ext_lower != wanted_dot_ext:
                            file_name = f"{base}{wanted_dot_ext}"
                        # אם קיימת סיומת לא-טקסט ואחרת – נשאיר כפי שהיא כדי לכבד את שם הקובץ שהוזן
                except Exception:
                    pass
                # שמירה ישירה במסד (להימנע מתלות ב-BOT_TOKEN של שכבת הבוט)
                try:
                    # קבע גרסה חדשה על בסיס האחרונה הפעילה
                    prev = db.code_snippets.find_one(
                        {
                            'user_id': user_id,
                            'file_name': file_name,
                            '$or': [
                                {'is_active': True},
                                {'is_active': {'$exists': False}}
                            ]
                        },
                        sort=[('version', -1)]
                    )
                except Exception:
                    prev = None
                version = int((prev or {}).get('version', 0) or 0) + 1
                if not description:
                    try:
                        description = (prev or {}).get('description') or ''
                    except Exception:
                        description = ''
                prev_tags = []
                try:
                    prev_tags = list((prev or {}).get('tags') or [])
                except Exception:
                    prev_tags = []
                # אל תוסיף תגיות repo:* כברירת מחדל בעת העלאה חדשה; שמור רק תגיות רגילות אם המשתמש לא הקליד
                safe_prev_tags = [t for t in prev_tags if not (isinstance(t, str) and t.strip().lower().startswith('repo:'))]
                final_tags = tags if tags else safe_prev_tags

                now = datetime.now(timezone.utc)
                doc = {
                    'user_id': user_id,
                    'file_name': file_name,
                    'code': code,
                    'programming_language': language,
                    'description': description,
                    'tags': final_tags,
                    'version': version,
                    'created_at': now,
                    'updated_at': now,
                    'is_active': True,
                }
                try:
                    res = db.code_snippets.insert_one(doc)
                except Exception as _e:
                    res = None
                if res and getattr(res, 'inserted_id', None):
                    return redirect(url_for('view_file', file_id=str(res.inserted_id)))
                error = 'שמירת הקובץ נכשלה'
        except Exception as e:
            error = f'שגיאה בהעלאה: {e}'
    # שליפת שפות קיימות להצעה
    languages = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []
    languages = sorted([l for l in languages if l]) if languages else []
    return render_template('upload.html', bot_username=BOT_USERNAME_CLEAN, user=session['user_data'], languages=languages, error=error, success=success)

@app.route('/api/favorite/toggle/<file_id>', methods=['POST'])
@login_required
def api_toggle_favorite(file_id):
    """טוגל מועדפים עבור קובץ: מעדכן את המסמך הפעיל העדכני לפי file_name למשתמש."""
    try:
        db = get_db()
        user_id = session['user_id']
        try:
            src = db.code_snippets.find_one({'_id': ObjectId(file_id), 'user_id': user_id})
        except Exception:
            src = None
        if not src:
            return jsonify({'ok': False, 'error': 'קובץ לא נמצא'}), 404

        file_name = src.get('file_name')
        if not file_name:
            return jsonify({'ok': False, 'error': 'שם קובץ חסר'}), 400

        current = bool(src.get('is_favorite', False))
        new_state = not current
        now = datetime.now(timezone.utc)

        # עדכן את הגרסאות הפעילות האחרונות עבור אותו שם קובץ
        q = {
            'user_id': user_id,
            'file_name': file_name,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        try:
            db.code_snippets.update_many(q, {
                '$set': {
                    'is_favorite': new_state,
                    'favorited_at': (now if new_state else None),
                    'updated_at': now,
                }
            })
        except Exception as e:
            return jsonify({'ok': False, 'error': f'לא ניתן לעדכן מועדפים: {e}'}), 500

        return jsonify({'ok': True, 'state': new_state})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/files/bulk-favorite', methods=['POST'])
@login_required
def api_files_bulk_favorite():
    """הוספת is_favorite=True לקבוצת קבצים של המשתמש."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']
        now = datetime.now(timezone.utc)

        q = {
            '_id': {'$in': object_ids},
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        res = db.code_snippets.update_many(q, {
            '$set': {
                'is_favorite': True,
                'favorited_at': now,
                'updated_at': now,
            }
        })
        return jsonify({'success': True, 'updated': int(getattr(res, 'modified_count', 0))})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/bulk-unfavorite', methods=['POST'])
@login_required
def api_files_bulk_unfavorite():
    """ביטול is_favorite לקבוצת קבצים של המשתמש."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']
        now = datetime.now(timezone.utc)

        q = {
            '_id': {'$in': object_ids},
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        res = db.code_snippets.update_many(q, {
            '$set': {
                'is_favorite': False,
                'favorited_at': None,
                'updated_at': now,
            }
        })
        return jsonify({'success': True, 'updated': int(getattr(res, 'modified_count', 0))})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/bulk-tag', methods=['POST'])
@login_required
def api_files_bulk_tag():
    """הוספת תגיות לקבוצת קבצים של המשתמש ללא כפילויות."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        tags = list(data.get('tags') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400
        # נרמול תגיות – מחרוזות לא ריקות בלבד
        safe_tags = []
        for t in tags:
            try:
                s = str(t).strip()
            except Exception:
                s = ''
            if s:
                safe_tags.append(s)
        # הסר כפילויות תוך שמירה על סדר יחסי
        seen = set()
        norm_tags = [x for x in safe_tags if not (x in seen or seen.add(x))]
        if not norm_tags:
            return jsonify({'success': False, 'error': 'No tags provided'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']
        now = datetime.now(timezone.utc)

        q = {
            '_id': {'$in': object_ids},
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        }
        res = db.code_snippets.update_many(q, {
            '$addToSet': {'tags': {'$each': norm_tags}},
            '$set': {'updated_at': now}
        })
        return jsonify({'success': True, 'updated': int(getattr(res, 'modified_count', 0))})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/create-zip', methods=['POST'])
@login_required
def api_files_create_zip():
    """יצירת קובץ ZIP עם קבצים נבחרים של המשתמש."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']

        # שליפת הקבצים השייכים למשתמש בלבד
        cursor = db.code_snippets.find({
            '_id': {'$in': object_ids},
            'user_id': user_id,
            '$or': [
                {'is_active': True},
                {'is_active': {'$exists': False}}
            ]
        })

        from io import BytesIO
        import zipfile

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for doc in cursor:
                filename = (doc.get('file_name') or f"file_{str(doc.get('_id'))}.txt").strip() or f"file_{str(doc.get('_id'))}.txt"
                # ודא שם ייחודי אם יש כפילויות
                try:
                    # מניעת שמות תיקיה מסוכנים
                    filename = filename.replace('..', '_').replace('/', '_').replace('\\', '_')
                except Exception:
                    filename = f"file_{str(doc.get('_id'))}.txt"
                content = doc.get('code')
                if not isinstance(content, str):
                    content = ''
                zf.writestr(filename, content)

        zip_buffer.seek(0)
        ts = int(time.time())
        return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name=f'code_files_{ts}.zip')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/create-share-link', methods=['POST'])
@login_required
def api_files_create_share_link():
    """יוצר קישור שיתוף ציבורי לקבצים נבחרים ומחזיר URL."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        if len(file_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400

        db = get_db()
        user_id = session['user_id']

        # אימות שהקבצים שייכים למשתמש
        owned_count = db.code_snippets.count_documents({
            '_id': {'$in': object_ids},
            'user_id': user_id
        })
        if owned_count != len(object_ids):
            return jsonify({'success': False, 'error': 'Some files not found'}), 404

        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=PUBLIC_SHARE_TTL_DAYS)

        db.share_links.insert_one({
            'token': token,
            'file_ids': object_ids,
            'user_id': user_id,
            'created_at': now,
            'expires_at': expires_at,
            'view_count': 0,
        })

        base_url = (WEBAPP_URL or request.host_url.rstrip('/')).rstrip('/')
        share_url = f"{base_url}/shared/{token}"
        return jsonify({'success': True, 'share_url': share_url, 'expires_at': expires_at.isoformat(), 'token': token})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/bulk-delete', methods=['POST'])
@login_required
def api_files_bulk_delete():
    """מחיקה רכה (soft delete) לקבוצת קבצים – מסמן is_active=False עם תוקף שחזור.

    קלט JSON:
    - file_ids: List[str]
    - ttl_days: Optional[int] – אם לא סופק, יילקח מ־RECYCLE_TTL_DAYS (ברירת מחדל 7)
    """
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get('file_ids') or [])
        # ברירת מחדל מ-ENV (RECYCLE_TTL_DAYS); אם התקבל ערך לא חוקי – השתמש בברירת המחדל
        raw_ttl = data.get('ttl_days')
        if raw_ttl is None or str(raw_ttl).strip() == '':
            ttl_days = RECYCLE_TTL_DAYS_DEFAULT
        else:
            try:
                ttl_days = int(raw_ttl)
            except Exception:
                ttl_days = RECYCLE_TTL_DAYS_DEFAULT
        if ttl_days < 1:
            ttl_days = RECYCLE_TTL_DAYS_DEFAULT
        if ttl_days > 30:
            ttl_days = 30

        if not file_ids:
            return jsonify({'success': False, 'error': 'No files selected'}), 400
        # המרה ל-ObjectId והסרת כפילויות לשמירה על לוגיקה עקבית בספירה/אימות
        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid file id'}), 400
        # שמור סדר אך הסר כפילויות
        unique_object_ids = list(dict.fromkeys(object_ids))
        if len(unique_object_ids) > 100:
            return jsonify({'success': False, 'error': 'Too many files (max 100)'}), 400

        db = get_db()
        user_id = session['user_id']
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=ttl_days)

        # אימות בעלות ואיסוף סטטוס is_active לכל קובץ; תוצאה אחת לכל ID ייחודי
        docs = list(db.code_snippets.find(
            {'_id': {'$in': unique_object_ids}, 'user_id': user_id},
            {'_id': 1, 'is_active': 1}
        ))
        found_ids = {doc['_id'] for doc in docs}
        if len(found_ids) != len(unique_object_ids):
            return jsonify({'success': False, 'error': 'Some files not found'}), 404
        # קבצים פעילים למחיקה (מוגדר כ-True או לא קיים)
        active_ids = [doc['_id'] for doc in docs if bool(doc.get('is_active', True))]
        skipped_already_deleted = len(unique_object_ids) - len(active_ids)

        modified_count = 0
        if active_ids:
            q = {
                '_id': {'$in': active_ids},
                'user_id': user_id,
                '$or': [
                    {'is_active': True},
                    {'is_active': {'$exists': False}}
                ]
            }
            res = db.code_snippets.update_many(q, {
                '$set': {
                    'is_active': False,
                    'deleted_at': now,
                    'deleted_expires_at': expires_at,
                    'updated_at': now,
                }
            })
            modified_count = int(getattr(res, 'modified_count', 0))
        return jsonify({
            'success': True,
            'deleted': modified_count,
            'skipped_already_deleted': skipped_already_deleted,
            'requested': len(unique_object_ids),
            'message': f'הקבצים הועברו לסל המחזור ל-{ttl_days} ימים'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stats')
@login_required
def api_stats():
    """API לקבלת סטטיסטיקות"""
    db = get_db()
    user_id = session['user_id']

    # --- Cache: JSON סטטיסטיקות לפי משתמש ופרמטרים ---
    should_cache = getattr(cache, 'is_enabled', False)
    try:
        _params = {
            # לעתיד: אם יתווספו פילטרים לסטטיסטיקות ב-query string
        }
        _raw = json.dumps(_params, sort_keys=True, ensure_ascii=False)
        _hash = hashlib.sha256(_raw.encode('utf-8')).hexdigest()[:16]
        stats_cache_key = f"api:stats:user:{user_id}:{_hash}"
    except Exception:
        stats_cache_key = f"api:stats:user:{user_id}:v1"

    if should_cache:
        try:
            cached_json = cache.get(stats_cache_key)
            if isinstance(cached_json, dict) and cached_json:
                # ETag בסיסי לפי hash של גוף ה‑JSON השמור בקאש
                try:
                    etag = 'W/"' + hashlib.sha256(json.dumps(cached_json, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16] + '"'
                    inm = request.headers.get('If-None-Match')
                    if inm and inm == etag:
                        return Response(status=304)
                    resp = jsonify(cached_json)
                    resp.headers['ETag'] = etag
                    return resp
                except Exception:
                    return jsonify(cached_json)
        except Exception:
            pass
    
    active_query = {
        'user_id': user_id,
        '$or': [
            {'is_active': True},
            {'is_active': {'$exists': False}}
        ]
    }
    
    stats = {
        'total_files': db.code_snippets.count_documents(active_query),
        'languages': list(db.code_snippets.distinct('programming_language', active_query)),
        'recent_activity': []
    }
    
    recent = db.code_snippets.find(
        active_query,
        {'file_name': 1, 'created_at': 1}
    ).sort('created_at', DESCENDING).limit(10)
    
    for item in recent:
        stats['recent_activity'].append({
            'file_name': item['file_name'],
            'created_at': item.get('created_at', datetime.now()).isoformat()
        })
    
    if should_cache:
        try:
            cache.set(stats_cache_key, stats, API_STATS_CACHE_TTL)
        except Exception:
            pass
    # הוספת ETag לתגובה גם כאשר לא שוחזר מהקאש
    try:
        etag = 'W/"' + hashlib.sha256(json.dumps(stats, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16] + '"'
        inm = request.headers.get('If-None-Match')
        if inm and inm == etag:
            return Response(status=304)
        resp = jsonify(stats)
        resp.headers['ETag'] = etag
        return resp
    except Exception:
        return jsonify(stats)

@app.route('/settings')
@login_required
def settings():
    """דף הגדרות"""
    user_id = session['user_id']
    
    # בדיקה אם המשתמש הוא אדמין
    user_is_admin = is_admin(user_id)

    # בדיקה האם יש חיבור קבוע פעיל
    has_persistent = False
    try:
        db = get_db()
        token = request.cookies.get(REMEMBER_COOKIE_NAME)
        if token:
            doc = db.remember_tokens.find_one({'token': token, 'user_id': user_id})
            if doc:
                exp = doc.get('expires_at')
                if isinstance(exp, datetime):
                    has_persistent = exp > datetime.now(timezone.utc)
                else:
                    try:
                        has_persistent = datetime.fromisoformat(str(exp)) > datetime.now(timezone.utc)
                    except Exception:
                        has_persistent = False
    except Exception:
        has_persistent = False

    return render_template('settings.html',
                         user=session['user_data'],
                         is_admin=user_is_admin,
                         persistent_login_enabled=has_persistent,
                         persistent_days=PERSISTENT_LOGIN_DAYS)

@app.route('/health')
def health():
    """בדיקת תקינות"""
    health_data = {
        'status': 'checking',
        'message': 'Web app is running!',
        'version': '2.0.0',
        'database': 'unknown',
        'config': {},
        'timestamp': datetime.now(timezone.utc).isoformat()
    }
    
    # בדיקת משתני סביבה
    health_data['config'] = {
        'MONGODB_URL': 'configured' if MONGODB_URL else 'missing',
        'BOT_TOKEN': 'configured' if BOT_TOKEN else 'missing',
        'BOT_USERNAME': BOT_USERNAME or 'missing',
        'DATABASE_NAME': DATABASE_NAME,
        'WEBAPP_URL': WEBAPP_URL
    }
    
    # בדיקת חיבור למסד נתונים
    try:
        if not MONGODB_URL:
            health_data['database'] = 'not configured'
            health_data['status'] = 'unhealthy'
            health_data['error'] = 'MONGODB_URL is not configured'
        else:
            db = get_db()
            db.command('ping')
            health_data['database'] = 'connected'
            health_data['status'] = 'healthy'
    except Exception as e:
        health_data['database'] = 'error'
        health_data['status'] = 'unhealthy'
        health_data['error'] = str(e)
    
    return jsonify(health_data)

# API: הפעלת/ביטול חיבור קבוע
@app.route('/api/persistent_login', methods=['POST'])
@login_required
def api_persistent_login():
    try:
        db = get_db()
        user_id = session['user_id']
        payload = request.get_json(silent=True) or {}
        enable = bool(payload.get('enable'))

        resp = jsonify({'ok': True, 'enabled': enable})

        if enable:
            # צור טוקן ושמור ב-DB
            token = secrets.token_urlsafe(32)
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=PERSISTENT_LOGIN_DAYS)
            try:
                db.remember_tokens.create_index('token', unique=True)
                db.remember_tokens.create_index('expires_at', expireAfterSeconds=0)
            except Exception:
                pass
            db.remember_tokens.update_one(
                {'user_id': user_id},
                {'$set': {'user_id': user_id, 'token': token, 'updated_at': now, 'expires_at': expires_at}, '$setOnInsert': {'created_at': now}},
                upsert=True
            )
            resp.set_cookie(
                REMEMBER_COOKIE_NAME,
                token,
                max_age=PERSISTENT_LOGIN_DAYS * 24 * 3600,
                secure=True,
                httponly=True,
                samesite='Lax'
            )
        else:
            # נטרל: מחיקת טוקן וקוקי
            try:
                token = request.cookies.get(REMEMBER_COOKIE_NAME)
                if token:
                    db.remember_tokens.delete_one({'user_id': user_id, 'token': token})
            except Exception:
                pass
            resp.delete_cookie(REMEMBER_COOKIE_NAME)

        return resp
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/api/ui_prefs', methods=['POST'])
@login_required
def api_ui_prefs():
    """שמירת העדפות UI (כרגע: font_scale)."""
    try:
        payload = request.get_json(silent=True) or {}
        font_scale = float(payload.get('font_scale', 1.0))
        theme = (payload.get('theme') or '').strip().lower()
        # הגבלה סבירה
        if font_scale < 0.85:
            font_scale = 0.85
        if font_scale > 1.6:
            font_scale = 1.6
        db = get_db()
        user_id = session['user_id']
        update_fields = {'ui_prefs.font_scale': font_scale, 'updated_at': datetime.now(timezone.utc)}
        if theme in {'classic','ocean','forest'}:
            update_fields['ui_prefs.theme'] = theme
        db.users.update_one({'user_id': user_id}, {'$set': update_fields}, upsert=True)
        # גם בקוקי כדי להשפיע מיידית בעמודים ציבוריים
        resp = jsonify({'ok': True, 'font_scale': font_scale, 'theme': theme or None})
        try:
            resp.set_cookie('ui_font_scale', str(font_scale), max_age=365*24*3600, samesite='Lax')
            if theme in {'classic','ocean','forest'}:
                resp.set_cookie('ui_theme', theme, max_age=365*24*3600, samesite='Lax')
        except Exception:
            pass
        return resp
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# --- Public statistics for landing/mini web app ---
@app.route('/api/public_stats')
def api_public_stats():
    """סטטיסטיקות גלובליות להצגה בעמוד הבית/מיני-ווב ללא התחברות.

    מחזיר:
    - total_users: סה"כ משתמשים שנוצרו אי פעם
    - active_users_24h: משתמשים שהיו פעילים ב-24 השעות האחרונות (updated_at)
    - total_snippets: סה"כ קטעי קוד ייחודיים שנשמרו אי פעם (distinct לפי user_id+file_name) כאשר התוכן לא ריק — כולל כאלה שנמחקו (is_active=false)
    """
    try:
        db = get_db()
        now_utc = datetime.now(timezone.utc)
        last_24h = now_utc - timedelta(hours=24)

        # Users
        try:
            total_users = int(db.users.count_documents({}))
        except Exception:
            total_users = 0
        try:
            active_users_24h = int(db.users.count_documents({"updated_at": {"$gte": last_24h}}))
        except Exception:
            active_users_24h = 0

        # Total distinct snippets (user_id+file_name), with non-empty code, including deleted (soft-deleted)
        try:
            pipeline = [
                {"$match": {"code": {"$type": "string"}}},
                {"$addFields": {
                    "code_size": {
                        "$cond": {
                            "if": {"$eq": [{"$type": "$code"}, "string"]},
                            "then": {"$strLenBytes": "$code"},
                            "else": 0,
                        }
                    }
                }},
                {"$match": {"code_size": {"$gt": 0}}},
                {"$group": {"_id": {"user_id": "$user_id", "file_name": "$file_name"}}},
                {"$count": "count"},
            ]
            res = list(db.code_snippets.aggregate(pipeline, allowDiskUse=True))
            total_snippets = int(res[0]["count"]) if res else 0
        except Exception:
            total_snippets = 0

        return jsonify({
            "ok": True,
            "total_users": total_users,
            "active_users_24h": active_users_24h,
            "total_snippets": total_snippets,
            "timestamp": now_utc.isoformat(),
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "total_users": 0,
            "active_users_24h": 0,
            "total_snippets": 0,
        }), 200

# --- Auth status & user info ---
@app.route('/api/me')
def api_me():
    """סטטוס התחברות ופרטי משתמש בסיסיים לצורך סוכנים/קליינט.

    לא זורק 401 כדי לאפשר בדיקה פשוטה; מחזיר ok=false אם לא מחובר.
    """
    try:
        is_auth = 'user_id' in session
        if not is_auth:
            return jsonify({
                'ok': False,
                'authenticated': False
            })
        user_data = session.get('user_data') or {}
        # שליפת העדפות בסיסיות מה‑DB (best-effort, ללא כשל)
        prefs = {}
        try:
            _db = get_db()
            u = _db.users.find_one({'user_id': session['user_id']}) or {}
            prefs = (u.get('ui_prefs') or {})
        except Exception:
            prefs = {}
        return jsonify({
            'ok': True,
            'authenticated': True,
            'user': {
                'user_id': session['user_id'],
                'username': user_data.get('username'),
                'first_name': user_data.get('first_name'),
                'last_name': user_data.get('last_name'),
            },
            'ui_prefs': {
                'font_scale': prefs.get('font_scale'),
                'theme': prefs.get('theme')
            }
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# --- External uptime public endpoint ---
@app.route('/api/uptime')
def api_uptime():
    """נתוני זמינות חיצוניים (ללא סודות)."""
    try:
        summary = fetch_external_uptime()
        if not summary:
            return jsonify({'ok': False, 'error': 'uptime_unavailable'}), 503
        safe = {
            'ok': True,
            'provider': summary.get('provider') or UPTIME_PROVIDER or None,
            'uptime_percentage': summary.get('uptime_percentage'),
            'status_url': summary.get('status_url') or (UPTIME_STATUS_URL or None),
        }
        return jsonify(safe)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# --- Public share route ---
@app.route('/share/<share_id>')
def public_share(share_id):
    """הצגת שיתוף פנימי בצורה ציבורית ללא התחברות.

    תומך בפרמטר view=md כדי להציג קבצי Markdown בעמוד התצוגה הייעודי (עם כפתורי שיתוף).
    """
    doc = get_internal_share(share_id)
    if not doc:
        return render_template('404.html'), 404

    code = doc.get('code', '')
    language = (doc.get('language', 'text') or 'text').lower()
    file_name = doc.get('file_name', 'snippet.txt')
    description = doc.get('description', '')

    # אם view=md והמסמך Markdown – נרנדר את עמוד md_preview עם דגל is_public
    try:
        view = (request.args.get('view') or '').strip().lower()
    except Exception:
        view = ''
    is_markdown = (language == 'markdown') or (isinstance(file_name, str) and file_name.lower().endswith('.md'))
    if view == 'md' and is_markdown:
        file_data = {
            'id': share_id,
            'file_name': file_name or 'README.md',
            'language': 'markdown',
        }
        return render_template('md_preview.html', user={}, file=file_data, md_code=code, bot_username=BOT_USERNAME_CLEAN, is_public=True)

    # ברירת מחדל: תצוגת קוד (כמו קודם)
    try:
        lexer = get_lexer_by_name(language, stripall=True)
    except Exception:
        try:
            lexer = guess_lexer(code)
        except Exception:
            from pygments.lexers import TextLexer
            lexer = TextLexer()
    formatter = HtmlFormatter(style='github-dark', linenos=True, cssclass='source', lineanchors='line', anchorlinenos=True)
    highlighted_code = highlight(code, lexer, formatter)
    css = formatter.get_style_defs('.source')

    size = len(code.encode('utf-8'))
    lines = len(code.split('\n'))
    created_at = doc.get('created_at')
    if isinstance(created_at, datetime):
        created_at_str = created_at.strftime('%d/%m/%Y %H:%M')
    else:
        try:
            created_at_str = datetime.fromisoformat(created_at).strftime('%d/%m/%Y %H:%M') if created_at else ''
        except Exception:
            created_at_str = ''

    file_data = {
        'id': share_id,
        'file_name': file_name,
        'language': language,
        'icon': get_language_icon(language),
        'description': description,
        'tags': [],
        'size': format_file_size(size),
        'lines': lines,
        'created_at': created_at_str,
        'updated_at': created_at_str,
        'version': 1,
    }
    return render_template('view_file.html', file=file_data, highlighted_code=highlighted_code, syntax_css=css)

# --- Public multiple-files share route (tokens created via /api/files/create-share-link) ---
@app.route('/shared/<token>')
def public_shared_files(token: str):
    """עמוד שיתוף ציבורי לקבצים מרובים לפי token מ-collection share_links.

    תומך בהצגת רשימה עם קישורי הורדה/צפייה לכל קובץ. אם פג תוקף, מחזיר 404.
    """
    try:
        db = get_db()
        doc = db.share_links.find_one({'token': token})
    except Exception:
        doc = None
    if not doc:
        return render_template('404.html'), 404

    # תוקף
    exp = doc.get('expires_at')
    try:
        now = datetime.now(timezone.utc)
        if isinstance(exp, datetime):
            expired = exp <= now
        else:
            expired = True
    except Exception:
        expired = True
    if expired:
        return render_template('404.html'), 404

    # שליפת קבצים
    file_ids = [oid for oid in (doc.get('file_ids') or []) if isinstance(oid, ObjectId)]
    if not file_ids:
        return render_template('404.html'), 404
    try:
        cursor = db.code_snippets.find({'_id': {'$in': file_ids}})
        files = list(cursor)
    except Exception:
        files = []
    if not files:
        return render_template('404.html'), 404

    # בניית רשימת פריטים לתצוגה
    view_items = []
    for f in files:
        code = f.get('code', '')
        language = (f.get('programming_language') or 'text').lower()
        file_name = (f.get('file_name') or 'snippet.txt')
        size = len((code or '').encode('utf-8'))
        lines = len((code or '').split('\n'))
        view_items.append({
            'id': str(f.get('_id')),
            'file_name': file_name,
            'language': language,
            'icon': get_language_icon(language),
            'size': format_file_size(size),
            'lines': lines,
            'code': code,
        })

    # תבנית בסיסית של רשימת קבצים ששותפו
    # שימוש ב-template קיים אם יש – אחרת נציג רשימה פשוטה דרך view_file עבור פריט בודד אינו מתאים כאן
    # לכן נשתמש ב-html פשוט בתוך אותו טמפלט בסיס
    # רנדר טמפלט ייעודי כדי למנוע עמוד ריק ולתת פריסה אחידה
    return render_template('shared_files.html', items=view_items)

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    print(f"Server error: {e}")
    return render_template('500.html'), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """טיפול בכל שגיאה אחרת"""
    print(f"Unhandled exception: {e}")
    import traceback
    traceback.print_exc()
    return render_template('500.html'), 500

# --- OpenAPI/Swagger/Redoc documentation endpoints ---
OPENAPI_SPEC_PATH = Path(ROOT_DIR) / 'docs' / 'openapi.yaml'

@app.route('/openapi.yaml')
def openapi_yaml():
    try:
        return send_file(OPENAPI_SPEC_PATH, mimetype='application/yaml')
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

@app.route('/docs')
def swagger_docs():
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
    <style>body { margin:0; } #swagger-ui { max-width: 100%; }</style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.onload = () => {
        window.ui = SwaggerUIBundle({ url: '/openapi.yaml', dom_id: '#swagger-ui' });
      };
    </script>
  </body>
  <script>/* Avoid CSP issues in simple dev setup */</script>
  </html>
"""
    return Response(html, mimetype='text/html')

@app.route('/redoc')
def redoc_docs():
    html = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>ReDoc</title>
    <style>body { margin:0; padding: 0; }</style>
    <script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"></script>
  </head>
  <body>
    <redoc spec-url='/openapi.yaml'></redoc>
    <script>
      try { Redoc.init('/openapi.yaml'); } catch (e) {}
    </script>
  </body>
</html>
"""
    return Response(html, mimetype='text/html')

# בדיקת קונפיגורציה בהפעלה
def check_configuration():
    """בדיקת משתני סביבה נדרשים"""
    required_vars = {
        'MONGODB_URL': MONGODB_URL,
        'BOT_TOKEN': BOT_TOKEN,
        'BOT_USERNAME': BOT_USERNAME
    }
    
    missing = []
    for var_name, var_value in required_vars.items():
        if not var_value:
            missing.append(var_name)
            print(f"WARNING: {var_name} is not configured!")
    
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        print("Please configure them in Render Dashboard or .env file")
    
    # בדיקת חיבור ל-MongoDB
    if MONGODB_URL:
        try:
            test_client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
            test_client.server_info()
            print("✓ MongoDB connection successful")
            test_client.close()
        except Exception as e:
            print(f"✗ MongoDB connection failed: {e}")
    
    return len(missing) == 0

if __name__ == '__main__':
    print("Starting Code Keeper Web App...")
    print(f"BOT_USERNAME: {BOT_USERNAME}")
    print(f"DATABASE_NAME: {DATABASE_NAME}")
    print(f"WEBAPP_URL: {WEBAPP_URL}")
    
    if check_configuration():
        print("Configuration check passed ✓")
    else:
        print("WARNING: Configuration issues detected!")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('DEBUG', 'false').lower() == 'true')
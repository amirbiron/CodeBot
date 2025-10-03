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

# הוספת נתיב ה-root של הפרויקט ל-PYTHONPATH כדי לאפשר import ל-"database" כשהסקריפט רץ מתוך webapp/
ROOT_DIR = str(Path(__file__).resolve().parents[1])
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# יצירת האפליקציה
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.permanent_session_lifetime = timedelta(days=30)  # סשן נשמר ל-30 יום

# הגדרות
MONGODB_URL = os.getenv('MONGODB_URL')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'code_keeper_bot')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'my_code_keeper_bot')
BOT_USERNAME_CLEAN = (BOT_USERNAME or '').lstrip('@')
WEBAPP_URL = os.getenv('WEBAPP_URL', 'https://code-keeper-webapp.onrender.com')
PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', '')
_ttl_env = os.getenv('PUBLIC_SHARE_TTL_DAYS', '7')
try:
    PUBLIC_SHARE_TTL_DAYS = max(1, int(_ttl_env))
except Exception:
    PUBLIC_SHARE_TTL_DAYS = 7

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
    return {
        'bot_username': BOT_USERNAME_CLEAN,
        'ui_font_scale': font_scale,
        'ui_theme': theme,
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
        except Exception as e:
            print(f"Failed to connect to MongoDB: {e}")
            raise
    return db

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
    return render_template('index.html', 
                         bot_username=BOT_USERNAME_CLEAN,
                         logged_in='user_id' in session,
                         user=session.get('user_data', {}))

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
    
    # פרמטרים לחיפוש ומיון
    search_query = request.args.get('q', '')
    language_filter = request.args.get('lang', '')
    category_filter = request.args.get('category', '')
    sort_by = request.args.get('sort', 'created_at')
    repo_name = request.args.get('repo', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 20
    
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
                return render_template('files.html',
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
        # שליפת רשימת MRU מהאוסף recent_opens לפי user_id, ממוינת מהאחרון לראשון
        files_list = []
        try:
            recent_cursor = db.recent_opens.find({'user_id': user_id}).sort('last_opened_at', DESCENDING).limit(100)
            recent_items = list(recent_cursor)
            total_count = len(recent_items)
            for item in recent_items:
                fname = item.get('file_name') or ''
                # קח את הגרסה האחרונה הפעילה של אותו file_name לתצוגה עקבית
                try:
                    latest = db.code_snippets.find_one(
                        {
                            'user_id': user_id,
                            'file_name': fname,
                            '$or': [
                                {'is_active': True},
                                {'is_active': {'$exists': False}}
                            ]
                        },
                        sort=[('version', -1)]
                    )
                except Exception:
                    latest = None
                if not latest:
                    # אם אין תיעוד תואם – דלג
                    continue
                code_str = latest.get('code') or ''
                lang_raw = (latest.get('programming_language') or '').lower() or 'text'
                lang_display = 'markdown' if (lang_raw in {'', 'text'} and str(fname).lower().endswith('.md')) else lang_raw
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
                    'last_opened_at': format_datetime_display(item.get('last_opened_at')),
                })
        except Exception:
            files_list = []
            total_count = 0
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
        total_pages = 1
        return render_template('files.html',
                             user=session['user_data'],
                             files=files_list,
                             total_count=total_count,
                             languages=languages,
                             search_query=search_query,
                             language_filter=language_filter,
                             category_filter=category_filter,
                             sort_by=sort_by,
                             page=1,
                             total_pages=total_pages,
                             has_prev=False,
                             has_next=False,
                             bot_username=BOT_USERNAME_CLEAN)

    # אם לא עשינו aggregation כבר (בקטגוריות large/other) — עבור all נשתמש גם באגרגציה
    if not category_filter:
        sort_dir = -1 if sort_by.startswith('-') else 1
        sort_field_local = sort_by.lstrip('-')
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
            {'$match': {'code_size': {'$gt': 0}}},
            {'$sort': {'file_name': 1, 'version': -1}},
            {'$group': {'_id': '$file_name', 'latest': {'$first': '$$ROOT'}}},
            {'$replaceRoot': {'newRoot': '$latest'}},
            {'$sort': {sort_field_local: sort_dir}},
            {'$skip': (page - 1) * per_page},
            {'$limit': per_page},
        ]
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
    
    # עדכון רשימת "נפתחו לאחרונה" (MRU) עבור המשתמש הנוכחי
    try:
        from pymongo import ASCENDING, DESCENDING  # ייבוא מקומי כדי להימנע משינויי טופ-לבל
        coll = db.recent_opens
        try:
            coll.create_index([('user_id', ASCENDING), ('file_name', ASCENDING)], name='user_file_unique', unique=True)
            coll.create_index([('user_id', ASCENDING), ('last_opened_at', DESCENDING)], name='user_last_opened_idx')
        except Exception:
            pass
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
        return render_template('view_file.html',
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
    
    # בדיקה אם הקובץ בינארי
    if is_binary_file(code, file.get('file_name', '')):
        return render_template('view_file.html',
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
        'version': file.get('version', 1)
    }
    
    return render_template('view_file.html',
                         user=session['user_data'],
                         file=file_data,
                         highlighted_code=highlighted_code,
                         syntax_css=css,
                         raw_code=code)

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
    return render_template('md_preview.html', user=session.get('user_data', {}), file=file_data, md_code=code, bot_username=BOT_USERNAME_CLEAN)

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
                    return redirect(url_for('files'))
                error = 'שמירת הקובץ נכשלה'
        except Exception as e:
            error = f'שגיאה בהעלאה: {e}'
    # שליפת שפות קיימות להצעה
    languages = db.code_snippets.distinct('programming_language', {'user_id': user_id}) if db is not None else []
    languages = sorted([l for l in languages if l]) if languages else []
    return render_template('upload.html', bot_username=BOT_USERNAME_CLEAN, user=session['user_data'], languages=languages, error=error, success=success)

@app.route('/api/stats')
@login_required
def api_stats():
    """API לקבלת סטטיסטיקות"""
    db = get_db()
    user_id = session['user_id']
    
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
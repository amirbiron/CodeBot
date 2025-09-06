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

from flask import Flask, render_template, jsonify, request, session, redirect, url_for, send_file, abort
from pymongo import MongoClient, DESCENDING
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
from bson import ObjectId
import requests

# יצירת האפליקציה
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# הגדרות
MONGODB_URL = os.getenv('MONGODB_URL')
DATABASE_NAME = os.getenv('DATABASE_NAME', 'code_keeper_bot')
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'my_code_keeper_bot')
WEBAPP_URL = os.getenv('WEBAPP_URL', 'https://code-keeper-webapp.onrender.com')

# חיבור ל-MongoDB
client = None
db = None

def get_db():
    """מחזיר חיבור למסד הנתונים"""
    global client, db
    if client is None:
        client = MongoClient(MONGODB_URL)
        db = client[DATABASE_NAME]
    return db

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

def format_file_size(size_bytes: int) -> str:
    """מעצב גודל קובץ לתצוגה ידידותית"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"

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

# Routes

@app.route('/')
def index():
    """דף הבית"""
    return render_template('index.html', 
                         bot_username=BOT_USERNAME,
                         logged_in='user_id' in session,
                         user=session.get('user_data', {}))

@app.route('/login')
def login():
    """דף התחברות"""
    return render_template('login.html', bot_username=BOT_USERNAME)

@app.route('/auth/telegram', methods=['GET', 'POST'])
def telegram_auth():
    """טיפול באימות Telegram"""
    auth_data = dict(request.args) if request.method == 'GET' else request.get_json()
    
    if not verify_telegram_auth(auth_data):
        return jsonify({'error': 'Invalid authentication'}), 401
    
    # שמירת נתוני המשתמש בסשן
    session['user_id'] = int(auth_data['id'])
    session['user_data'] = {
        'id': int(auth_data['id']),
        'first_name': auth_data.get('first_name', ''),
        'last_name': auth_data.get('last_name', ''),
        'username': auth_data.get('username', ''),
        'photo_url': auth_data.get('photo_url', '')
    }
    
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    """התנתקות"""
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """דשבורד עם סטטיסטיקות"""
    db = get_db()
    user_id = session['user_id']
    
    # שליפת סטטיסטיקות
    total_files = db.code_snippets.count_documents({'user_id': user_id})
    
    # חישוב נפח כולל
    pipeline = [
        {'$match': {'user_id': user_id}},
        {'$group': {
            '_id': None,
            'total_size': {'$sum': {'$strLenBytes': '$code'}}
        }}
    ]
    size_result = list(db.code_snippets.aggregate(pipeline))
    total_size = size_result[0]['total_size'] if size_result else 0
    
    # שפות פופולריות
    languages_pipeline = [
        {'$match': {'user_id': user_id}},
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
        {'user_id': user_id},
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
                         stats=stats)

@app.route('/files')
@login_required
def files():
    """רשימת כל הקבצים של המשתמש"""
    db = get_db()
    user_id = session['user_id']
    
    # פרמטרים לחיפוש ומיון
    search_query = request.args.get('q', '')
    language_filter = request.args.get('lang', '')
    sort_by = request.args.get('sort', 'created_at')
    page = int(request.args.get('page', 1))
    per_page = 20
    
    # בניית שאילתה
    query = {'user_id': user_id}
    
    if search_query:
        query['$or'] = [
            {'file_name': {'$regex': search_query, '$options': 'i'}},
            {'description': {'$regex': search_query, '$options': 'i'}},
            {'tags': {'$in': [search_query.lower()]}}
        ]
    
    if language_filter:
        query['programming_language'] = language_filter
    
    # ספירת סך הכל
    total_count = db.code_snippets.count_documents(query)
    
    # שליפת הקבצים
    sort_order = DESCENDING if sort_by.startswith('-') else 1
    sort_field = sort_by.lstrip('-')
    
    files_cursor = db.code_snippets.find(query).sort(sort_field, sort_order).skip((page - 1) * per_page).limit(per_page)
    
    files_list = []
    for file in files_cursor:
        files_list.append({
            'id': str(file['_id']),
            'file_name': file['file_name'],
            'language': file.get('programming_language', 'text'),
            'icon': get_language_icon(file.get('programming_language', '')),
            'description': file.get('description', ''),
            'tags': file.get('tags', []),
            'size': format_file_size(len(file.get('code', '').encode('utf-8'))),
            'lines': len(file.get('code', '').split('\n')),
            'created_at': file.get('created_at', datetime.now()).strftime('%d/%m/%Y %H:%M'),
            'updated_at': file.get('updated_at', datetime.now()).strftime('%d/%m/%Y %H:%M')
        })
    
    # רשימת שפות לפילטר
    languages = db.code_snippets.distinct('programming_language', {'user_id': user_id})
    
    # חישוב עמודים
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template('files.html',
                         user=session['user_data'],
                         files=files_list,
                         total_count=total_count,
                         languages=sorted(languages) if languages else [],
                         search_query=search_query,
                         language_filter=language_filter,
                         sort_by=sort_by,
                         page=page,
                         total_pages=total_pages,
                         has_prev=page > 1,
                         has_next=page < total_pages)

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
    
    # הדגשת syntax
    code = file.get('code', '')
    language = file.get('programming_language', 'text')
    
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
        'lines': len(code.split('\n')),
        'created_at': file.get('created_at', datetime.now()).strftime('%d/%m/%Y %H:%M'),
        'updated_at': file.get('updated_at', datetime.now()).strftime('%d/%m/%Y %H:%M'),
        'version': file.get('version', 1)
    }
    
    return render_template('view_file.html',
                         user=session['user_data'],
                         file=file_data,
                         highlighted_code=highlighted_code,
                         syntax_css=css)

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

@app.route('/api/stats')
@login_required
def api_stats():
    """API לקבלת סטטיסטיקות"""
    db = get_db()
    user_id = session['user_id']
    
    stats = {
        'total_files': db.code_snippets.count_documents({'user_id': user_id}),
        'languages': list(db.code_snippets.distinct('programming_language', {'user_id': user_id})),
        'recent_activity': []
    }
    
    recent = db.code_snippets.find(
        {'user_id': user_id},
        {'file_name': 1, 'created_at': 1}
    ).sort('created_at', DESCENDING).limit(10)
    
    for item in recent:
        stats['recent_activity'].append({
            'file_name': item['file_name'],
            'created_at': item.get('created_at', datetime.now()).isoformat()
        })
    
    return jsonify(stats)

@app.route('/health')
def health():
    """בדיקת תקינות"""
    try:
        # בדיקת חיבור ל-MongoDB
        db = get_db()
        db.command('ping')
        db_status = 'connected'
    except:
        db_status = 'disconnected'
    
    return jsonify({
        'status': 'healthy' if db_status == 'connected' else 'degraded',
        'message': 'Web app is running!',
        'version': '2.0.0',
        'database': db_status,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('DEBUG', 'false').lower() == 'true')
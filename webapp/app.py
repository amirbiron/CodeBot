#!/usr/bin/env python3
"""
Web Application for Code Keeper Bot
אפליקציית ווב לבוט שומר קבצי קוד
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
import secrets
import hashlib
import json
from typing import Optional, Dict, Any

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file, abort
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import pymongo
from bson import ObjectId
import requests

# Import from the bot's modules
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import config
from database import DatabaseManager
from utils import detect_language_from_filename, get_language_emoji

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')

# Configuration
app.config['SECRET_KEY'] = os.getenv('WEBAPP_SECRET_KEY', secrets.token_hex(32))
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Enable CORS for API endpoints
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Initialize database
db = DatabaseManager()

# JWT configuration
JWT_SECRET = os.getenv('JWT_SECRET', app.config['SECRET_KEY'])
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24

# Telegram Bot Token for verification
BOT_TOKEN = config.BOT_TOKEN

def create_jwt_token(user_id: int, username: str) -> str:
    """Create a JWT token for user authentication"""
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
        return None

def login_required(f):
    """Decorator to require login for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check session
        if 'user_id' not in session:
            # Check for JWT token in header
            auth_header = request.headers.get('Authorization')
            if auth_header:
                try:
                    token = auth_header.split(' ')[1]  # Bearer <token>
                    payload = verify_jwt_token(token)
                    if payload:
                        session['user_id'] = payload['user_id']
                        session['username'] = payload.get('username', 'User')
                    else:
                        return jsonify({'error': 'Invalid or expired token'}), 401
                except:
                    return jsonify({'error': 'Invalid authorization header'}), 401
            else:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Authentication required'}), 401
                return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    """Homepage - redirect to dashboard if logged in"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login')
def login():
    """Login page with Telegram authentication"""
    return render_template('login.html', bot_username=os.getenv('BOT_USERNAME', 'CodeKeeperBot'))

@app.route('/auth/telegram', methods=['POST'])
def telegram_auth():
    """Handle Telegram authentication"""
    try:
        data = request.get_json()
        
        # Verify Telegram auth data
        auth_data = data.get('auth_data', {})
        if not verify_telegram_auth(auth_data):
            return jsonify({'error': 'Invalid authentication data'}), 401
        
        user_id = auth_data.get('id')
        username = auth_data.get('username', f'user_{user_id}')
        first_name = auth_data.get('first_name', '')
        
        # Save user to database if not exists
        db.save_user(user_id, username)
        
        # Create session
        session['user_id'] = user_id
        session['username'] = username
        session['first_name'] = first_name
        session.permanent = True
        
        # Create JWT token
        token = create_jwt_token(user_id, username)
        
        return jsonify({
            'success': True,
            'token': token,
            'user': {
                'id': user_id,
                'username': username,
                'first_name': first_name
            }
        })
        
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return jsonify({'error': 'Authentication failed'}), 500

def verify_telegram_auth(auth_data: dict) -> bool:
    """Verify Telegram authentication data"""
    try:
        check_hash = auth_data.get('hash')
        if not check_hash:
            return False
        
        # Create data-check-string
        data_check_arr = []
        for key in sorted(auth_data.keys()):
            if key != 'hash':
                data_check_arr.append(f"{key}={auth_data[key]}")
        
        data_check_string = '\n'.join(data_check_arr)
        
        # Calculate hash
        secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
        calculated_hash = hashlib.sha256(
            (data_check_string.encode() + secret_key)
        ).hexdigest()
        
        # Verify hash
        if calculated_hash != check_hash:
            return False
        
        # Check auth date (not older than 1 day)
        auth_date = int(auth_data.get('auth_date', 0))
        if (datetime.now().timestamp() - auth_date) > 86400:
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"Auth verification error: {e}")
        return False

@app.route('/logout')
def logout():
    """Logout user"""
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    """User dashboard"""
    user_id = session['user_id']
    
    # Get user statistics
    stats = db.get_user_stats(user_id)
    
    # Get recent files
    recent_files = db.get_user_files(user_id, limit=10)
    
    return render_template('dashboard.html',
                         username=session.get('username', 'User'),
                         stats=stats,
                         recent_files=recent_files)

@app.route('/files')
@login_required
def files():
    """Files listing page"""
    user_id = session['user_id']
    
    # Get pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '')
    language = request.args.get('language', '')
    
    # Get files with pagination
    offset = (page - 1) * per_page
    
    if search or language:
        files = db.search_code(user_id, search, programming_language=language if language else None)
    else:
        files = db.get_user_files(user_id, limit=per_page, offset=offset)
    
    # Get total count for pagination
    total_files = db.get_user_stats(user_id).get('total_files', 0)
    total_pages = (total_files + per_page - 1) // per_page
    
    return render_template('files.html',
                         files=files,
                         page=page,
                         total_pages=total_pages,
                         search=search,
                         language=language)

@app.route('/file/<file_id>')
@login_required
def view_file(file_id):
    """View a specific file"""
    user_id = session['user_id']
    
    # Get file from database
    file_data = db.get_code_snippet(user_id, file_id)
    
    if not file_data:
        abort(404)
    
    # Get file versions
    versions = db.get_file_versions(user_id, file_id)
    
    return render_template('file_view.html',
                         file=file_data,
                         versions=versions,
                         language_emoji=get_language_emoji(file_data.get('programming_language', 'text')))

@app.route('/file/<file_id>/download')
@login_required
def download_file(file_id):
    """Download a file"""
    user_id = session['user_id']
    
    # Get file from database
    file_data = db.get_code_snippet(user_id, file_id)
    
    if not file_data:
        abort(404)
    
    # Create file content
    content = file_data.get('code', '')
    filename = file_data.get('file_name', 'code.txt')
    
    # Send file
    from io import BytesIO
    file_io = BytesIO(content.encode('utf-8'))
    file_io.seek(0)
    
    return send_file(file_io,
                     as_attachment=True,
                     download_name=filename,
                     mimetype='text/plain')

# API Endpoints
@app.route('/api/stats')
@login_required
def api_stats():
    """Get user statistics"""
    user_id = session['user_id']
    stats = db.get_user_stats(user_id)
    return jsonify(stats)

@app.route('/api/files')
@login_required
def api_files():
    """Get user files"""
    user_id = session['user_id']
    
    # Get parameters
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    search = request.args.get('search', '')
    language = request.args.get('language', '')
    
    if search or language:
        files = db.search_code(user_id, search, programming_language=language if language else None)
    else:
        files = db.get_user_files(user_id, limit=limit, offset=offset)
    
    # Convert ObjectId to string for JSON serialization
    for file in files:
        if '_id' in file and isinstance(file['_id'], ObjectId):
            file['_id'] = str(file['_id'])
        if 'created_at' in file and hasattr(file['created_at'], 'isoformat'):
            file['created_at'] = file['created_at'].isoformat()
        if 'updated_at' in file and hasattr(file['updated_at'], 'isoformat'):
            file['updated_at'] = file['updated_at'].isoformat()
    
    return jsonify({
        'files': files,
        'total': len(files),
        'limit': limit,
        'offset': offset
    })

@app.route('/api/file/<file_id>')
@login_required
def api_get_file(file_id):
    """Get a specific file"""
    user_id = session['user_id']
    
    file_data = db.get_code_snippet(user_id, file_id)
    
    if not file_data:
        return jsonify({'error': 'File not found'}), 404
    
    # Convert ObjectId to string
    if '_id' in file_data and isinstance(file_data['_id'], ObjectId):
        file_data['_id'] = str(file_data['_id'])
    if 'created_at' in file_data and hasattr(file_data['created_at'], 'isoformat'):
        file_data['created_at'] = file_data['created_at'].isoformat()
    if 'updated_at' in file_data and hasattr(file_data['updated_at'], 'isoformat'):
        file_data['updated_at'] = file_data['updated_at'].isoformat()
    
    return jsonify(file_data)

@app.route('/api/search')
@login_required
def api_search():
    """Search files"""
    user_id = session['user_id']
    
    query = request.args.get('q', '')
    language = request.args.get('language', '')
    tags = request.args.getlist('tags')
    
    results = db.search_code(user_id, query, 
                            programming_language=language if language else None,
                            tags=tags if tags else None)
    
    # Convert ObjectId to string
    for file in results:
        if '_id' in file and isinstance(file['_id'], ObjectId):
            file['_id'] = str(file['_id'])
        if 'created_at' in file and hasattr(file['created_at'], 'isoformat'):
            file['created_at'] = file['created_at'].isoformat()
        if 'updated_at' in file and hasattr(file['updated_at'], 'isoformat'):
            file['updated_at'] = file['updated_at'].isoformat()
    
    return jsonify({
        'results': results,
        'count': len(results),
        'query': query
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    try:
        # Check database connection
        db.db.command('ping')
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'version': '1.0.0'
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 503

@app.errorhandler(404)
def not_found(error):
    """404 error handler"""
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    """500 error handler"""
    logger.error(f"Internal error: {error}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    return render_template('500.html'), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV') == 'development'
    app.run(host='0.0.0.0', port=port, debug=debug)
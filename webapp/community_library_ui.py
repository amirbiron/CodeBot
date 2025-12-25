from __future__ import annotations

from flask import Blueprint, render_template, session
import os

from webapp.activity_tracker import log_user_event

community_library_ui = Blueprint('community_library_ui', __name__)


@community_library_ui.route('/community-library')
def community_library_page():
    # רישום פעילות "כניסה לספרייה הקהילתית" (Best-effort)
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
    return render_template('community_library.html', is_admin=is_admin)

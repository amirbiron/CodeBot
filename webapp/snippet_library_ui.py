from __future__ import annotations

from flask import Blueprint, render_template, session
import os

snippet_library_ui = Blueprint('snippet_library_ui', __name__)


@snippet_library_ui.route('/snippets')
def snippets_page():
    # Determine admin from ENV list
    is_admin = False
    try:
        uid = int(session.get('user_id')) if session.get('user_id') is not None else 0
        admin_ids_env = os.getenv('ADMIN_USER_IDS', '')
        admin_ids = [int(x.strip()) for x in admin_ids_env.split(',') if x.strip().isdigit()]
        is_admin = uid in admin_ids
    except Exception:
        is_admin = False
    return render_template('snippets.html', is_admin=is_admin)

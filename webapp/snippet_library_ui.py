from __future__ import annotations

from flask import Blueprint, render_template, session
import os

from webapp.activity_tracker import log_user_event

snippet_library_ui = Blueprint('snippet_library_ui', __name__)


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
    return render_template('snippets.html', is_admin=is_admin)


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

"""
Note Boards UI routes (server-rendered pages).

בתבנית ``webapp/collections_ui.py``: הראוטים כאן מגישים HTML בלבד, וכל
הנתונים נשלפים מה-API בצד הלקוח. כך העמוד חוזר מהר, והלוגיקה חיה במקום
אחד — ``webapp/note_boards_api.py``.
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, session

boards_ui = Blueprint('boards_ui', __name__)


@boards_ui.route('/boards')
def boards_page():
    """רשימת הלוחות."""
    if 'user_id' not in session:
        return redirect('/login?next=/boards')
    return render_template('note_boards.html')


@boards_ui.route('/boards/<board_id>')
def board_page(board_id: str):
    """משטח לוח יחיד.

    ``board_id`` מועבר לתבנית ולא נבדק כאן: הבעלות נאכפת ב-API, שמחזיר
    404 ללוח שאינו של המשתמש. בדיקה כפולה כאן הייתה מחייבת גישה למסד
    בראוט שכל תפקידו להגיש HTML.
    """
    if 'user_id' not in session:
        return redirect(f'/login?next=/boards/{board_id}')
    return render_template('note_board.html', board_id=board_id)

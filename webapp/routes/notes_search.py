"""עמוד חיפוש הפתקים (server-rendered).

בתבנית ``webapp/boards_ui.py``: הראוט כאן מגיש HTML בלבד, והתוצאות
נשלפות בצד הלקוח מ-``/api/sticky-notes/search``. כך העמוד חוזר מהר,
והלוגיקה חיה במקום אחד — ``webapp/sticky_notes_api.py``.

**למה עמוד ולא מודאל.** חיפוש שמחזיר תצוגה מקדימה של 200 תווים לכל
תוצאה צריך מקום, והתוצאה היא יעד שרוצים לשתף ולחזור אליו — כלומר URL.
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, session

notes_search_bp = Blueprint('notes_search', __name__)


@notes_search_bp.route('/notes/search')
def notes_search_page():
    """עמוד החיפוש.

    ``login_required`` אינו בשימוש כאן במכוון, בדיוק כמו בשאר עמודי
    הפתקים: הבדיקה הידנית שומרת את ``next``, כך שסשן שפג מחזיר את
    המשתמש לעמוד החיפוש אחרי ההתחברות במקום לזרוק אותו לשורש.

    אין כאן גישה למסד ואין בדיקת בעלות: ה-API הוא שמסנן לפי
    ``user_id``, ובדיקה כפולה בראוט שכל תפקידו להגיש HTML הייתה מחייבת
    שאילתה שאין לה מה להוסיף.
    """
    if 'user_id' not in session:
        return redirect('/login?next=/notes/search')

    # **הפלטה מגיעה מהשרת ולא מוקלדת בתבנית.** ``NOTE_COLORS`` הוא מקור
    # האמת היחיד לגוונים ולתוויות, ורשימה שנייה ב-HTML הייתה נסחפת ממנו
    # בדיוק כשמישהו מוסיף צבע. הגוונים עצמם נכתבים כ-``style`` מוטבע ולא
    # ב-CSS, כי ``docs/webapp/theming_and_css`` אוסר HEX קשיח בקובץ CSS
    # — ובמקביל מחריג את הפתקים מהערכה במפורש. שתי הדרישות מתקיימות יחד
    # רק כשהערך זורם מהפייתון.
    from sticky_notes_target import NOTE_COLORS, NOTE_COLOR_ORDER

    palette = [
        {
            'id': color_id,
            'hex': str(NOTE_COLORS[color_id]['hex']),
            'label': str(NOTE_COLORS[color_id]['label']),
        }
        for color_id in NOTE_COLOR_ORDER
    ]
    return render_template('notes_search.html', note_palette=palette)

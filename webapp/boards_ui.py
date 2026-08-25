"""
Note Boards UI routes (server-rendered pages).

בתבנית ``webapp/collections_ui.py``: הראוטים כאן מגישים HTML בלבד, וכל
הנתונים נשלפים מה-API בצד הלקוח. כך העמוד חוזר מהר, והלוגיקה חיה במקום
אחד — ``webapp/note_boards_api.py``.
"""
from __future__ import annotations

from urllib.parse import quote

from flask import Blueprint, redirect, render_template, session

try:  # type: ignore
    from bson import ObjectId  # type: ignore
except Exception:  # pragma: no cover
    def ObjectId(x):  # type: ignore
        s = str(x or "")
        if len(s) != 24:
            raise ValueError("malformed ObjectId")
        return s

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


@boards_ui.route('/note/<note_id>')
def note_permalink(note_id: str):
    """קישור קבוע לפתק — ומשם הפניה למקום שבו הוא באמת יושב.

    **זה תיקון השורש לבעיית ה-deep link.** עד היום כל צרכן הרכיב את
    ה-URL בעצמו מהמזהים שהיו לו ביד: ``sw.js`` בנה ``/md/<file_id>``,
    והפעמון ב-``base.html`` עשה אותו דבר. לפתק לוח אין ``file_id``, ולכן
    ההתראה נחתה בשורש האתר ולחיצה על הפעמון פשוט לא עשתה כלום.

    עכשיו יש בונה אחד, והוא כאן. הצרכנים פותחים ``/note/<id>`` ולא
    צריכים לדעת דבר על סוג הפתק — כולל סוג שלישי שיתווסף בעתיד.

    ``login_required`` אינו בשימוש כאן במכוון: הבדיקה הידנית מאפשרת
    לשמור ``next`` בדיוק כמו בשאר עמודי הלוחות, כך שסשן שפג מחזיר את
    המשתמש לפתק אחרי ההתחברות במקום לזרוק אותו לשורש.
    """
    if 'user_id' not in session:
        return redirect(f'/login?next=/note/{note_id}')

    try:
        from webapp.app import get_db
        db = get_db()
        note = db.sticky_notes.find_one(
            {'_id': ObjectId(str(note_id)), 'user_id': int(session['user_id'])},
            {'file_id': 1, 'board_id': 1, 'repo_name': 1, 'repo_path': 1},
        )
    except Exception:
        note = None

    if not note:
        # פתק שנמחק, או מזהה פגום. הלוחות הם היעד הבטוח.
        return redirect('/boards')

    board_id = str(note.get('board_id') or '')
    if board_id:
        return redirect(f'/boards/{board_id}?note={note_id}')

    file_id = str(note.get('file_id') or '')
    if file_id:
        return redirect(f'/md/{file_id}?note={note_id}')

    # פתק על קובץ בריפו ממורר. **זה היה חסר** — הפונקציה הכירה שני סוגי
    # יעד בלבד, ולכן פתק ריפו נפל אל ``/boards`` הכללי: לחיצה על תזכורת
    # הביאה את המשתמש ללוחות במקום לקובץ שהפתק יושב עליו.
    #
    # דפדפן הריפו הוא SPA שמחזיק את הריפו הנבחר ב-session ובּ-localStorage,
    # ולא ב-URL: ``updateUrlHash`` כותב ``file`` ו-``search`` ב-hash בלבד,
    # ולעולם לא ``repo``. לכן URL רגיל נראה ``/repo/#file=X`` בלי שם ריפו.
    #
    # ``?repo=`` ו-``?note=`` כאן הם **כוונה חד-פעמית**, לא מצב: הם קיימים
    # רק כדי לכפות ריפו מבחוץ בטעינה אחת, כי ההתראה חייבת להעביר גם ריפו
    # וגם פתק, וה-hash לבדו נושא רק קובץ. ``get_current_repo_name`` נותנת
    # ל-``repo`` עדיפות מעל ה-session בדיוק בשביל הטעינה הזו.
    #
    # **הצד השני של החוזה חי ב-``consumeOneShotUrlParams``** שב-
    # ``repo-browser.js``: הוא מסיר את שניהם מה-URL מיד אחרי הצריכה. בלי
    # זה הם היו שורדים לריענון וכופים את הריפו של הקישור המקורי גם אחרי
    # שהמשתמש עבר לריפו אחר. מי שמשנה כאן פרמטר — שיעדכן גם שם.
    #
    # **שני הערכים מאומתים כאן מחדש, מול אותו חוזה שיצר אותם**, ולא רק
    # מקודדים. מקור הערכים הוא מסמך הפתק, כלומר קלט שהגיע פעם ממשתמש —
    # ו-CodeQL מסמן בצדק זרימה כזו אל ``redirect`` (``py/url-redirection``).
    # היעד כאן אמנם מתחיל תמיד בליטרל ``/repo/`` ולכן אינו יכול לצאת מהאתר,
    # אבל אימות מפורש עדיף על הסתמכות על צורת המחרוזת: מסמך עם ``repo_name``
    # פגום — ממסלול כתיבה עתידי, ממיגרציה, מגיבוי — לא ייצר כאן קישור מוזר
    # אלא ייפול לברירת המחדל.
    #
    # ``REPO_NAME_PATTERN`` מיובא ולא משוכפל: אותו דפוס כבר מוקלד בשלושה
    # מקומות, ורביעי היה מבטיח שהם ייפרדו. ``normalize_repo_path`` היא
    # בדיוק הפונקציה שכתבה את הנתיב, ולכן הקריאה כאן מתכנסת לאותה צורה
    # (והיא גם דוחה traversal ומחזירה מחרוזת ריקה).
    from services.git_mirror_service import GitMirrorService
    from sticky_notes_target import normalize_repo_path

    repo_name = str(note.get('repo_name') or '')
    repo_path = normalize_repo_path(note.get('repo_path'))
    # ``fullmatch`` ולא ``match``: ב-Python ``$`` תואם גם **לפני** תו שורה
    # חדשה בסוף, ולכן ``"CodeBot\n"`` היה עובר את הדפוס. עם ``quote`` הוא
    # לא היה שובר את ה-URL, אבל אימות שמקבל ערך שהוא עצמו פוסל אינו אימות.
    if repo_name and repo_path and GitMirrorService.REPO_NAME_PATTERN.fullmatch(repo_name):
        return redirect(
            f'/repo/?repo={quote(repo_name, safe="")}&note={note_id}'
            f'#file={quote(repo_path, safe="/")}'
        )

    return redirect('/boards')

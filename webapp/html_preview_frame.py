"""המסגרת של תצוגת ה-HTML (``/html/<id>``): ה-CSP של ``/raw_html/<id>``, ומדווח הגלילה שהפתקים נשענים עליו.

**למה יש כאן סקריפט בכלל.** ``/raw_html`` מגיש את ה-HTML של המשתמש בתוך iframe מבודד: ``sandbox`` בלי
``allow-same-origin``, כלומר מקור אטום, והדף שמסביב אינו יכול לקרוא שום דבר מתוך המסגרת — לא את התוכן ולא כמה
גללו בה. פתק "על הקובץ" (``surface``) חייב לנוע עם התוכן, ולכן מישהו בתוך המסגרת צריך לספר לדף כמה גללו. זה
המדווח: סקריפט קטן שמצורף לסוף ה-HTML ושולח לדף, ב-``postMessage``, את מיקום הגלילה, את רוחב התוכן ואת הכיוון —
ותו לא. הצרכן בצד הדפדפן הוא ``webapp/static/js/html-preview-notes.js``.

**שלושה מצבים, ופונקציה אחת שבונה את ה-CSP שלהם** (:func:`raw_html_csp`):

* **בלי מדווח** — ``/raw_html/<id>`` כמו שהוא, וזה מה ש"חלון חדש" פותח: אין סקריפטים בכלל (``sandbox`` בלי
  ``allow-scripts``, ו-``script-src 'none'``). המחרוזת זהה בדיוק למה שהראוט שלח לפני שהמדווח נוסף.
* **מדווח, בלי JS של המשתמש** — ברירת המחדל של המסגרת בעמוד התצוגה (:data:`REPORT_SCROLL_PARAM`). ה-sandbox
  מתיר סקריפטים, ו-``script-src`` מתיר רק את המדווח, לפי ``nonce`` חד-פעמי שנוצר לכל תשובה. סקריפט שכתוב בקובץ
  עצמו — ``<script>``, ‏``onclick``, ‏``onerror`` — אינו נושא את ה-``nonce`` ולכן נחסם. נמדד בכרומיום (נובמבר
  2026), ונבדק ב-``tests/test_html_preview_notes_browser.py``.
* **JS של המשתמש** (``?allow=scripts``) — ``script-src 'unsafe-inline'`` כמו קודם, והמדווח מצורף **בלי**
  ``nonce``: ``nonce`` באותה הנחיה מבטל את ``'unsafe-inline'``, והסקריפטים שהמשתמש ביקש להריץ היו נחסמים. נמדד
  בכרומיום: עם ``'unsafe-inline' 'nonce-…'`` רק הסקריפט שנושא את ה-``nonce`` רץ.

**כל הנחיות ה-``'none'`` כאן מכוונות**, וההיתר למקרה חריג ניתן בפונקציה הזו בלבד, לכל תשובה של ``/raw_html``
לחוד — לא ב-CSP הכללי של האתר (``_add_default_csp`` ב-``webapp/app.py``), שמוסיף מדיניות רק כשהתשובה לא קבעה
אחת. ``amir-bug-patterns``, ``BY-STACK/browser-policy.md`` B1.

**למה בסוף ה-HTML ולא בתחילתו.** סקריפט לפני ``<!doctype html>`` היה מבטל אותו, והדף היה מוצג במצב quirks.
אחרי ``</html>`` הדפדפן מכניס את התגית לתוך ה-body, ולכן צירוף לסוף אינו צריך לפרסר את ה-HTML של המשתמש.
המחיר: קובץ שנגמר בתוך ``<script>``, ``<textarea>`` או הערה שלא נסגרו בולע את התגית כטקסט, והמדווח לא רץ — הפתקים
פשוט לא עוקבים אחרי הגלילה, ושום דבר לא נשבר.
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Callable, Dict, Optional

#: הסיומות שנותנות לקובץ תצוגת דפדפן — ראו :func:`is_html_file`.
HTML_FILE_EXTENSIONS = ('.html', '.htm')


def is_html_file(language: Any, file_name: Any) -> bool:
    """האם לקובץ יש תצוגת דפדפן (``/html/<id>``): השפה ``html``, או סיומת מ-:data:`HTML_FILE_EXTENSIONS`.

    הכלל האחד לשלושה צרכנים: הראוט ``html_preview`` ב-``webapp/app.py``, כפתור 🌐 בעמוד הקובץ ובעמוד הקבצים
    (``is_html_file`` בתבניות, דרך :data:`TEMPLATE_GLOBALS`), והקישור הקבוע של פתק (``_note_file_target`` ב-
    ``webapp/app.py``), שמפנה פתק על קובץ HTML לתצוגה הזו ולא ל-``/md/``. עד נובמבר 2026 הכלל היה כתוב בראוט ובשתי
    התבניות, כל אחד בעותק משלו. **בלי ``strip``**, כמו העותקים שהוא מחליף וכמו ``is_markdown_file``.
    """
    lang = language.lower() if isinstance(language, str) else ''
    name = file_name.lower() if isinstance(file_name, str) else ''
    return lang == 'html' or name.endswith(HTML_FILE_EXTENSIONS)


#: מה שהמודול נותן לתבניות. ``webapp/app.py`` רושם אותם על האפליקציה, וטסט שמרנדר תבנית בסביבת Jinja משלו מוסיף אותם
#: משם — כמו ``TEMPLATE_FILTERS`` ב-``webapp/file_name_display.py``. המודול הוא עלה: הוא אינו מייבא דבר מהוובאפ.
TEMPLATE_GLOBALS: Dict[str, Callable[..., Any]] = {"is_html_file": is_html_file}

#: הפרמטר ש-``/html/<id>`` שולח ב-``src`` של המסגרת, ושבזכותו ``/raw_html`` מצרף את המדווח. "חלון חדש" לא שולח
#: אותו, ולכן מקבל את הקובץ כמו שהוא.
REPORT_SCROLL_PARAM = "report_scroll"

#: ה-``type`` של ההודעה שהמדווח שולח לדף. הדף מקבל אותו מהתבנית (``html_preview.html``), ולכן הוא כתוב רק כאן.
SCROLL_MESSAGE_TYPE = "codebot:html-frame-scroll"

#: ה-``type`` של ההודעה שהדף שולח למסגרת כדי לקבל דיווח מיד — אחרי טעינה מחדש של המסגרת.
SCROLL_REQUEST_TYPE = "codebot:html-frame-scroll-request"

#: הבתים האקראיים ב-``nonce``. ``secrets.token_urlsafe`` מקודד אותם ב-base64url בלי ``=``, ולכן ה-``nonce`` בנוי
#: מ-``A-Za-z0-9_-`` בלבד — תווים ש-``base64-value`` של CSP מקבל.
_NONCE_BYTES = 16

_CSP_COMMON = (
    "default-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "connect-src 'none'; "
    "img-src data:; "
    "style-src 'unsafe-inline'; "
    "font-src data:; "
    "object-src 'none'; "
    "frame-ancestors 'self'; "
)

# המדווח. כל מה שהוא שולח הוא מספרים ומחרוזת כיוון: הדף מאמת כל שדה לפני שהוא משתמש בו
# (``html-preview-notes.js``), כי במצב JS גם הסקריפטים של הקובץ יכולים לשלוח הודעה מאותה מסגרת.
#
# ``'*'`` כיעד ההודעה: הדף שמסביב הוא של האתר — ``frame-ancestors 'self'`` אינו נותן לאתר אחר להטמיע את
# המסגרת — ומה שנשלח אינו סוד. ההודעה שמגיעה מהדף מתקבלת רק כשהשולח הוא ``parent``.
#
# ``requestAnimationFrame``: דיווח אחד לכל פריים בגלילה רציפה, ולא אחד לכל אירוע.
_REPORTER_JS = (
    "(function(){"
    "var TYPE=" + json.dumps(SCROLL_MESSAGE_TYPE) + ";"
    "var REQUEST=" + json.dumps(SCROLL_REQUEST_TYPE) + ";"
    "var queued=false;"
    "function send(){"
    "queued=false;"
    "var se=document.scrollingElement||document.documentElement;"
    "if(!se)return;"
    "parent.postMessage({type:TYPE,x:window.scrollX,y:window.scrollY,"
    "scrollWidth:se.scrollWidth,clientWidth:se.clientWidth,"
    "direction:getComputedStyle(se).direction==='rtl'?'rtl':'ltr'},'*');"
    "}"
    "function schedule(){if(queued)return;queued=true;requestAnimationFrame(send);}"
    "addEventListener('scroll',schedule,{passive:true});"
    "addEventListener('resize',schedule);"
    "addEventListener('load',send);"
    "addEventListener('message',function(ev){"
    "if(ev.source===parent&&ev.data&&ev.data.type===REQUEST)send();"
    "});"
    "send();"
    "})();"
)


def new_reporter_nonce() -> str:
    """``nonce`` חד-פעמי לתשובה אחת של ``/raw_html``."""
    return secrets.token_urlsafe(_NONCE_BYTES)


def raw_html_csp(*, scripts_enabled: bool, reporter_nonce: Optional[str]) -> str:
    """ה-CSP של תשובה אחת של ``/raw_html`` — שלושת המצבים שבראש המודול.

    ``reporter_nonce`` נחשב רק כשהסקריפטים של המשתמש כבויים: במצב JS המדווח רץ בזכות ``'unsafe-inline'``.
    """
    if scripts_enabled:
        return "sandbox allow-scripts; " + _CSP_COMMON + "script-src 'unsafe-inline'"
    if reporter_nonce:
        return "sandbox allow-scripts; " + _CSP_COMMON + f"script-src 'nonce-{reporter_nonce}'"
    return "sandbox; " + _CSP_COMMON + "script-src 'none'"


def with_scroll_reporter(html: str, *, nonce: Optional[str]) -> str:
    """ה-HTML של המשתמש, ובסופו המדווח — עם ``nonce`` כשנמסר, ובלעדיו במצב JS."""
    nonce_attr = f' nonce="{nonce}"' if nonce else ""
    return f"{html}\n<script{nonce_attr}>{_REPORTER_JS}</script>\n"

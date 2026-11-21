"""המסגרת של תצוגת ה-HTML (``/html/<id>``): ה-CSP של ``/raw_html/<id>``, ומדווח הגלילה שהפתקים נשענים עליו.

**למה יש כאן סקריפט בכלל.** ``/raw_html`` מגיש את ה-HTML של המשתמש בתוך iframe מבודד: ``sandbox`` בלי
``allow-same-origin``, כלומר מקור אטום, והדף שמסביב אינו יכול לקרוא שום דבר מתוך המסגרת — לא את התוכן ולא כמה
גללו בה. פתק "על הקובץ" (``surface``) חייב לנוע עם התוכן, ולכן מישהו בתוך המסגרת צריך לספר לדף כמה גללו. זה
המדווח: סקריפט קטן שמצורף לסוף ה-HTML ושולח לדף, ב-``postMessage``, את מיקום הגלילה, את רוחב התוכן ואת הכיוון —
ומקבל ממנו דבר אחד: הוראה לגלול למקום מסוים (:data:`SCROLL_COMMAND_TYPE`), בשביל קישור לפתק שמחוץ לחלון. הצרכן
בצד הדפדפן הוא ``webapp/static/js/html-preview-notes.js``.

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
פשוט לא עוקבים אחרי הגלילה, ושום דבר לא נשבר. וקובץ שמגדיר בעצמו CSP (``<meta
http-equiv="Content-Security-Policy">``) — מדיניות כזו נאכפת בנוסף לזו של התשובה, וה-``nonce`` אינו מתיר את המדווח
מולה — מוגש בלי "אפשר JS" בלי מדווח, במצב הראשון (:func:`declares_own_csp`): גם שם הפתקים לא עוקבים אחרי הגלילה.

**שני דברים שנגררים מכך שהמסגרת מתירה סקריפטים, גם כשהסקריפטים של הקובץ חסומים** — שניהם נמדדו בכרומיום
(נובמבר 2026) מול הקוד שלפני המדווח:

* **``<noscript>``.** הדפדפן מחליט אם להציג אותו לפי ה-``sandbox`` ולא לפי ה-CSP, ולכן עם ``allow-scripts`` התוכן
  שלו מוסתר — גם כשאף סקריפט של הקובץ לא ירוץ. בלי "אפשר JS" המדווח מציג אותו בעצמו (:data:`_NOSCRIPT_JS`), כמו
  שהוצג לפני שהיה מדווח. במצב JS הוא נשאר מוסתר, כמו תמיד.
* **מסמך שהמסגרת עוברת אליו** — קישור בקובץ, או ``<meta http-equiv="refresh">`` (שבלי ``allow-scripts`` לא עבד
  בכלל) — מקבל את ``allow-scripts`` של המסגרת בלי ה-CSP שלנו, ולכן הסקריפטים שלו רצים, בתוך אותו מקור אטום. נעילה
  של ה-``sandbox`` אחרי שהמסמך שלנו נטען חסמה את הקישור ולא את ה-``refresh``, שמתחיל לפני שהנעילה מגיעה. לכן
  ההגנה היא בצד של הדף: אף מאזין ``message`` בתצוגה אינו מבצע פעולה בשם המשתמש על סמך הודעה מהמסגרת. מאזין כזה
  היה — סימנייה על עוגן (``html-anchor-click``) — והוסר; המאזין של הפתקים רק מזיז פתקים, ובודק כל שדה.
"""

from __future__ import annotations

import json
import logging
import secrets
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

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

#: ה-``type`` של הוראת הגלילה שהדף שולח למסגרת: ``{type, x, y}``, מספרים סופיים. בשביל קישור לפתק (``?note=``)
#: שיושב מחוץ לחלון המסגרת — המנהל גולל את התוכן אליו (``scrollToNote`` ב-``sticky-notes.js``). המדווח גולל ומדווח
#: מיד, כך שהדף רואה את המיקום החדש גם כשהגלילה לא זזה (כבר שם, או בקצה).
SCROLL_COMMAND_TYPE = "codebot:html-frame-scroll-to"

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
# המסגרת — ומה שנשלח אינו סוד. ההודעות שמגיעות מהדף — בקשת דיווח, והוראת גלילה (:data:`SCROLL_COMMAND_TYPE`) —
# מתקבלות רק כשהשולח הוא ``parent``, והוראת גלילה רק עם שני מספרים סופיים (``Number.isFinite`` אינו ממיר מחרוזת).
# גלילה היא כל מה שהיא עושה: היא אינה קוראת דבר מהמסמך מעבר למה שהדיווח ממילא שולח.
#
# ``requestAnimationFrame``: דיווח אחד לכל פריים בגלילה רציפה, ולא אחד לכל אירוע.
_REPORTER_JS = (
    "(function(){"
    "var TYPE=" + json.dumps(SCROLL_MESSAGE_TYPE) + ";"
    "var REQUEST=" + json.dumps(SCROLL_REQUEST_TYPE) + ";"
    "var COMMAND=" + json.dumps(SCROLL_COMMAND_TYPE) + ";"
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
    "var d=ev.data;"
    "if(ev.source!==parent||!d)return;"
    "if(d.type===REQUEST){send();return;}"
    "if(d.type===COMMAND&&Number.isFinite(d.x)&&Number.isFinite(d.y)){window.scrollTo(d.x,d.y);send();}"
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


#: **התוכן של ``<noscript>``, כמו בקובץ בלי סקריפטים** — רק כשהסקריפטים של הקובץ חסומים. כשהמסמך מתיר סקריפטים,
#: הדפדפן קורא את התוכן של ``<noscript>`` כטקסט ולא כאלמנטים, ומסתיר אותו. כאן הטקסט נקרא מחדש כ-HTML, ב-``template``,
#: והאלמנטים נכנסים במקום ה-``<noscript>`` עצמו — כי ``noscript`` מוסתר ב-``!important`` בגיליון של הדפדפן כשסקריפטים
#: מותרים. מה שנבנה כך לא מריץ דבר: ``<script>`` שנכנס דרך ``innerHTML`` אינו רץ, ו-``onerror`` ודומיו נחסמים ב-CSP.
#: ההבדל היחיד שנשאר: סלקטור ``noscript p`` בעיצוב של הקובץ לא יתפוס, כי ה-``noscript`` כבר אינו שם. רץ לפני הדיווח
#: הראשון, כדי שרוחב התוכן שנשלח יכלול את מה שנחשף.
_NOSCRIPT_JS = (
    "document.querySelectorAll('noscript').forEach(function(n){"
    "var t=document.createElement('template');"
    "t.innerHTML=n.textContent;"
    "n.replaceWith(t.content);"
    "});"
)


def with_scroll_reporter(html: str, *, nonce: Optional[str], file_scripts_enabled: bool) -> str:
    """ה-HTML של המשתמש, ובסופו המדווח — עם ``nonce`` כשנמסר, ובלעדיו במצב JS.

    ``file_scripts_enabled`` — "אפשר JS". בלעדיו המדווח גם מציג את התוכן של ``<noscript>`` (:data:`_NOSCRIPT_JS`).
    """
    nonce_attr = f' nonce="{nonce}"' if nonce else ""
    noscript = "" if file_scripts_enabled else _NOSCRIPT_JS
    return f"{html}\n<script{nonce_attr}>{noscript}{_REPORTER_JS}</script>\n"


#: התגיות שהדפדפן משאיר בראש המסמך (``<head>``). התגית הראשונה שאינה ביניהן פותחת את ה-body, ומשם ``<meta>`` של
#: CSP כבר אינו נאכף — ולכן :func:`declares_own_csp` עוצרת בה.
_HEAD_TAGS = frozenset(("html", "head", "meta", "link", "title", "style", "script", "base", "noscript", "template"))

#: גודל הנתח שנמסר למפרסר בכל פעם — כדי לעצור בתחילת ה-body, ולא לפרסר קובץ שלם בשביל הראש שלו.
_SCAN_CHUNK = 4096


class _OwnCspScanner(HTMLParser):
    """מחפש ``<meta http-equiv="Content-Security-Policy">`` בראש המסמך, ועוצר בתגית הראשונה של ה-body."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = False
        self.done = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if self.done:
            return
        if tag not in _HEAD_TAGS:
            self.done = True
            return
        if tag != "meta":
            return
        for name, value in attrs:
            # ``http-equiv`` בלי ערך מגיע כ-``None``. ``strip`` מחמיר מהדפדפן — רווח סביב הערך מספיק כאן כדי לוותר על
            # המדווח, וזה הכיוון הבטוח (ראו :func:`declares_own_csp`).
            if name == "http-equiv" and isinstance(value, str) and value.strip().lower() == "content-security-policy":
                self.found = True
                self.done = True
                return


def declares_own_csp(html: str) -> bool:
    """האם הקובץ מגדיר CSP משלו, ב-``<meta http-equiv="Content-Security-Policy">`` בראש המסמך.

    **למה זה חשוב.** מדיניות כזו נאכפת בנוסף לזו של התשובה, וה-``nonce`` של המדווח אינו מתיר אותו מולה — ואז במצב
    בלי "אפשר JS" המסגרת מתירה סקריפטים (``allow-scripts``, בשביל המדווח) ואף סקריפט לא רץ: הפתקים לא עוקבים אחרי
    הגלילה, ו-``<noscript>`` מוסתר בלי שאיש יציג אותו. ``/raw_html`` מגיש קובץ כזה בלי מדווח, במצב הראשון שבראש
    המודול — ``sandbox`` בלי ``allow-scripts`` מבטל את ה-``allow-scripts`` של המסגרת, והדפדפן מציג את
    ``<noscript>`` בעצמו. נמדד בכרומיום (נובמבר 2026).

    **רק בראש המסמך**, ולכן העצירה בתגית הראשונה של ה-body. נמדד באותה מדידה: ``<meta>`` כזה בראש — או ראשון בקובץ
    בלי ``<head>`` כתוב — חסם את המדווח; אחרי ``<p>`` הוא לא נאכף, והמדווח רץ. תגית שהמפרסר כאן מפרש כראש וכזו שאינה
    (``<meta>`` בתוך ``<noscript>`` שבראש, טקסט לפני התגית) — הטעות היא לכיוון "יש CSP": הקובץ מוצג כמו ב"חלון חדש",
    והפתקים לא עוקבים אחרי הגלילה בו. הכיוון ההפוך היה מחזיר את ``<noscript>`` המוסתר.

    **מפרסר שנכשל = "יש CSP", ונרשם.** ``_markupbase`` של Python 3.11 (הגרסה בפרודקשן, ``Dockerfile``) עדיין מכיל
    ``raise AssertionError`` על הצהרות פגומות. במדידה על 3.11.18 אף קלט לא הגיע אליהם (2.6 מיליון קלטים אקראיים), אבל
    תגית התמונה אינה נעוצה בגרסת תיקון. בלי ההגנה קובץ כזה היה מפיל את ``/raw_html`` ב-500; איתה הוא מוצג כמו
    ב"חלון חדש" — בלי סקריפטים בכלל — והלוג סופר כמה פעמים זה קרה. רק ``AssertionError``: זה מה שהמפרסר זורק על
    קלט פגום, וכל חריגה אחרת היא באג ועולה.
    """
    scanner = _OwnCspScanner()
    try:
        for start in range(0, len(html), _SCAN_CHUNK):
            scanner.feed(html[start:start + _SCAN_CHUNK])
            if scanner.done:
                break
    except AssertionError:
        # בלי ``exc_info`` ובלי הודעת החריגה: ``_markupbase`` מצטט בה קטע מהקובץ, כלומר מתוכן של המשתמש.
        logger.warning("html preview: the HTML parser rejected the file; serving it without the scroll reporter")
        return True
    return scanner.found

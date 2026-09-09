"""סורק האאוטליין של HTML ותבניות Jinja.

**סורק לקסיקלי עם מחסנית, לא פרסר עץ.** תבנית Jinja אינה HTML תקין: תגית
שנפתחת בענף אחד של ``{% if %}`` ונסגרת בענף אחר היא הכתיב הרגיל כאן, לא
שגיאה. פרסר DOM "מתקן" את זה בשקט — הוא מזיז תגיות, סוגר מה שלא נסגר,
ומחזיר מספרי שורות שאינם במקום שבו הטקסט באמת יושב. סורק טוקנים שטוח לא
מנסה לאזן, ולכן גם לא משקר.

השמות שטוחים ולא מנוקדים: ב-HTML אין מרחבי שמות, ו-``div`` בעומק שתים-עשרה
אינו שם משמעותי. התחילית נוספת רק כשיש עוגן אמיתי — ``id`` על בלוק
``<script>`` הופך את הפונקציות שבתוכו ל-``script#x.initColors``. **המשמעות
היא שהוספת ``id`` לבלוק קיים משנה את שמן של כל הפונקציות בתוכו**, בדיוק
כמו שעטיפת פונקציות במחלקה משנה שמות מתודות בפייתון. זו התנהגות ולא באג,
והיא כתובה כאן כדי שלא תיראה כמו באג בעוד חצי שנה.
"""

from __future__ import annotations

import re
from typing import Any

#: אלמנטים שאין להם תגית סגירה, ולכן אסור לדחוף אותם למחסנית — אחרת הם
#: לא ייסגרו לעולם ויסיטו את שורת ה-``end`` של כל מה שמעליהם.
#:
#: **המפרט וה-דפדפן אינם מסכימים, והאיחוד הוא הבחירה.** רשימת ה-void
#: elements ב-WHATWG (``html.spec.whatwg.org/multipage/syntax.html``) מונה
#: שלושה-עשר ואינה כוללת ``param``, שהוצא ממנה כמיושן. Chromium **כן**
#: מתייחס אליו כ-void — נמדד: ``document.createElement("param").outerHTML``
#: אינו כולל תגית סגירה. הצרכן כאן הוא קובץ שמישהו כתב, ומי שכתב
#: ``<param>`` בתבנית ישנה התכוון ל-void; לכן ארבעה-עשר.
_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

#: ה-MIME types שגורמים ל-``<script>`` לרוץ כ-JavaScript.
#:
#: מקור: ``mimesniff.spec.whatwg.org`` — "JavaScript MIME type essence
#: match". שש-עשרה הרשומות אומתו אחת-אחת מול Chromium (טעינת ``<script
#: type="...">`` ובדיקה אם הגוף באמת רץ), וההתאמה הייתה מלאה.
#:
#: **"essence" פירושו בלי פרמטרים.** ``text/javascript; charset=utf-8``
#: **אינו** רץ — נמדד. השוואה מקלה יותר, כמו "מכיל javascript", הייתה
#: מסווגת אותו כקוד ומריצה עליו סורק JS על תוכן שאינו JavaScript.
_JAVASCRIPT_MIME_ESSENCES = frozenset({
    "application/ecmascript", "application/javascript",
    "application/x-ecmascript", "application/x-javascript",
    "text/ecmascript", "text/javascript", "text/javascript1.0",
    "text/javascript1.1", "text/javascript1.2", "text/javascript1.3",
    "text/javascript1.4", "text/javascript1.5", "text/jscript",
    "text/livescript", "text/x-ecmascript", "text/x-javascript",
})

#: תוכנם של אלה אינו HTML אלא טקסט גולמי, והם נסגרים **רק** בתגית הסגירה
#: שלהם עצמם.
_RAWTEXT_ELEMENTS = frozenset({"script", "style"})

#: תגיות Jinja שהן מרחב עם התחלה וסוף, ולכן מקבלות טווח.
_JINJA_BLOCK_TAGS = frozenset({"block", "macro"})

#: תגיות Jinja שהן נקודת השקה לקובץ אחר. אין להן סוף, ולכן ``start == end``.
_JINJA_REFERENCE_TAGS = frozenset({"extends", "include", "import", "from"})

#: כל תגית Jinja שיש לה ``end``, כדי שמחסנית ה-Jinja תדע לקנן נכון.
#: ``{% if %}`` אינו סימבול, אבל ``{% endif %}`` **אסור לו** לסגור
#: ``{% block %}`` שנפתח לפניו.
_JINJA_CLOSING_TAGS = frozenset({
    "block", "macro", "if", "for", "call", "filter", "set", "with",
    "trans", "autoescape", "raw", "apply",
})

_TAG_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]*")
_JINJA_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_QUOTED = re.compile(r"""["']([^"']*)["']""")

#: הגדרת פונקציה ב-JavaScript, בצורות שמופיעות בפועל. ``base.html`` מכיל
#: 135 מהצורה הראשונה ו-24 מצורת החץ.
_JS_FUNCTION = re.compile(
    r"(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\("
)
#: רשימת הפרמטרים מכבדת רמת קינון אחת של סוגריים, ולא ``[^)]*``. הצורה
#: הרחבה התאימה ל-``const md = (a ? b : (()=>({x})))({`` — הצבה של תוצאת
#: קריאה, לא הגדרה — כי היא עצרה ב-``)`` הראשון ומצאה ``=>`` אחריו.
#: הקינון גם מרוויח: ``const k = (a, b = (1)) => a`` נתפס עכשיו, ולא היה.
_JS_ASSIGNED = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s+)?(?:function\b|\((?:[^()]|\([^()]*\))*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
)

#: תו שאחריו ``/`` הוא חילוק ולא תחילת regex. הכלל המקובל: אחרי מזהה,
#: מספר, ``)`` או ``]`` מגיע אופרטור; בכל מקום אחר ``/`` פותח literal.
#: ב-``base.html`` יש תשעה regex literals, וחמישה מהם מכילים ``"`` — בלי
#: המצב הזה המרכאה הייתה פותחת מחרוזת ובולעת את הקוד שאחריה.
_BEFORE_DIVISION = re.compile(r"[\w$)\]]")


def extract(text: str) -> dict[str, Any]:
    """מפת הסימבולים של תבנית HTML/Jinja."""
    rows: list[dict[str, Any]] = []
    tags: list[tuple[str, int, str | None]] = []
    jinja: list[tuple[str, int, str]] = []
    line = 1
    index = 0
    size = len(text)

    while index < size:
        char = text[index]

        if char == "\n":
            line += 1
            index += 1
            continue

        # ההערות נבדקות **לפני** כל דבר אחר, כדי שקוד מת בתוכן לא ייכנס
        # למפה. ``base.html`` מכיל 25 הערות HTML ותשע הערות Jinja, וחלקן
        # רב-שורתיות.
        if text.startswith("{#", index):
            index, line = _skip_past(text, index + 2, "#}", line)
            continue
        if text.startswith("<!--", index):
            index, line = _skip_past(text, index + 4, "-->", line)
            continue

        # תגית Jinja נבדקת לפני ``<``, כי היא יכולה לעטוף תגית HTML.
        if text.startswith("{%", index):
            stop, next_line = _skip_past(text, index + 2, "%}", line)
            _read_jinja(text[index + 2 : stop - 2], line, rows, jinja)
            index, line = stop, next_line
            continue
        if text.startswith("{{", index):
            index, line = _skip_past(text, index + 2, "}}", line)
            continue

        if char == "<":
            index, line = _read_tag(text, index, line, rows, tags)
            continue

        index += 1

    # תגיות שנשארו פתוחות בסוף הקובץ. זה הכתיב הרגיל בתבנית שנפתחת בענף
    # אחד ונסגרת באחר, ולכן הן מדווחות עד סוף הקובץ ולא נזרקות.
    for name, opened, anchor in tags:
        if anchor:
            rows.append({"name": f"{name}#{anchor}", "start": opened, "end": line})
    for kind, opened, name in jinja:
        if kind in _JINJA_BLOCK_TAGS:
            rows.append({"name": f"{kind} {name}", "start": opened, "end": line})

    return {"symbols": rows}


def _skip_past(text: str, start: int, needle: str, line: int) -> tuple[int, int]:
    """מדלג עד אחרי ``needle``, או עד סוף הטקסט אם הוא לא נסגר.

    קטע שלא נסגר אינו שגיאה שמפילה את הסריקה: הקלט הוא קובץ שמישהו כתב,
    ובקובץ באמצע עריכה זה קורה. הוא נבלע עד הסוף, וזה גם מה שדפדפן עושה.
    """
    stop = text.find(needle, start)
    if stop < 0:
        return len(text), line + text.count("\n", start)
    end = stop + len(needle)
    return end, line + text.count("\n", start, end)


def _read_jinja(
    body: str,
    line: int,
    rows: list[dict[str, Any]],
    stack: list[tuple[str, int, str]],
) -> None:
    """מטפל בתגית Jinja אחת. ``body`` הוא מה שבין ``{%`` ל-``%}``."""
    # ``{%-`` ו-``-%}`` הם whitespace control ומופיעים ב-``admin_mcp.html``.
    # החיתוך והחיפוש נעשים על **אותה** מחרוזת: גרסה קודמת חיפשה במנוקה
    # וחתכה מהמקורית, וההיסט של ה-``strip`` הזיז את הגבול — ``block
    # content`` חזר כ-``block k``.
    cleaned = body.strip().strip("-").strip()
    word = _JINJA_WORD.search(cleaned)
    if not word:
        return
    keyword = word.group(0)
    rest = cleaned[word.end() :].strip()

    if keyword.startswith("end"):
        closes = keyword[3:]
        # שליפה עד ההתאמה, ולא שליפה עיוורת: ``{% endif %}`` בתוך
        # ``{% block %}`` אסור לו לסגור את ה-block.
        for depth in range(len(stack) - 1, -1, -1):
            if stack[depth][0] == closes:
                kind, opened, name = stack.pop(depth)
                del stack[depth:]
                if kind in _JINJA_BLOCK_TAGS:
                    rows.append({"name": f"{kind} {name}", "start": opened, "end": line})
                return
        return

    if keyword in _JINJA_REFERENCE_TAGS:
        quoted = _QUOTED.search(rest)
        target = quoted.group(1) if quoted else rest.split()[0] if rest.split() else ""
        rows.append({"name": f"{keyword} {target}", "start": line, "end": line})
        return

    if keyword in _JINJA_CLOSING_TAGS:
        # שם מקומי אחר מ-``name`` שבענף ה-``end`` שמעל: שם אחד לשני
        # טיפוסים הוא בדיוק מה ש-mypy תפס כאן, ו-``attr-defined`` הוא
        # אחד משני הקודים שה-CI חוסם עליהם.
        argument = _JINJA_WORD.search(rest)
        stack.append((keyword, line, argument.group(0) if argument else ""))


def _read_tag(
    text: str,
    index: int,
    line: int,
    rows: list[dict[str, Any]],
    stack: list[tuple[str, int, str | None]],
) -> tuple[int, int]:
    """קורא תגית אחת מ-``<``. מחזיר את המיקום והשורה שאחריה."""
    if text.startswith("</", index):
        name = _TAG_NAME.match(text, index + 2)
        if not name:
            return index + 1, line
        stop, next_line = _skip_past(text, index, ">", line)
        _close_tag(name.group(0).lower(), line, rows, stack)
        return stop, next_line

    name = _TAG_NAME.match(text, index + 1)
    if not name:
        return index + 1, line

    tag = name.group(0).lower()
    attributes, stop, next_line = _read_attributes(text, name.end(), line)
    self_closing = attributes.rstrip().endswith("/")
    anchor = _attribute(attributes, "id")

    if tag in _RAWTEXT_ELEMENTS:
        label = f"{tag}#{anchor}" if anchor else tag
        body_rows, end_index, end_line = _read_rawtext(
            text, stop, next_line, tag,
            prefix=f"{label}." if anchor else "",
            javascript=tag == "script" and _is_javascript(attributes),
        )
        rows.append({"name": label, "start": line, "end": end_line})
        rows.extend(body_rows)
        return end_index, end_line

    if tag not in _VOID_ELEMENTS and not self_closing:
        stack.append((tag, line, anchor))
    elif anchor:
        rows.append({"name": f"{tag}#{anchor}", "start": line, "end": next_line})

    return stop, next_line


def _close_tag(
    tag: str,
    line: int,
    rows: list[dict[str, Any]],
    stack: list[tuple[str, int, str | None]],
) -> None:
    """סוגר תגית, ומדווח את מי שנשלף אם היה לו ``id``.

    **המחסנית מקבלת כל תגית פותחת, גם בלי ``id``, והדיווח הוא שמסונן.**
    מימוש שדוחף רק אלמנטים בעלי ``id`` אך שולף על כל תגית סוגרת נראה זהה
    ברוב המקרים ונשבר על ``<div id="a"><div></div></div>``: התגית הסוגרת
    הפנימית הייתה שולפת את ``#a`` ונותנת לו את שורת הסיום הפנימית. מעקב
    העומק חייב להיות שלם גם כשהדיווח חלקי.

    **תגית סוגרת שאין לה התאמה נזרקת ולא שולפת כלום.** בתבנית Jinja זה
    הכתיב הרגיל — ``<div>`` נפתח בענף אחד של ``{% if %}`` ונסגר באחר —
    ושליפה עיוורת הייתה מרוקנת את המחסנית ומסיטה את כל השורות שמתחת.
    """
    for depth in range(len(stack) - 1, -1, -1):
        if stack[depth][0] == tag:
            name, opened, anchor = stack.pop(depth)
            # מה שהיה פתוח **בתוך** התגית שנסגרה כבר לא ייסגר בנפרד;
            # הוא מדווח כאן עד אותה שורה, ולא נזרק בשקט.
            for inner, inner_line, inner_anchor in stack[depth:]:
                if inner_anchor:
                    rows.append(
                        {"name": f"{inner}#{inner_anchor}", "start": inner_line, "end": line}
                    )
            del stack[depth:]
            if anchor:
                rows.append({"name": f"{name}#{anchor}", "start": opened, "end": line})
            return


def _read_attributes(text: str, start: int, line: int) -> tuple[str, int, int]:
    """קורא עד ``>``, תוך כיבוד מחרוזות.

    ``<div title="a > b">`` הוא תגית אחת. חיפוש ``>`` בלי לכבד מחרוזות היה
    חותך אותה באמצע, וכל מה שאחריה היה נקרא כטקסט.
    """
    index = start
    size = len(text)
    quote = ""
    while index < size:
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == ">":
            return text[start:index], index + 1, line + text.count("\n", start, index + 1)
        index += 1
    return text[start:], size, line + text.count("\n", start)


def _attribute(attributes: str, name: str) -> str | None:
    """הערך של תכונה, או ``None``. מחזיר גם ערך ריק כ-``None``."""
    found = re.search(
        rf"""(?:^|\s){re.escape(name)}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""",
        attributes,
        re.IGNORECASE,
    )
    if not found:
        return None
    value = next((group for group in found.groups() if group is not None), "")
    return value.strip() or None


def _is_javascript(attributes: str) -> bool:
    """האם הבלוק הזה הוא JavaScript שראוי לרדת לתוכו.

    היעדר ``type``, ``type`` ריק, ``module``, או MIME type של JavaScript.
    כל השאר הוא data block שהדפדפן אינו מריץ — ב-``base.html`` יש ארבעה
    ``application/json``, ו-``JSON`` שנסרק כ-JS היה מייצר סימבולים
    ממחרוזות שבמקרה נראות כמו הגדרות.
    """
    declared = _attribute(attributes, "type")
    if declared is None:
        return True
    normalized = declared.strip().casefold()
    return normalized in {"", "module"} or normalized in _JAVASCRIPT_MIME_ESSENCES


def _read_rawtext(
    text: str, start: int, line: int, tag: str, prefix: str, javascript: bool
) -> tuple[list[dict[str, Any]], int, int]:
    """קורא גוף של ``<script>`` או ``<style>`` עד תגית הסגירה שלו.

    **היציאה היא על ``</tag`` בלבד, בלי לכבד מחרוזות של JavaScript** — וזה
    נמדד ולא הונח: ``<script>var s = "</script>";</script>`` נטען ב-Chromium,
    ותוכן האלמנט חזר כ-``'var s = "'``. כל השאר הפך לטקסט HTML. המפרט אומר
    את אותו דבר במפורש — "always escape ... ``</script`` as ``\\x3C/script``
    when these sequences appear in literals in scripts (e.g. in strings,
    regular expressions, or comments)". המימוש האינטואיטיבי הוא ההפוך, והוא
    לא היה זורק שגיאה — רק מותח את הבלוק עד הסוגר הבא.
    """
    # **חיפוש על הטקסט המקורי, לא על עותק ממוזער.** ``text.lower()``
    # יכול לשנות **אורך** — ``İ`` (U+0130) הופך לשני תווים — והאינדקס
    # שחוזר משמש לחיתוך ולספירת שורות ב-``text``, כך שהוא מוסט. וזו גם
    # הקצאה של עותק מלא של הטקסט לכל תגית ``script``/``style``, עד 10MB
    # לפי ``RANGE_READ_MAX_BYTES`` — בדיוק העלות שההערה על
    # ``_CR_WITHOUT_LF`` ב-``outline.py`` נמנעת ממנה במפורש.
    found = re.compile(rf"</{re.escape(tag)}", re.IGNORECASE).search(text, start)
    stop = found.start() if found else len(text)
    end_line = line + text.count("\n", start, stop)
    after, after_line = _skip_past(text, stop, ">", end_line)

    rows = _read_javascript(text[start:stop], line, prefix) if javascript else []
    return rows, after, after_line


def _read_javascript(source: str, line: int, prefix: str) -> list[dict[str, Any]]:
    """הגדרות הפונקציות בתוך בלוק סקריפט.

    זה מה שהופך בלוק בן שבע-מאות שורות למפה שאפשר לנווט בה. בלוק שמוחזר
    כסימבול אחד אינו מפה — הוא רק גבול.

    המצבים הם מחרוזת, template literal, שתי צורות הערה, ו-**regex
    literal**. האחרון אינו קישוט: ב-``base.html`` יש ``.replace(/"/g, ...)``
    בשלושה מקומות, והמרכאה שבתוך ה-regex הייתה פותחת מחרוזת ובולעת את הקוד
    עד המרכאה הבאה.
    """
    rows: list[dict[str, Any]] = []
    pending: list[tuple[str, int, int]] = []
    depth = 0
    index = 0
    size = len(source)
    current = line
    #: הטוקן הלא-רווח האחרון — משמש **רק** להבחנה בין regex לחילוק.
    token = ""
    #: כמה סוגריים עגולים של חתימה עוד פתוחים. חיובי = אנחנו בתוך
    #: רשימת הפרמטרים, ושם ``{`` אינו פותח גוף.
    signature = 0

    while index < size:
        char = source[index]

        if char == "\n":
            current += 1
            index += 1
            # ``const f = x => x + 1`` בלי גוף מסולסל נגמר בסוף השורה.
            # הסגירה כאן היא רק למי שכבר יצא מהחתימה: פונקציה שהחתימה
            # שלה נפרסת על כמה שורות עדיין ממתינה לגוף, ואסור לסגור אותה
            # בסוף השורה הראשונה.
            if not signature:
                while pending and pending[-1][2] < 0:
                    name, opened, _ = pending.pop()
                    rows.append({"name": f"{prefix}{name}", "start": opened, "end": current - 1})
            continue

        if source.startswith("//", index):
            stop = source.find("\n", index)
            index = size if stop < 0 else stop
            continue
        if source.startswith("/*", index):
            index, current = _skip_past(source, index + 2, "*/", current)
            continue
        if char in "\"'`":
            index, current = _skip_string(source, index, current)
            token = "x"
            continue
        if char == "/" and not _BEFORE_DIVISION.match(token):
            index, current = _skip_regex(source, index, current)
            token = "x"
            continue

        # **בתוך רשימת הפרמטרים אין גוף.** ``function f(a, opts = {})``
        # מכיל ``{`` שאינו פותח את הפונקציה, ורישום העומק ברגע ההתאמה
        # גרם ל-``}`` שסוגר את ברירת המחדל לסגור את הפונקציה כולה —
        # ``end == start`` בשורת החתימה. נמדד: 136 מתוך 841 ההגדרות בכל
        # התבניות, ו-61 מתוך 97 ב-``admin_observability.html``.
        #
        # לכן ``signature`` סופר את הסוגריים העגולים שנותרו פתוחים מאז
        # ההתאמה. כל עוד הוא חיובי אנחנו בחתימה: ``{``/``}`` נספרים
        # לעומק כרגיל, אבל אינם סוגרים כלום, וה-``{`` הראשון **אחרי**
        # שהם התאזנו הוא זה שרושם את עומק הגוף.
        if signature:
            if char == "(":
                signature += 1
            elif char == ")":
                signature -= 1
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            if not char.isspace():
                token = char
            index += 1
            continue

        if char == "{":
            depth += 1
            # פונקציה שממתינה לגוף (``-1``) מקבלת כאן את עומקה האמיתי.
            # זה חל גם על ``function`` רגילה — אחרי שהחתימה נסגרה — וגם
            # על חץ עם גוף מסולסל.
            if pending and pending[-1][2] < 0:
                name, opened, _ = pending.pop()
                pending.append((name, opened, depth - 1))
        elif char == "}":
            depth -= 1
            while pending and 0 <= pending[-1][2] >= depth:
                name, opened, _ = pending.pop()
                rows.append({"name": f"{prefix}{name}", "start": opened, "end": current})

        if char.isalpha() or char in "_$":
            # ``adjacent`` הוא התו ה**צמוד** ולא הטוקן האחרון. שני
            # השימושים נראים דומים ואינם: ל-regex צריך את הטוקן הקודם
            # (``x /2`` הוא חילוק), ולגבול מזהה צריך את התו הסמוך.
            # משתנה אחד לשניהם חסם הגדרה לגיטימית אחרי ``var s = "abc"``
            # בלי נקודה-פסיק, אחרי ``init()`` ואחרי ``arr[0]``.
            adjacent = source[index - 1] if index else ""
            match = _JS_FUNCTION.match(source, index) or _JS_ASSIGNED.match(source, index)
            if match and not _BEFORE_DIVISION.match(adjacent):
                # ``-1`` = "ממתין לגוף" בשני המקרים. ה-``{`` שיגיע הוא
                # שיקבע את העומק, בין אם החתימה בסוגריים ובין אם לא.
                pending.append((match.group(1), current, -1))
                signature = 1 if match.group(0).rstrip().endswith("(") else 0
                index = match.end()
                token = "x"
                continue

        if not char.isspace():
            token = char
        index += 1

    # פונקציות שלא נסגרו עד סוף הבלוק.
    for name, opened, _ in pending:
        rows.append({"name": f"{prefix}{name}", "start": opened, "end": current})
    return rows


def _skip_string(source: str, index: int, line: int) -> tuple[int, int]:
    """מדלג על מחרוזת, כולל template literal עם ``${...}`` מקונן.

    **המונה חייב לספור את אותם תווים בשני הכיוונים.** גרסה קודמת העלתה
    את ``nesting`` רק על ``${`` אך הורידה אותו על **כל** ``}``, ולכן
    אובייקט או גוף בלוק בתוך ``${...}`` הורידו אותו לאפס בטרם עת. משם
    ה-backtick הבא נקרא כסוגר של המחרוזת החיצונית, והסורק המשיך לקרוא
    טקסט HTML כאילו הוא קוד — ושלוש פונקציות נעלמו מהמפה לגמרי:
    ``renderStoryCell`` ו-``renderAiExplainCell`` ב-
    ``admin_observability.html``, ו-``executedFunction`` ב-
    ``md_preview.html``.

    עכשיו, מרגע ה-``${``, גם ``{`` רגיל מעלה. מחרוזת שנפתחת בתוך
    ``${...}`` מטופלת ברקורסיה, כדי ש-``}`` בתוכה לא ייחשב לסוגר.
    """
    quote = source[index]
    index += 1
    size = len(source)
    nesting = 0
    while index < size:
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "\n":
            line += 1
        elif quote == "`" and source.startswith("${", index):
            nesting += 1
            index += 2
            continue
        elif nesting and char in "\"'`":
            # מחרוזת מקוננת בתוך ההחלפה. בלי זה, ``}`` שיושב בתוכה היה
            # מוריד את המונה ומוציא אותנו מה-template מוקדם.
            index, line = _skip_string(source, index, line)
            continue
        elif nesting and char == "{":
            nesting += 1
        elif nesting and char == "}":
            nesting -= 1
        elif char == quote and not nesting:
            return index + 1, line
        index += 1
    return size, line


def _skip_regex(source: str, index: int, line: int) -> tuple[int, int]:
    """מדלג על regex literal, כולל מחלקת תווים ``[...]`` שיכולה להכיל ``/``."""
    index += 1
    size = len(source)
    in_class = False
    while index < size:
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "\n":  # regex אינו חוצה שורות — כנראה היה חילוק
            return index, line
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            return index + 1, line
        index += 1
    return size, line

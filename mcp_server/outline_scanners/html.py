"""סורק האאוטליין של HTML ותבניות Jinja.

**סורק לקסיקלי עם מחסנית, לא פרסר עץ.** תבנית Jinja אינה HTML תקין: תגית
שנפתחת בענף אחד של ``{% if %}`` ונסגרת בענף אחר היא הכתיב הרגיל כאן, לא
שגיאה. פרסר DOM "מתקן" את זה בשקט — הוא מזיז תגיות, סוגר מה שלא נסגר,
ומחזיר מספרי שורות שאינם במקום שבו הטקסט באמת יושב. סורק טוקנים שטוח לא
מנסה לאזן, ולכן גם לא משקר.

**מספר השורה נגזר מהאינדקס ואינו מתוחזק תוך כדי ריצה** — ראו
``_lines.py``, שם ההיגיון והמדידה. הגרסה הקודמת החזיקה מונה שהתקדם על כל
``\\n`` שנצרך, ושלוש קפיצות שהזיזו את האינדקס ביותר מתו אחד עקפו אותו.

**גוף של ``<script>`` ושל ``<style>`` נסרק על ידי תת-סורק**, וזה מה שהופך
בלוק בן אלף שורות ממפה שאין בה מה למצוא למפה שאפשר לנווט בה. בתבניות של
הפרויקט הזה יושבות 13,297 שורות בתוך בלוקי ``<style>`` — כמעט כמו בכל
קובצי ה-CSS יחד — ו-``dashboard.html`` החזיר אותן קודם כסימבול אחד בן
1,442 שורות.

השמות שטוחים ולא מנוקדים: ב-HTML אין מרחבי שמות, ו-``div`` בעומק שתים-עשרה
אינו שם משמעותי. התחילית נוספת רק כשיש עוגן אמיתי — ``id`` על בלוק
``<script>`` הופך את הפונקציות שבתוכו ל-``script#x.initColors``. **המשמעות
היא שהוספת ``id`` לבלוק קיים משנה את שמן של כל הפונקציות בתוכו**, בדיוק
כמו שעטיפת פונקציות במחלקה משנה שמות מתודות בפייתון. זו התנהגות ולא באג,
והיא כתובה כאן כדי שלא תיראה כמו באג בעוד חצי שנה.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from . import _ceiling
from . import css as _css
from ._lines import line_at, line_table

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

#: מקומפל פעם אחת ולא בכל קריאה — ``_read_rawtext`` רץ לכל תגית ``script``
#: ו-``style`` בקובץ, ו-``re.compile`` אינו מוחזק בקאש כמו ``re.search``.
_RAWTEXT_CLOSERS = {
    tag: re.compile(rf"</{tag}", re.IGNORECASE) for tag in _RAWTEXT_ELEMENTS
}

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

#: שם תכונה נגמר ברווח, ב-``/``, ב-``>`` או ב-``=``. מקור: מצב "attribute
#: name state" בטוקנייזר של WHATWG.
_ATTRIBUTE_NAME = re.compile(r"[^\s/>=]+")

#: הגדרת פונקציה ב-JavaScript, בצורות שמופיעות בפועל. ``base.html`` מכיל
#: 135 מהצורה הראשונה ו-24 מצורת החץ.
#:
#: **ההתאמה נעצרת לפני רשימת הפרמטרים** (``(?=\s*\()`` ולא ``\s*\(``), כדי
#: שהלולאה תספור בעצמה את הסוגריים העגולים. משם נגזר "האם אנחנו עדיין
#: בחתימה", במקום לנחש אותו מצורת הטקסט שהותאם.
#:
#: **``\s*(?:\*\s*)?`` ולא ``\s*\*?\s*``.** השתיים מתאימות בדיוק את אותה
#: שפה, אבל בצורה הישנה שני ה-``\s*`` צמודים ומופרדים באטום אופציונלי:
#: על רצף רווחים באורך *m* יש O(m) דרכים לפצל אותו, וכל פיצול נבדק מחדש
#: מול ``[A-Za-z_$]`` שנכשל. נמדד על ``<script>\nfunction`` ורצף רווחים:
#: 0.63 שניות ל-10KB, 2.53 ל-20KB, 9.98 ל-40KB — פי ארבע לכל הכפלה. ``\s``
#: כולל ``\n``, ולכן רצף שורות ריקות מספיק. הלולאה יושבת במנוע הרג'קס של
#: CPython שמחזיק את ה-GIL, ואי אפשר לבטל אותה מבחוץ.
#:
#: **``kw`` היא קבוצה בשם ולא בדיקת טקסט.** ממנה נגזר "הצורה הזאת חייבת
#: גוף בסוגריים מסולסלים", ראו ``_read_javascript``. בדיקה על צורת
#: ``group(0)`` הייתה חוזרת בדיוק על הכשל שתוקן כאן קודם — גזירת מצב
#: מהטקסט שהותאם במקום מעובדה מבנית על ההתאמה.
_JS_FUNCTION = re.compile(
    r"(?:async\s+)?(?P<kw>function)\s*(?:\*\s*)?(?P<name>[A-Za-z_$][\w$]*)(?=\s*\()"
)
#: רשימת הפרמטרים מכבדת רמת קינון אחת של סוגריים, ולא ``[^)]*``. הצורה
#: הרחבה התאימה ל-``const md = (a ? b : (()=>({x})))({`` — הצבה של תוצאת
#: קריאה, לא הגדרה — כי היא עצרה ב-``)`` הראשון ומצאה ``=>`` אחריו.
#: הקינון גם מרוויח: ``const k = (a, b = (1)) => a`` נתפס עכשיו, ולא היה.
#:
#: החלופה ``function\b`` **אינה** בולעת את ה-``(``, וצורת החץ **כן** בולעת
#: את ``(…)`` כי בלעדיה אי אפשר לראות את ה-``=>``. שתיהן עובדות מול אותו
#: כלל, כי בשנייה עומק הסוגריים חוזר לערכו עוד לפני סוף ההתאמה.
_JS_ASSIGNED = re.compile(
    r"\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s+)?(?:(?P<kw>function)\b|\((?:[^()]|\([^()]*\))*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)"
)

#: תו שאחריו ``/`` הוא חילוק ולא תחילת regex. הכלל המקובל: אחרי מזהה,
#: מספר, ``)`` או ``]`` מגיע אופרטור; בכל מקום אחר ``/`` פותח literal.
#: ב-``base.html`` יש תשעה regex literals, וחמישה מהם מכילים ``"`` — בלי
#: המצב הזה המרכאה הייתה פותחת מחרוזת ובולעת את הקוד שאחריה.
_BEFORE_DIVISION = re.compile(r"[\w$)\]]")


def extract(text: str) -> dict[str, Any]:
    """מפת הסימבולים של תבנית HTML/Jinja."""
    rows: list[dict[str, Any]] = _ceiling.Capped()
    try:
        return {"symbols": _read_template(text, rows)}
    except _ceiling.TooManySymbols:
        # **תופס את התקרה בלבד.** ``except Exception`` כאן היה מחזיר
        # "אין אאוטליין" על כל באג בסורק, על תבנית תקינה לגמרי — וזה
        # K11 בכיוון ההפוך. הנימוק המלא ב-``_ceiling.TooManySymbols``.
        return _ceiling.too_many_symbols()


def _read_template(text: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """הסריקה עצמה, בלי מעטפת התשובה.

    **שלוש המחסניות חסומות גם הן, ולא רק רשימת השורות.** נמדד:
    ``"<a>"`` שחוזר מיליון פעם הוא 3.00MB, מייצר **אפס** שורות — אין
    לו ``id`` — ומגיע ל-122.5MB, כי כל תגית נדחפת ל-``tags`` וממתינה
    לסוגר שלא יבוא. תקרה על השורות לבדן לא הייתה יורה שם בכלל; עם
    שלוש המחסניות חסומות אותו קלט נמדד ב-6.1MB.
    """
    tags: list[tuple[str, int, str | None]] = _ceiling.Capped()
    jinja: list[tuple[str, int, str]] = _ceiling.Capped()
    lines = line_table(text)
    index = 0
    size = len(text)

    while index < size:
        # ההערות נבדקות **לפני** כל דבר אחר, כדי שקוד מת בתוכן לא ייכנס
        # למפה. ``base.html`` מכיל 25 הערות HTML ותשע הערות Jinja, וחלקן
        # רב-שורתיות.
        if text.startswith("{#", index):
            index = _skip_past(text, index + 2, "#}")
            continue
        if text.startswith("<!--", index):
            index = _skip_past(text, index + 4, "-->")
            continue

        # תגית Jinja נבדקת לפני ``<``, כי היא יכולה לעטוף תגית HTML.
        if text.startswith("{%", index):
            stop = _jinja_tag_end(text, index)
            if stop < 0:
                # **תגית שלא נסגרה אינה תגית.** מדלגים על ``{%`` בלבד
                # וממשיכים לסרוק כטקסט, כדי שתגית תקינה שיושבת מתחתיה
                # תימצא כרגיל. בליעה עד סוף הקובץ הייתה מוחקת אותה יחד
                # עם השבורה.
                index += 2
                continue
            _read_jinja(text[index + 2 : stop - 2], line_at(lines, index), rows, jinja)
            index = stop
            continue
        if text.startswith("{{", index):
            index = _skip_past(text, index + 2, "}}")
            continue

        if text[index] == "<":
            index = _read_tag(text, index, lines, rows, tags)
            continue

        index += 1

    # תגיות שנשארו פתוחות בסוף הקובץ. זה הכתיב הרגיל בתבנית שנפתחת בענף
    # אחד ונסגרת באחר, ולכן הן מדווחות עד סוף הקובץ ולא נזרקות.
    last = line_at(lines, size)
    for name, opened, anchor in tags:
        if anchor:
            rows.append({"name": f"{name}#{anchor}", "start": opened, "end": last})
    for kind, opened, name in jinja:
        if kind in _JINJA_BLOCK_TAGS:
            rows.append({"name": f"{kind} {name}", "start": opened, "end": last})

    return rows


def _skip_past(text: str, start: int, needle: str) -> int:
    """מדלג עד אחרי ``needle``, או עד סוף הטקסט אם הוא לא נסגר.

    קטע שלא נסגר אינו שגיאה שמפילה את הסריקה: הקלט הוא קובץ שמישהו כתב,
    ובקובץ באמצע עריכה זה קורה. הוא נבלע עד הסוף, וזה גם מה שדפדפן עושה
    להערה או לביטוי שלא נסגרו. לתגית ``{% %}`` יש כלל אחר, ב-
    ``_jinja_tag_end``, כי שם בליעה עד הסוף מוחקת סימבולים תקינים.
    """
    stop = text.find(needle, start)
    return len(text) if stop < 0 else stop + len(needle)


def _jinja_tag_end(text: str, index: int) -> int:
    """הסוף של תגית ``{% ... %}``, או ``-1`` אם היא לא נסגרה.

    **הסוגר שנמצא חייב להיות של התגית הזאת.** ``text.find`` לבדו מחזיר את
    המופע הבא של ``%}`` איפשהו בקובץ, ולכן תגית שלא נסגרה בלעה את הסוגר
    של השכנה התקינה שמתחתיה — וזו נעלמה מהמפה לגמרי, עם ``status: "ok"``
    ובלי שום סימן שמשהו חסר. ``{%`` נוסף שמופיע לפני הסוגר פירושו שהסוגר
    שנמצא אינו שלנו.
    """
    stop = text.find("%}", index + 2)
    if stop < 0:
        return -1
    nested = text.find("{%", index + 2)
    if 0 <= nested < stop:
        return -1
    return stop + 2


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
                # מה שהיה פתוח **בתוך** התגית שנסגרה כבר לא ייסגר בנפרד;
                # הוא מדווח כאן עד אותה שורה, ולא נזרק בשקט. ``_close_tag``
                # עשה את זה למחסנית ה-HTML מהיום הראשון, וכאן זה חסר —
                # ולכן ``{% block %}`` שנפתח בתוך ``{% if %}`` ולא נסגר לפני
                # ה-``{% endif %}`` נמחק מהמפה בלי שום סימן. זה גם סתר את
                # מה שהתיעוד מבטיח, שתגית שלא נסגרה מדווחת עד סוף הקובץ.
                for inner, inner_line, inner_name in stack[depth:]:
                    if inner in _JINJA_BLOCK_TAGS:
                        rows.append(
                            {"name": f"{inner} {inner_name}", "start": inner_line, "end": line}
                        )
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
    lines: Sequence[int],
    rows: list[dict[str, Any]],
    stack: list[tuple[str, int, str | None]],
) -> int:
    """קורא תגית אחת מ-``<``. מחזיר את המיקום שאחריה."""
    line = line_at(lines, index)

    if text.startswith("</", index):
        name = _TAG_NAME.match(text, index + 2)
        if not name:
            return index + 1
        stop = _skip_past(text, index, ">")
        _close_tag(name.group(0).lower(), line, rows, stack)
        return stop

    name = _TAG_NAME.match(text, index + 1)
    if not name:
        return index + 1

    tag = name.group(0).lower()
    attributes, self_closing, stop = _read_attributes(text, name.end())
    #: ``id=""`` ו-``id`` בלי ערך אינם עוגן — נמדד ש-``getElementById("")``
    #: אינו מוצא כלום. אבל ``id=" "`` **כן** עוגן תקין ובר-מציאה, ולכן
    #: הערך נלקח גולמי ורק ריקנות אמיתית שוללת אותו.
    anchor = _attribute(attributes, "id") or None

    if tag in _RAWTEXT_ELEMENTS:
        return _read_rawtext(
            text, stop, lines, tag,
            label=f"{tag}#{anchor}" if anchor else tag,
            opened=line,
            prefix=f"{tag}#{anchor}." if anchor else "",
            reader=_body_reader(tag, attributes),
            rows=rows,
        )

    if tag not in _VOID_ELEMENTS and not self_closing:
        stack.append((tag, line, anchor))
    elif anchor:
        rows.append({"name": f"{tag}#{anchor}", "start": line, "end": line_at(lines, stop)})

    return stop


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


def _read_attributes(text: str, start: int) -> tuple[list[tuple[str, str]], bool, int]:
    """קורא את התכונות עד ``>``, ומחזיר אותן **מפורסות**.

    **הפרסינג נעשה כאן, פעם אחת.** הגרסה הקודמת החזירה את מחרוזת התכונות
    הגולמית, ומי שרצה ``id`` או ``type`` הריץ עליה רג'קס — ואז ``id=``
    שיושב **בתוך ערך של תכונה אחרת** ניצח. שתי תוצאות, שתיהן נמדדו:
    ``<div title="x id=decoy" id="real">`` החזיר ``div#decoy"``, שם שאינו
    קיים בקובץ בכלל; ו-``<script data-note="see type=text/plain">`` סווג
    כלא-JavaScript, כך שכל הפונקציות שבתוך הבלוק נעלמו מהמפה.

    **הלוכסן בערך לא מצוטט שייך לערך, לא לתגית.** נמדד ב-Chromium
    141.0.7390.37: ``<a id="k" href=/>text</a>`` נותן ``href="/"`` ואת
    הטקסט **בתוך** ה-``<a>``. לפי הטוקנייזר של WHATWG, ערך לא מצוטט נגמר
    ברווח או ב-``>`` בלבד. הגרסה הקודמת בדקה ``endswith("/")`` על המחרוזת
    הגולמית וסימנה את התגית כסוגרת את עצמה.
    """
    attributes: list[tuple[str, str]] = []
    index = start
    size = len(text)
    #: לוכסן שנראה ואינו חלק מערך. רק לוכסן שמגיע ממש לפני ``>`` סוגר.
    solidus = False

    while index < size:
        char = text[index]
        if char == ">":
            return attributes, solidus, index + 1
        if char.isspace():
            index += 1
            continue
        if char == "/":
            solidus = True
            index += 1
            continue

        solidus = False
        name = _ATTRIBUTE_NAME.match(text, index)
        if not name:
            index += 1
            continue
        index = name.end()

        while index < size and text[index].isspace():
            index += 1
        value = ""
        if index < size and text[index] == "=":
            index += 1
            while index < size and text[index].isspace():
                index += 1
            if index < size and text[index] in "\"'":
                # ``<div title="a > b">`` הוא תגית אחת. חיפוש ``>`` בלי
                # לכבד מחרוזות היה חותך אותה באמצע.
                quote = text[index]
                closing = text.find(quote, index + 1)
                stop = size if closing < 0 else closing
                value = text[index + 1 : stop]
                index = min(stop + 1, size)
            else:
                stop = index
                while stop < size and not text[stop].isspace() and text[stop] != ">":
                    stop += 1
                value = text[index:stop]
                index = stop

        attributes.append((name.group(0).casefold(), value))

    return attributes, solidus, size


def _attribute(attributes: list[tuple[str, str]], name: str) -> str | None:
    """הערך **הגולמי** של תכונה, או ``None`` אם היא נעדרת.

    הראשונה מנצחת, כמו בדפדפן: תכונה כפולה נזרקת ולא דורסת.

    **והערך אינו מקוצץ כאן, בכוונה.** גרסה קודמת עשתה
    ``value.strip() or None`` — כלומר אפתה נרמול של צרכן אחד לתוך גטר
    משותף, ושלושת הצרכנים דורשים שלושה דברים שונים. נמדד ב-Chromium
    141: ``<script type=" text/javascript ">`` **כן** רץ (רווחים
    מקוצצים), ``<style type=" text/css ">`` **אינו** יוצר גיליון
    (התאמה מדויקת), ו-``<span id=" x ">`` שומר את הרווחים —
    ``getElementById(" x ")`` מוצא אותו. הקיצוץ המשותף שבר את שני
    האחרונים: ``<style type=" ">`` הפך ל-``None`` ונקרא כ"אין ``type``
    בכלל", כלומר נסרק כ-CSS בזמן שהדפדפן אינו מחיל אותו.

    בקורפוס הזה יש אפס תכונות ``id`` או ``type`` עם רווחים בקצוות, ולכן
    זו התאמה לשפה ולא לקורפוס — והכלי משרת כל ריפו ממורר, לא רק את זה.
    """
    for found, value in attributes:
        if found == name:
            return value
    return None


def _is_javascript(attributes: list[tuple[str, str]]) -> bool:
    """האם הבלוק הזה הוא JavaScript שראוי לרדת לתוכו.

    היעדר ``type``, ``type`` ריק, ``module``, או MIME type של JavaScript.
    כל השאר הוא data block שהדפדפן אינו מריץ — ב-``base.html`` יש ארבעה
    ``application/json``, ו-``JSON`` שנסרק כ-JS היה מייצר סימבולים
    ממחרוזות שבמקרה נראות כמו הגדרות.
    """
    declared = _attribute(attributes, "type")
    if declared is None:
        return True
    #: הקיצוץ כאן, ולא ב-``_attribute``, כי הוא נכון ל-``<script>``
    #: בלבד — נמדד: ``type=" text/javascript "`` רץ.
    normalized = declared.strip().casefold()
    return normalized in {"", "module"} or normalized in _JAVASCRIPT_MIME_ESSENCES


#: ה-MIME type היחיד שגורם ל-``<style>`` להיות CSS. **נמדד ולא נכתב
#: מהזיכרון**, ב-Chromium 141.0.7390.37: ``type="text/plain"`` אינו יוצר
#: ``sheet`` בכלל, ו-``type="text/css; charset=utf-8"`` **גם הוא לא** —
#: פרמטרים נדחים, בדיוק כמו ב-essence match של ``<script>``. היעדר
#: ``type`` ו-``type=""`` כן חלים, וההשוואה אינה תלוית רישיות.
#:
#: בתבניות של הפרויקט אין היום אף ``<style type=...>``, ולכן זו התאמה
#: לשפה ולא לקורפוס — כמו שאר המקרים כאן.
_CSS_MIME_ESSENCE = "text/css"


def _is_css(attributes: list[tuple[str, str]]) -> bool:
    """האם גוף ה-``<style>`` הזה הוא CSS שראוי לרדת לתוכו.

    **ואין כאן ``strip()``, בשונה מ-``_is_javascript`` — נמדד ב-Chromium
    141.** ``<style>`` עושה התאמה מדויקת (לא תלוית רישיות) ל-``""`` או
    ל-``text/css``, וכל רווח בכל מקום מבטל אותה: ``type=" text/css "``,
    ``type="\ttext/css\n"``, ``type="text/css "`` ואפילו ``type=" "``
    כולם מחזירים ``sheet == null``. ``<script>`` **כן** מקצץ —
    ``type=" text/javascript "`` רץ. שני התגים באמת נבדלים, ולכן שני
    הקודים נבדלים.
    """
    declared = _attribute(attributes, "type")
    if declared is None:
        return True
    return declared.casefold() in {"", _CSS_MIME_ESSENCE}


#: מי סורק את גוף הבלוק. ``None`` פירושו שלא יורדים לתוכו — הבלוק מדווח
#: כגבול, וזו התשובה הנכונה ל-data block שהדפדפן אינו מריץ.
#: תת-הסורק **כותב** לרשימה שהוא מקבל ואינו מחזיר אחת, כדי שהתקרה
#: תהיה תקציב אחד לכל הקובץ ולא אחד לכל בלוק. הנימוק והמדידה
#: ב-``css.read_blocks``.
_BodyReader = Callable[
    [str, int, int, Sequence[int], str, list[dict[str, Any]]], None
]


def _body_reader(tag: str, attributes: list[tuple[str, str]]) -> _BodyReader | None:
    """בוחר את תת-הסורק לגוף של ``<script>`` או ``<style>``.

    ההחלטה נגזרת מהתכונות **המפורסות** ולא מהמחרוזת הגולמית, וזה מה
    שמונע מ-``type=`` שיושב בתוך ערך של תכונה אחרת להכריע אותה.
    """
    if tag == "script":
        return _read_javascript if _is_javascript(attributes) else None
    if tag == "style":
        return _css.read_blocks if _is_css(attributes) else None
    return None


def _read_rawtext(
    text: str,
    start: int,
    lines: Sequence[int],
    tag: str,
    label: str,
    opened: int,
    prefix: str,
    reader: _BodyReader | None,
    rows: list[dict[str, Any]],
) -> int:
    """קורא גוף של ``<script>`` או ``<style>`` עד תגית הסגירה שלו.

    מחזיר את המיקום שאחרי תגית הסגירה, ומוסיף ל-``rows`` את הבלוק עצמו
    ואחריו מה שתת-הסורק מצא בתוכו. **הדיווח נעשה כאן ולא אצל הקורא**
    כדי שהסדר יישמר: תגית הסגירה נמצאת לפני שתת-הסורק רץ, ולכן אפשר
    לרשום את הבלוק תחילה — ורשימה שתת-הסורק כותב לתוכה אינה יכולה
    להיכנס אחריו אם הוא נרשם אחריה.

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
    # לפי ``RANGE_READ_MAX_BYTES``.
    found = _RAWTEXT_CLOSERS[tag].search(text, start)
    stop = found.start() if found else len(text)
    after = _skip_past(text, stop, ">")

    # תת-הסורק מקבל את הטקסט עם גבולות ולא פרוסה שלו: פרוסה היא מרחב
    # אינדקסים אחר, וטבלת השורות אחת לכל הקובץ. זה גם חוסך עותק של עד
    # 10MB לכל תגית. שני תת-הסורקים חולקים את החתימה הזאת בדיוק, וזה מה
    # שמאפשר לבחור ביניהם בלי ענף בתוך הקורא.
    rows.append({"name": label, "start": opened, "end": line_at(lines, after)})
    if reader:
        reader(text, start, stop, lines, prefix, rows)
    return after


class _Pending(NamedTuple):
    """הגדרת פונקציה שנרשמה וממתינה לגוף שלה.

    ``body_depth`` הוא ``-1`` כל עוד הגוף לא התחיל. ``parens`` הוא עומק
    הסוגריים העגולים **ברגע ההתאמה** — ה-``{`` פותח את הגוף רק כשחוזרים
    אליו, וזה מה שמונע מ-``{`` שיושב בתוך רשימת הפרמטרים לפתוח גוף.
    ``awaits_brace`` אומר שהצורה הזאת חייבת גוף בסוגריים מסולסלים, ולכן
    אסור לסגור אותה בסוף שורה.

    ``body_from`` הוא ההיסט שאחרי ההתאמה — כלומר המקום שממנו הגוף **יכול**
    להתחיל. ממנו נגזר "האם הגוף בכלל התחיל", וזה מה שמונע סגירה בשורת
    ה-``=>`` כשהגוף מתחיל בשורה שאחריה.

    זה ``NamedTuple`` ולא טאפל רגיל כי שישה שדות שניגשים אליהם לפי מספר
    מיקום הם שבירות מיותרת בלולאה צפופה.
    """

    name: str
    opened: int
    body_depth: int
    parens: int
    brackets: int
    awaits_brace: bool
    body_from: int


#: תו שאם הוא האחרון בשורה, הביטוי שלפניו **חסר** ולכן חייב להימשך לשורה
#: הבאה. **נמדד ב-Node 22.22.2 ולא נכתב מהזיכרון**, ובשאלה דקדוקית טהורה
#: שאין בה תלות ב-ASI ובשום ערך החזרה: האם ``(a C)`` הוא שגיאת תחביר
#: בזמן ש-``(a C b)`` תקין? אם כן — ``C`` דורש אופרנד ימני, ושורה
#: שנגמרת בו אינה יכולה לסיים את הביטוי.
#:
#: ``:`` נכנס אף שהמבחן הזה דחה אותו לבדו, כי הוא נמדד בנפרד בהקשר של
#: תלתן: ``a ? 1 :`` ואז ``2`` בשורה הבאה הוא קוד תקין. מחוץ לתלתן
#: ``a :`` אינו חוקי בכלל, ולכן הכללתו אינה עולה דבר על קלט תקין.
#:
#: מה ש**אינו** כאן, ומאותה מדידה: ``! ~ { ; ) ] }``, מזהים וספרות —
#: כולם יכולים לסיים ביטוי או משפט.
_UNFINISHED_EXPRESSION = re.compile(r"[-+*/%.,?:&|^<>=([]")


def _concise_body_ended(
    waiting: _Pending, token: str, token_at: int, parens: int, brackets: int
) -> bool:
    """האם גוף החץ של ``waiting`` נגמר ב-``index``, שהוא ירידת שורה?

    זה המקום היחיד שסוגר פונקציה בגבול שורה, והוא קיים בשביל צורה אחת:
    חץ בלי גוף בסוגריים מסולסלים (``const f = x => x + 1``), שאין דבר
    אחר שיסגור אותו. **שלוש סיבות שונות שלא לסגור, וכל אחת נחוצה בפני
    עצמה:**

    ``awaits_brace`` מוציא את מי שחייב גוף מסולסל — צורת ``function``
    בכל וריאציה — ואת החץ שגופו המסולסל מתחיל בשורה הבאה (סגנון Allman).

    **הגוף אינו יכול להיות ריק.** ``const f = (a) =>`` ואז ``;`` הוא
    ``SyntaxError`` ב-Node 22.22.2, ולכן ירידת השורה שצמודה ל-``=>``
    לעולם אינה מסיימת את הגוף — הגוף פשוט מתחיל בשורה הבאה. בלי התנאי
    הזה הצורה הזאת קיבלה ``end == start`` על פונקציה שלמה, בדיוק כמו
    סגנון Allman לפני שתוקן.

    **ושורה שנגמרת באופרטור אינה מסיימת את הביטוי**, ולכן גוף שפרוס על
    כמה שורות נסגר בשורה שבה הביטוי באמת נגמר. שלושה מנגנונים, וכל אחד
    למשכיות מסוג אחר: ``parens`` לסוגריים עגולים פתוחים, ``brackets``
    למרובעים, ו-``_UNFINISHED_EXPRESSION`` לשורה שנגמרת באופרטור.

    **ומה שהם עדיין אינם מכסים, מדוד ומוצהר:** המשכיות שמסומנת בתחילת
    השורה **הבאה** ולא בסוף הנוכחית. ``const h = () => list`` ואז
    ``.map(…)`` בשורה נפרדת נסגר בשורה הראשונה, כי ``list`` הוא מזהה
    ותקין כסוף ביטוי — וההסתכלות כאן היא אחורה בלבד. זו הגדרה אחת עם
    ``end`` מוקדם, לא בליעה של הבלוק, ותיקונה דורש קורא-קדימה שהוא
    שינוי בסדר גודל אחר.

    **ו"הגוף התחיל" נגזר מהיסט ולא מסריקה חוזרת.** גרסה קודמת קראה כאן
    ל-``_next_meaningful`` מ-``body_from`` עד ``index`` — כלומר סרקה מחדש
    את כל מה שנצבר, בכל ירידת שורה. נמדד: גדילה של פי ארבע לכל הכפלה
    (4.05, 3.71, 3.99), ו-80KB ב-1.72 שניות — בהסקה לתקרת ה-10MB, שעות.
    ``token_at``, ההיסט של הטוקן המשמעותי האחרון, עונה על אותה שאלה
    בהשוואת שני מספרים: אותו קלט ב-0.0031 שניות, פי 554, וגדילה של פי
    1.8. השקילות אינה הנחה: שני מסלולי הדילוג בלולאה — רווחים והערות —
    אינם נוגעים ב-``token``, ולכן "הטוקן האחרון קודם ל-``body_from``"
    הוא בדיוק "אין תו משמעותי בין ``body_from`` ל-``index``".
    """
    if waiting.body_depth >= 0 or waiting.awaits_brace:
        return False
    if parens > waiting.parens or brackets > waiting.brackets:
        return False
    if token_at < waiting.body_from:
        return False
    return not _UNFINISHED_EXPRESSION.match(token)


def _next_meaningful(text: str, index: int, stop: int) -> str:
    """התו הבא שאינו רווח ואינו הערה, או מחרוזת ריקה אם אין כזה.

    **הערות נספרות כרווח, וזה לא קישוט.** ``function foo()`` ואחריו
    ``// why`` ואז ``{`` בשורה נפרדת הוא JavaScript תקין — אומת ב-Node
    22.22.2 דרך ``new Function``. קורא-קדימה שמסתפק ב"התו הלא-רווח הבא"
    היה רואה ``/`` ומחמיץ את הגוף.
    """
    while index < stop:
        char = text[index]
        if char.isspace():
            index += 1
        elif text.startswith("//", index):
            found = text.find("\n", index)
            index = stop if found < 0 else min(found, stop)
        elif text.startswith("/*", index):
            found = text.find("*/", index + 2)
            index = stop if found < 0 else min(found + 2, stop)
        else:
            return char
    return ""


def _read_javascript(
    text: str,
    start: int,
    stop: int,
    lines: Sequence[int],
    prefix: str,
    rows: list[dict[str, Any]],
) -> None:
    """מוסיף ל-``rows`` את הגדרות הפונקציות שבתוך בלוק סקריפט.

    זה מה שהופך בלוק בן שבע-מאות שורות למפה שאפשר לנווט בה. בלוק שמוחזר
    כסימבול אחד אינו מפה — הוא רק גבול.

    המצבים הם מחרוזת, template literal, שתי צורות הערה, ו-**regex
    literal**. האחרון אינו קישוט: ב-``base.html`` יש ``.replace(/"/g, ...)``
    בשלושה מקומות, והמרכאה שבתוך ה-regex הייתה פותחת מחרוזת ובולעת את הקוד
    עד המרכאה הבאה.

    **"האם אנחנו עדיין בחתימה" נגזר מעומק הסוגריים, ולא נקבע בהתאמה.**
    ``function f(a, opts = {})`` מכיל ``{`` שאינו פותח את גוף הפונקציה,
    ורישום העומק ברגע ההתאמה גרם ל-``}`` שסוגר את ברירת המחדל לסגור את
    הפונקציה כולה — ``end == start`` בשורת החתימה, ב-136 מתוך 841
    ההגדרות. הגרסה הקודמת ניסתה לתקן את זה במונה שנקבע מ**צורת הטקסט
    שהותאם** (``group(0).endswith("(")``), ונכשלה בשני כיוונים: היא לא
    חלה על ``const f = function (…)``, שבו ההתאמה נגמרת במילה ``function``;
    וכשהמונה לא חזר לאפס — סוגר עגול אחד שלא נסגר — היא חסמה כל התאמה
    חדשה ו**השתיקה את שאר הבלוק**.

    עכשיו הלולאה סופרת ``parens`` תמיד, וכל פונקציה ממתינה זוכרת את
    ``parens`` שברגע ההתאמה. ה-``{`` פותח את הגוף רק כשחזרנו לערך ההוא.
    סוגר שלא נסגר מקלקל פונקציה אחת במקום בלוק שלם.

    **וסגירה בסוף שורה חלה רק על מי שרשאי להיגמר שם.** הענף הזה קיים
    בשביל חץ בלי גוף מסולסל (``const f = x => x + 1``), שאין דבר אחר
    שיסגור אותו. אבל הוא לא הבחין בין "אין גוף מסולסל" לבין "הגוף מתחיל
    בשורה הבאה", ולכן סגנון Allman — ``{`` בשורה נפרדת — החזיר
    ``end == start`` על פונקציה שלמה, בשלוש הצורות.

    ההבחנה נלקחת **ברגע ההתאמה** ונשמרת ב-``awaits_brace``, ולא נבדקת
    שוב בכל שורה. אומת ב-Node 22.22.2 דרך ``new Function``: ``function``
    בכל צורותיו — הצהרה, ביטוי, גנרטור, ``async`` — הוא **SyntaxError**
    בלי גוף בסוגריים מסולסלים, ולכן צורה כזאת ממתינה תמיד. רק חץ יכול
    בלי סוגריים, ואצלו ההמתנה נקבעת לפי מה שבא אחרי ה-``=>``.
    """
    pending: list[_Pending] = _ceiling.Capped()
    depth = 0
    parens = 0
    brackets = 0
    index = start
    #: הטוקן הלא-רווח האחרון, ו**ההיסט שלו**. שני צרכנים, ולכן שני
    #: משתנים: ``token`` מבדיל בין regex לחילוק (ושם הסימון ``"x"``
    #: לאחר מחרוזת, regex או חתימה נושא משקל — הוא אומר "טוקן שאינו
    #: אופרטור"), ו-``token_at`` עונה על "האם גוף החץ בכלל התחיל" בלי
    #: לסרוק אותו מחדש. שניהם מתעדכנים באותם ארבעה אתרים בדיוק.
    token = ""
    token_at = start - 1

    while index < stop:
        char = text[index]

        if char == "\n":
            # ``const f = x => x + 1`` בלי גוף מסולסל נגמר בסוף השורה,
            # וכל הסיבות שלא לסגור יושבות ב-``_concise_body_ended``.
            while pending and _concise_body_ended(
                pending[-1], token, token_at, parens, brackets
            ):
                done = pending.pop()
                rows.append({
                    "name": f"{prefix}{done.name}", "start": done.opened,
                    "end": line_at(lines, index),
                })
            index += 1
            continue

        if text.startswith("//", index):
            found = text.find("\n", index)
            index = stop if found < 0 else min(found, stop)
            continue
        if text.startswith("/*", index):
            index = min(_skip_past(text, index + 2, "*/"), stop)
            continue
        if char in "\"'`":
            index = _skip_string(text, index, stop)
            token = "x"
            token_at = index - 1
            continue
        if char == "/" and not _BEFORE_DIVISION.match(token):
            index = _skip_regex(text, index, stop)
            token = "x"
            token_at = index - 1
            continue

        if char == "(":
            parens += 1
        elif char == ")":
            parens -= 1
        elif char == "[":
            brackets += 1
        elif char == "]":
            brackets -= 1
        elif char == "{":
            depth += 1
            # פונקציה שממתינה לגוף (``-1``) מקבלת כאן את עומקה האמיתי —
            # אבל רק אם רשימת הפרמטרים כבר נסגרה.
            if pending and pending[-1].body_depth < 0 and parens <= pending[-1].parens:
                pending.append(pending.pop()._replace(body_depth=depth - 1))
        elif char == "}":
            depth -= 1
            while pending and 0 <= pending[-1].body_depth >= depth:
                done = pending.pop()
                rows.append({
                    "name": f"{prefix}{done.name}", "start": done.opened,
                    "end": line_at(lines, index),
                })
        elif char.isalpha() or char in "_$":
            # ``adjacent`` הוא התו ה**צמוד** ולא הטוקן האחרון. שני
            # השימושים נראים דומים ואינם: ל-regex צריך את הטוקן הקודם
            # (``x /2`` הוא חילוק), ולגבול מזהה צריך את התו הסמוך.
            # משתנה אחד לשניהם חסם הגדרה לגיטימית אחרי ``var s = "abc"``
            # בלי נקודה-פסיק, אחרי ``init()`` ואחרי ``arr[0]``.
            adjacent = text[index - 1] if index > start else ""
            match = (
                _JS_FUNCTION.match(text, index, stop)
                or _JS_ASSIGNED.match(text, index, stop)
            )
            if match and not _BEFORE_DIVISION.match(adjacent):
                # ``-1`` = "ממתין לגוף". ה-``{`` שיגיע כשעומק הסוגריים
                # יחזור לערך שנשמר כאן הוא זה שיקבע את העומק.
                #
                # ``kw`` היא קבוצה בשם, כלומר עובדה מבנית על ההתאמה ולא
                # בדיקה על צורת הטקסט שהותאם. צורת ``function`` חייבת גוף
                # מסולסל לפי הדקדוק; אצל חץ צריך להסתכל מה בא אחרי
                # ה-``=>``, ולכן קורא-קדימה שמדלג גם הערות.
                pending.append(_Pending(
                    name=match.group("name"),
                    opened=line_at(lines, index),
                    body_depth=-1,
                    parens=parens,
                    brackets=brackets,
                    awaits_brace=(
                        match.group("kw") is not None
                        or _next_meaningful(text, match.end(), stop) == "{"
                    ),
                    body_from=match.end(),
                ))
                index = match.end()
                token = "x"
                #: התו האחרון של החתימה, כלומר ``body_from - 1``. חייב
                #: להיות **לפני** ``body_from``, אחרת ההתאמה עצמה נראית
                #: כמו גוף שהתחיל והפונקציה תיסגר בשורת החתימה.
                token_at = index - 1
                continue

        if not char.isspace():
            token = char
            token_at = index
        index += 1

    # פונקציות שלא נסגרו עד סוף הבלוק.
    last = line_at(lines, stop)
    for waiting in pending:
        rows.append({"name": f"{prefix}{waiting.name}", "start": waiting.opened, "end": last})


def _skip_string(text: str, index: int, stop: int) -> int:
    """מדלג על מחרוזת, כולל template literal עם ``${...}`` מקונן.

    **המונה חייב לספור את אותם תווים בשני הכיוונים.** גרסה קודמת העלתה
    את ``nesting`` רק על ``${`` אך הורידה אותו על **כל** ``}``, ולכן
    אובייקט או גוף בלוק בתוך ``${...}`` הורידו אותו לאפס בטרם עת. משם
    ה-backtick הבא נקרא כסוגר של המחרוזת החיצונית, והסורק המשיך לקרוא
    טקסט HTML כאילו הוא קוד — ושלוש פונקציות נעלמו מהמפה לגמרי:
    ``renderStoryCell`` ו-``renderAiExplainCell`` ב-
    ``admin_observability.html``, ו-``executedFunction`` ב-
    ``md_preview.html``.

    **מחסנית מפורשת ולא רקורסיה.** מחרוזת שנפתחת בתוך ``${...}`` הייתה
    נכנסת למסגרת חדשה בלי חסם, ולכן קובץ של כ-3KB — ``` `${ ``` שחוזר
    994 פעם — הפיל ``RecursionError`` שאיש לא תפס לאורך כל המסלול עד
    לקוח ה-MCP. זה סתר את מה שהמודול מצהיר על עצמו, שערוץ הכשל הוא ערך
    ההחזרה ולא חריגה, ואת מה שהפרויקט כבר קיבע לסורק הפייתון ב-
    ``test_deep_nesting_does_not_raise_from_our_side``.
    """
    quotes = [text[index]]
    #: כמה ``{`` פתוחים בתוך ה-``${...}`` של כל רמה במחסנית.
    nesting = [0]
    index += 1

    while index < stop:
        char = text[index]
        if char == "\\":
            index += 2
            continue

        quote = quotes[-1]
        if quote == "`" and char == "$" and index + 1 < stop and text[index + 1] == "{":
            nesting[-1] += 1
            index += 2
            continue
        if nesting[-1] and char in "\"'`":
            # מחרוזת מקוננת בתוך ההחלפה. בלי זה, ``}`` שיושב בתוכה היה
            # מוריד את המונה ומוציא אותנו מה-template מוקדם.
            quotes.append(char)
            nesting.append(0)
            index += 1
            continue
        if nesting[-1] and char == "{":
            nesting[-1] += 1
        elif nesting[-1] and char == "}":
            nesting[-1] -= 1
        elif char == quote:
            quotes.pop()
            nesting.pop()
            if not quotes:
                return index + 1
        index += 1

    return stop


def _skip_regex(text: str, index: int, stop: int) -> int:
    """מדלג על regex literal, כולל מחלקת תווים ``[...]`` שיכולה להכיל ``/``."""
    index += 1
    in_class = False
    while index < stop:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "\n":  # regex אינו חוצה שורות — כנראה היה חילוק
            return index
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            return index + 1
        index += 1
    return stop

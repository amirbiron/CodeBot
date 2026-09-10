"""סורק האאוטליין של CSS.

**הסימבול הוא בלוק הסלקטור, אבל העיקר הוא ה-at-rules.** שם קבורים המובייל
וה-RTL, ושם באמת מחפשים: מפה שמראה ש-``@media (max-width: 768px)`` יושב
בשורות 400-520 שווה יותר מכל חיפוש טקסט, כי אחריה אפשר להמשיך ישר
ל-``lines=[400, 520]``.

**לקסר עם מחסנית, לא רג'קס.** ``CORE-PATTERNS.md`` U3 מזהיר במפורש מפני
רג'קס חמדן מעל טקסט חיצוני, ו-CSS נותן לזה ראיה: סוגריים מסולסלים יושבים
בקורפוס הזה בתוך הערות שמצטטות CSS, ``@`` יושב בתוך הערה
(``Maintainer: @Hirse``), ו-``;`` יושב בתוך ``url()`` מצוטט
(``url('data:image/svg+xml;utf8, …')``). כל אחד מהם היה מבלבל התאמת
תבנית, ואף אחד מהם אינו מבלבל מכונת מצבים.

**המצבים:** קוד, ``/* … */``, ``'…'``, ``"…"``, ``url(`` לא מצוטט (שבו
``)`` הוא הסוגר), ומבני Jinja.

**Jinja מדולג ללא תנאי, ושני הכיוונים נמדדו.** בקובצי ``.css`` בריפו יש
אפס מבני Jinja, ולכן הדילוג אינו עולה דבר; בבלוקי ``<style>`` בתבניות
שמונה מתוך 48 כן מכילים, ולכן הוא חובה. ``base.html`` מחזיק את המקרה:

.. code-block:: css

   :root[data-theme="custom"] {
       {% for var_name, var_value in custom_theme.variables.items() %}
       {{ var_name }}: {{ var_value }};
       {% endfor %}
   }

לקסר שאינו מדלג סופר כאן תשעה בלוקים בתשע שורות. עם הדילוג — סימבול אחד,
``:root[data-theme="custom"]``, וזה הנכון.

**ההערות מוסרות מה-prelude, וזה הדבר המרכזי בסורק הזה.** אב-טיפוס שלא
הסיר אותן החזיר שם באורך 1,699 בתים שהוא הערה בעברית ולא סלקטור, ניפח את
מונה הסלקטורים הרב-שורתיים מ-448 ל-867, וספר ``@media`` 37 במקום 68.
אחרי ההסרה כל המספרים התיישבו בדיוק על מונה ה-``{`` הבלתי-תלוי.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, NamedTuple

from ._lines import line_at, line_table

#: רצף רווחים כלשהו ← רווח יחיד. סלקטור שפרוס על כמה שורות הופך לשם אחד,
#: ובקורפוס הזה יש 448 כאלה.
_WHITESPACE = re.compile(r"\s+")

#: המילה של at-rule, בלי תחילית ספק. **תחילית הספק אינה ניחוש**: נמדד
#: ב-Chromium 141.0.7390.37 ש-``@-webkit-keyframes`` ממופה לאותו
#: ``CSSKeyframesRule`` כמו ``@keyframes``, כלומר הילדים שלו הם צעדים
#: גם שם. בקורפוס הזה יש אפס מופעים מקדימים, ולכן זו התאמה לשפה ולא
#: לקורפוס.
_AT_KEYWORD = re.compile(r"@(?:-[A-Za-z]+-)?([A-Za-z-]+)")

#: ``url(`` הוא פונקציה, ושמות פונקציות ב-CSS אינם תלויי רישיות. רג'קס
#: ולא ``text[i:i+4].lower()``: ``lower()`` יכול לשנות **אורך** (``İ``
#: הופך לשני תווים), וכל אריתמטיקת אינדקסים על עותק ממוזער היא בדיוק
#: ``BY-STACK/hebrew-source.md`` H6.
_URL_FUNCTION = re.compile(r"url\(", re.IGNORECASE)

#: תו שאם הוא צמוד ל-``url(`` מלפנים, זו פונקציה אחרת ולא ``url``.
#: ``-webkit-image-set(url(…))`` הוא כן ``url`` כי לפניו ``(``.
_IDENT_CHARACTER = re.compile(r"[\w-]")

#: מבני Jinja. הסדר לא משנה כי שלושתם נבדקים במקביל, אבל ``{#`` חייב
#: להיבדק לפני ``{`` הרגיל כדי שהערת Jinja לא תיקרא כפתיחת בלוק.
_JINJA_OPENERS = (("{%", "%}"), ("{{", "}}"), ("{#", "#}"))

#: at-rule שהילדים שלו **אינם** כללים עם סלקטור אלא צעדים.
#:
#: נמדד ב-CSSOM של Chromium 141.0.7390.37 ולא נכתב מהזיכרון: הילדים של
#: ``@keyframes`` הם ``CSSKeyframeRule`` עם ``keyText`` (``0%``) ובלי
#: ``selectorText``, בזמן ש-``@media``, ``@supports``, ``@layer``,
#: ``@container`` ו-``@scope`` כולם מחזירים ``CSSStyleRule`` עם סלקטור.
#: ``@font-face``, ``@page``, ``@counter-style`` ו-``@property`` מחזירים
#: אפס כללי-בן, ולכן אין בהם לְמה לרדת ואינם דורשים טיפול.
#:
#: ``0%`` ו-``to`` הם רעש ולא ניווט, ולכן צעד אינו סימבול. בקורפוס יש 54.
_AT_RULES_WHOSE_CHILDREN_ARE_STEPS = frozenset({"keyframes"})


class _Open(NamedTuple):
    """בלוק שנפתח וממתין ל-``}`` שלו.

    ``anchor`` הוא ההיסט של התו הראשון של ה-prelude שאינו רווח ואינו
    הערה — כלומר של הסלקטור עצמו, ולא של ההערה שמעליו. ``keyframes``
    אומר שהילדים של הבלוק הזה הם צעדים; ``step`` אומר שהבלוק הזה **הוא**
    צעד, ולכן אינו סימבול.
    """

    name: str
    anchor: int
    keyframes: bool
    step: bool


def extract(text: str) -> dict[str, Any]:
    """מפת הסימבולים של קובץ CSS.

    זהו חוזה הסורק שהראוטר קורא לו. ערוץ הכשל הוא ערך ההחזרה ולא חריגה,
    ולכן קלט פגום — בלוק שלא נסגר, מחרוזת שלא נסגרה, הערה בלי סוגר —
    מוחזר כמפה חלקית ולא זורק. זה לא ויתור: קובץ באמצע עריכה הוא קלט
    לגיטימי כאן, וזה גם מה שדפדפן עושה.
    """
    return {"symbols": read_blocks(text, 0, len(text), line_table(text), "")}


def read_blocks(
    text: str, start: int, stop: int, lines: Sequence[int], prefix: str
) -> list[dict[str, Any]]:
    """הבלוקים שבין ``start`` ל-``stop``.

    אותו לקסר משרת גם קובץ ``.css`` שלם וגם גוף של ``<style>`` בתוך
    תבנית. הוא מקבל את הטקסט עם גבולות ולא פרוסה שלו: פרוסה היא מרחב
    אינדקסים אחר, וטבלת השורות אחת לכל הקובץ.
    """
    rows: list[dict[str, Any]] = []
    stack: list[_Open] = []
    index = start
    #: ה-prelude נאסף בחלקים, כי ההערות שבתוכו מושמטות ממנו.
    pieces: list[str] = []
    chunk_from = index
    anchor = -1

    def take(upto: int) -> None:
        """אוסף את הקטע שעד ``upto`` ל-prelude, ומקבע את העוגן בפעם הראשונה."""
        nonlocal anchor
        piece = text[chunk_from:upto]
        if anchor < 0:
            trimmed = piece.lstrip()
            if trimmed:
                anchor = chunk_from + (len(piece) - len(trimmed))
        pieces.append(piece)

    def restart(at: int) -> None:
        """פותח prelude חדש. נקרא אחרי ``{``, ``}`` ו-``;``."""
        nonlocal chunk_from, pieces, anchor
        chunk_from, pieces, anchor = at, [], -1

    while index < stop:
        char = text[index]

        if text.startswith("/*", index):
            # ההערה יוצאת מה-prelude, אבל **אינה** שוברת אותו:
            # ``.a /* x */ .b {`` הוא סלקטור אחד חוקי.
            take(index)
            found = text.find("*/", index + 2)
            index = stop if found < 0 else min(found + 2, stop)
            chunk_from = index
            continue

        if char == "{" or char == "}":
            jinja = _jinja_span(text, index, stop)
            if jinja >= 0:
                take(index)
                index = jinja
                chunk_from = index
                continue

        if char in "\"'":
            index = _skip_string(text, index, stop)
            continue

        if char == "u" or char == "U":
            call = _URL_FUNCTION.match(text, index, stop)
            adjacent = text[index - 1] if index > start else ""
            if call and not _IDENT_CHARACTER.match(adjacent):
                index = _skip_url(text, call.end(), stop)
                continue

        if char == "{":
            take(index)
            name = _WHITESPACE.sub(" ", "".join(pieces)).strip()
            keyword = _AT_KEYWORD.match(name)
            stack.append(_Open(
                name=name,
                anchor=anchor if anchor >= 0 else index,
                keyframes=bool(
                    keyword
                    and keyword.group(1).lower() in _AT_RULES_WHOSE_CHILDREN_ARE_STEPS
                ),
                step=bool(stack) and stack[-1].keyframes,
            ))
            index += 1
            restart(index)
            continue

        if char == "}":
            if stack:
                _report(rows, stack.pop(), index, lines, prefix)
            index += 1
            restart(index)
            continue

        if char == ";":
            # at-rule בלי בלוק (``@import``, ``@charset``) אינה סימבול —
            # אין לה טווח. וההצהרות שבתוך בלוק אינן prelude של הבא.
            index += 1
            restart(index)
            continue

        index += 1

    # בלוקים שלא נסגרו עד הסוף מדווחים עד השורה האחרונה, כמו תגית שלא
    # נסגרה בסורק ה-HTML: זו התשובה הכנה, כי הם באמת לא נסגרו.
    while stack:
        _report(rows, stack.pop(), stop, lines, prefix)
    return rows


def _report(
    rows: list[dict[str, Any]],
    done: _Open,
    end_index: int,
    lines: Sequence[int],
    prefix: str,
) -> None:
    """מוסיף בלוק למפה, אם הוא בכלל סימבול.

    **צעד בתוך ``@keyframes`` אינו סימבול, ובלוק בלי שם אינו סימבול.**
    השני אינו קיים ב-CSS תקין (נמדד: אפס בקורפוס), אבל בקלט פגום הוא
    אפשרי — ושם לדווח אותו היה גרוע מלהשמיט: שם ריק אינו מזהה, הוא לא
    נמצא ב-``symbol=``, והוא תופס מקום בעמוד בלי לומר דבר.

    שני הארגומנטים הם **היסטים** ולא מספרי שורה, והגזירה נעשית כאן —
    כדי שיהיה מקום אחד שממנו מספר שורה יוצא אל המפה.
    """
    if done.step or not done.name:
        return
    rows.append({
        "name": f"{prefix}{done.name}",
        "start": line_at(lines, done.anchor),
        "end": line_at(lines, end_index),
    })


def _jinja_span(text: str, index: int, stop: int) -> int:
    """הסוף של מבנה Jinja שמתחיל כאן, או ``-1`` אם אין כזה.

    מחזיר את המיקום שאחרי הסוגר. מבנה שלא נסגר נבלע עד ``stop``, כמו כל
    קטע אחר שלא נסגר.
    """
    for opener, closer in _JINJA_OPENERS:
        if text.startswith(opener, index):
            found = text.find(closer, index + len(opener))
            return stop if found < 0 else min(found + len(closer), stop)
    return -1


def _skip_string(text: str, index: int, stop: int) -> int:
    """מדלג על מחרוזת מצוטטת, כולל ``\\`` שמחרג את הסוגר."""
    quote = text[index]
    index += 1
    while index < stop:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return stop


def _skip_url(text: str, index: int, stop: int) -> int:
    """מדלג על גוף ``url(…)``, בשתי הצורות.

    בצורה המצוטטת הסוגר הוא המרכאה ואחריה ``)``; בצורה הלא מצוטטת ``)``
    לבדו. שתיהן קיימות בקורפוס — 71 מצוטטות ו-28 לא — ולשתיהן זה משנה:
    ``url('data:image/svg+xml;utf8, <svg …>')`` מכיל ``;`` ומרכאות בתוך
    הערך, וגם ``<`` ו-``>``.
    """
    while index < stop and text[index].isspace():
        index += 1
    if index < stop and text[index] in "\"'":
        index = _skip_string(text, index, stop)
    found = text.find(")", index)
    return stop if found < 0 else min(found + 1, stop)

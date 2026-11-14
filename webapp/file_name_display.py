"""שם קובץ בשורה עברית, בעמודים שהשרת בונה — התאום של ``webapp/static/js/utils/file-name.js``.

ההסבר המלא — מה שבור, למה ``<bdi>``, מתי מפרקים, ולמה טבלאות ולא מאפיין הכתב של יוניקוד — כתוב פעם אחת, בראש הקובץ
ההוא. כאן רק מה שנוגע לצד השרת:

**למה גם בשרת.** עמוד שהשרת בונה (רשימת הקבצים, הכותרת של עמוד הקובץ, הדשבורד) מציג את השם לפני שה-JS רץ. בנייה
בשרת חוסכת את הקפיצה בטעינה, ולא תלויה בסקריפט בכלל.

**שני המימושים חייבים להחליט אותו דבר.** ``tests/test_file_name_display.py`` מריץ את ``parts`` של ה-JS האמיתי מול
:func:`file_name_parts` על רשימת שמות ועל כל תו ביוניקוד, ומשווה את ה-HTML ש-:func:`file_name_html` בונה למבנה
ש-``element`` בונה.

המודול הוא עלה: הוא אינו מייבא דבר מהוובאפ, ולכן אפשר לייבא אותו מכל מקום — כולל טסטים שמרנדרים תבניות בסביבת
Jinja משלהם (:data:`TEMPLATE_FILTERS`).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from typing import Any, Callable, NamedTuple

from markupsafe import Markup

#: אותיות הכתב העברי — אותה טבלה כמו ``HEBREW_LETTERS`` ב-``utils/file-name.js``.
HEBREW_LETTERS: tuple[tuple[int, int], ...] = (
    (0x05D0, 0x05EA), (0x05EF, 0x05F2), (0xFB1D, 0xFB1D), (0xFB1F, 0xFB28), (0xFB2A, 0xFB36), (0xFB38, 0xFB3C),
    (0xFB3E, 0xFB3E), (0xFB40, 0xFB41), (0xFB43, 0xFB44), (0xFB46, 0xFB4F),
)

#: אותיות הכתב הלטיני — אותה טבלה כמו ``LATIN_LETTERS`` ב-``utils/file-name.js``.
LATIN_LETTERS: tuple[tuple[int, int], ...] = (
    (0x0041, 0x005A), (0x0061, 0x007A), (0x00AA, 0x00AA), (0x00BA, 0x00BA), (0x00C0, 0x00D6), (0x00D8, 0x00F6),
    (0x00F8, 0x02B8), (0x02E0, 0x02E4), (0x1D00, 0x1D25), (0x1D2C, 0x1D5C), (0x1D62, 0x1D65), (0x1D6B, 0x1D77),
    (0x1D79, 0x1DBE), (0x1E00, 0x1EFF), (0x2071, 0x2071), (0x207F, 0x207F), (0x2090, 0x209C), (0x212A, 0x212B),
    (0x2132, 0x2132), (0x214E, 0x214E), (0x2183, 0x2184), (0x2C60, 0x2C7F), (0xA722, 0xA787), (0xA78B, 0xA7DC),
    (0xA7F1, 0xA7FF), (0xAB30, 0xAB5A), (0xAB5C, 0xAB64), (0xAB66, 0xAB69), (0xFB00, 0xFB06), (0xFF21, 0xFF3A),
    (0xFF41, 0xFF5A), (0x10780, 0x10785), (0x10787, 0x107B0), (0x107B2, 0x107BA), (0x1DF00, 0x1DF1E),
    (0x1DF25, 0x1DF2A),
)

#: כמו ``EXTENSION_RE`` ב-JS. ``\Z`` ולא ``$``: בפייתון ``$`` מתאים גם לפני ``\n`` אחרון, וב-JS (בלי הדגל ``m``) לא.
_EXTENSION_RE = re.compile(r"\.([A-Za-z0-9]{1,10})\Z")
_PATH_SEPARATOR_RE = re.compile(r"[/\\]")

_HEBREW_STARTS = tuple(start for start, _ in HEBREW_LETTERS)
_LATIN_STARTS = tuple(start for start, _ in LATIN_LETTERS)


class FileNameParts(NamedTuple):
    """השם והסיומת של שם שמפורק, כמו ``{stem, extension}`` ב-JS."""

    stem: str
    extension: str


def _in_ranges(ranges: tuple[tuple[int, int], ...], starts: tuple[int, ...], code_point: int) -> bool:
    index = bisect_right(starts, code_point) - 1
    return index >= 0 and code_point <= ranges[index][1]


def _as_text(name: Any) -> str:
    return "" if name is None else str(name)


def file_name_parts(name: Any) -> FileNameParts | None:
    """השם והסיומת של שם קובץ שהדפדפן היה מציג עם הסיומת באמצע, או ``None`` — ``parts`` ב-``utils/file-name.js``."""
    text = _as_text(name)
    if _PATH_SEPARATOR_RE.search(text):
        return None
    match = _EXTENSION_RE.search(text)
    if not match:
        return None
    stem = text[: match.start()]
    last_hebrew = -1
    for index in range(len(stem) - 1, -1, -1):
        if _in_ranges(HEBREW_LETTERS, _HEBREW_STARTS, ord(stem[index])):
            last_hebrew = index
            break
    if last_hebrew < 0:
        return None
    has_latin = False
    for char in stem[last_hebrew + 1:]:
        if char == ".":
            return None
        if _in_ranges(LATIN_LETTERS, _LATIN_STARTS, ord(char)):
            has_latin = True
    if not has_latin:
        return None
    return FileNameParts(stem, match.group(1))


def file_name_html(name: Any) -> Markup:
    """ה-``<bdi>`` של השם, כ-HTML מוכן לתבנית — אותו מבנה ש-``element`` ב-``utils/file-name.js`` בונה.

    ``Markup.format`` מקודד כל ערך שהוא מקבל (markupsafe 3.0.3: ``EscapeFormatter(self.escape)``), ולכן שם עם ``<``,
    ``&`` או מרכאות נכנס כטקסט. בין החלקים אין רווח, כדי שהטקסט יישאר השם תו בתו.
    """
    text = _as_text(name)
    split = file_name_parts(text)
    if split is None:
        return Markup('<bdi dir="auto">{}</bdi>').format(text)
    return Markup('<bdi dir="rtl">{}.<bdi>{}</bdi></bdi>').format(split.stem, split.extension)


#: הפילטרים שהמודול נותן לתבניות. ``webapp/app.py`` רושם אותם על האפליקציה, וטסט שמרנדר תבנית בסביבת Jinja משלו
#: מוסיף אותם משם — כך השם של הפילטר כתוב פעם אחת.
TEMPLATE_FILTERS: dict[str, Callable[[Any], Markup]] = {"file_name": file_name_html}

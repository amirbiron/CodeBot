"""Code chunking service for semantic search."""

from __future__ import annotations

import logging
import string
from dataclasses import dataclass, field
from typing import List, Optional

from config import config

logger = logging.getLogger(__name__)

# Configuration
CHUNK_SIZE = getattr(config, "CHUNK_SIZE_LINES", 220)
CHUNK_OVERLAP = getattr(config, "CHUNK_OVERLAP_LINES", 40)

# תקציב הבייטים הוא המגבלה האמיתית. חלון השורות נשאר תקרה שנייה בלבד.
#
# למה: ל-``gemini-embedding-001`` יש תקרת קלט של 2,048 טוקנים, והוא **חותך
# בשקט** כל מה שמעליה — בלי שגיאה, בלי אזהרה, עם וקטור שנראה תקין לגמרי.
# חיתוך לפי שורות בלבד אינו יודע כמה טקסט יצא: 220 שורות הן ~4,300 בייט
# ב-JSON עם מספר בכל שורה, ו-24,000 בייט במארקדאון עברי צפוף. בפרודקשן
# חצי מהצ'אנקים חצו את הסף, והווקטור שלהם תיאר רק את ההתחלה שלהם.
CHUNK_MAX_BYTES = int(getattr(config, "CHUNK_MAX_BYTES", 2000) or 2000)

# חפיפה כשיעור מהתקציב, כדי שהיא תישאר פרופורציונלית אם התקציב משתנה.
CHUNK_OVERLAP_RATIO = 0.15

# גרסת ה-chunker. כשהמספר הזה עולה, ``EmbeddingWorker`` מזהה שכל הקבצים
# נחתכו לפי כלל ישן ומעבד אותם מחדש מעצמו — בלי פקודת re-index ידנית.
# ראו ``database.manager.get_snippets_needing_processing``.
CHUNKER_VERSION = 2

# --- זיהוי צ'אנקים חסרי משמעות סמנטית ---
# קובץ ה-export של טבלת האמבדינגים עצמה חולק ל-88 צ'אנקים ונשלח לאמבדינג:
# 88 וקטורים שמתארים שורות של מספרים עשרוניים. וקטור כזה נוחת במקום שרירותי
# במרחב, לא קרוב לשום דבר בפרט, ולכן הוא יכול לצוץ כמעט בכל שאילתה.
#
# האות: יחס ספרות ופיסוק מתוך התווים **שאינם רווח**. רווחים אינם במונה בכוונה
# — קוד עתיר הזחה (פייתון, YAML מקונן, JSX) הוא 35%-45% רווח מטבעו, ולכן
# ספירתם הייתה פוסלת תוכן אמיתי.
#
# הסף כויל על כל 3,483 הצ'אנקים בפרודקשן: התוכן ה"מספרי" ביותר שאינו dump
# עוצר ב-0.556 (טבלאות מספרים במארקדאון), ומעל 0.6 יושבים רק ה-JSON dump
# ונתיבי SVG. 0.8 משאיר מרווח של 0.24 מהתוכן האמיתי הקרוב ביותר.
_LOW_INFORMATION_CHARS = frozenset(string.digits + string.punctuation)
LOW_INFORMATION_RATIO = 0.8

# מתחת לזה היחס חסר משמעות סטטיסטית: קובץ בן 12 בייט (``x = 1 + 2``) הוא
# 50% פיסוק וספרות בלי שיהיה בו שום דבר פגום.
LOW_INFORMATION_MIN_CHARS = 200

# תקרה למטא-דאטה שנוספת לכל צ'אנק (כותרת/תיאור/תגיות/שפה). בלעדיה טקסט
# שנשלח בפועל היה יכול לחרוג מהתקציב בגלל תיאור ארוך, אחרי שה-chunker כבר
# ספר בייטים בקפידה.
EMBEDDING_METADATA_MAX_BYTES = 500


@dataclass
class CodeChunk:
    """Represents a chunk of code."""

    index: int
    content: str
    start_line: int
    end_line: int

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class _Unit:
    """יחידת חיתוך אטומית — שורה, או חלק משורה שארוכה מהתקציב."""

    text: str
    line_no: int
    is_continuation: bool  # True = ממשיכה את השורה הקודמת, בלי newline לפניה
    # הגודל מחושב פעם אחת ביצירה ולא בכל גישה: הלולאה הראשית ניגשת ל-``size``
    # של אותה יחידה כמה פעמים (סריקה קדימה, ואז סריקת החפיפה אחורה), ו-property
    # שמקודד מחדש בכל פעם הפך את החיתוך ל-O(n·bytes) על קבצים גדולים.
    size: int = field(init=False)

    def __post_init__(self) -> None:
        self.size = len(self.text.encode("utf-8"))


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _split_oversized_line(line: str, line_no: int, budget: int) -> List[_Unit]:
    """חותך שורה שארוכה מהתקציב לחתיכות בגודל בטוח.

    זה המקרה של קובץ SVG או JS ממוזער: שורה אחת של 77KB. חיתוך לפי שורות
    לבדו לא היה מפצל אותה בכלל, והוקטור היה מכיר בערך 10% ממנה.
    החיתוך הוא לפי תווים, כי אין כאן גבול תחבירי להישען עליו.
    """
    data = line.encode("utf-8")
    if len(data) <= budget:
        return [_Unit(line, line_no, False)]

    units: List[_Unit] = []
    pos = 0
    total = len(data)
    while pos < total:
        end = min(pos + budget, total)
        # ``end`` חייב לנחות על תחילת תו ולא באמצע רצף UTF-8. בייט המשך
        # מזוהה לפי שני הביטים העליונים ``10``; נסוגים אחורה עד תחילת התו.
        while end > pos and end < total and (data[end] & 0xC0) == 0x80:
            end -= 1
        if end == pos:
            # תקציב קטן מתו בודד (אפשרי רק דרך ``max_bytes`` בטסטים): קדימה
            # עד סוף התו, כדי שהלולאה תתקדם ולא תיתקע.
            end = pos + 1
            while end < total and (data[end] & 0xC0) == 0x80:
                end += 1
        units.append(_Unit(data[pos:end].decode("utf-8"), line_no, bool(units)))
        pos = end
    return units


def _build_units(lines: List[str], budget: int) -> List[_Unit]:
    units: List[_Unit] = []
    for idx, line in enumerate(lines, start=1):
        if _byte_len(line) > budget:
            units.extend(_split_oversized_line(line, idx, budget))
        else:
            units.append(_Unit(line, idx, False))
    return units


def _join_units(units: List[_Unit]) -> str:
    parts: List[str] = []
    for pos, unit in enumerate(units):
        if pos and not unit.is_continuation:
            parts.append("\n")
        parts.append(unit.text)
    return "".join(parts)


def _separator_size(unit: _Unit, is_first: bool) -> int:
    return 0 if (is_first or unit.is_continuation) else 1


def split_code_to_chunks(
    code: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    *,
    max_bytes: Optional[int] = None,
) -> List[CodeChunk]:
    """Split code into overlapping chunks.

    Strategy:
    - כל צ'אנק מוגבל ב-``max_bytes`` בייטים (UTF-8) **וגם** ב-``chunk_size`` שורות
    - חפיפה בין צ'אנקים עוקבים שומרת הקשר, בשיעור מתקציב הבייטים
    - שורה ארוכה מהתקציב נחתכת לחתיכות; לכולן אותו מספר שורה
    - אין השמטת זנב: איחוד טווחי השורות מכסה את כל שורות הקובץ

    ``overlap`` הוא תקרה **שנייה** על החפיפה, במספר שורות: החפיפה בפועל היא
    המחמיר מבין תקציב הבייטים (15%), חצי מהצ'אנק בפועל, ו-``overlap`` שורות.
    ``overlap=0`` אכן מבטל את החפיפה לגמרי.
    """
    if not code or not code.strip():
        return []

    budget = int(max_bytes if max_bytes is not None else CHUNK_MAX_BYTES)
    if budget <= 0:
        budget = CHUNK_MAX_BYTES

    try:
        line_ceiling = int(chunk_size)
    except (TypeError, ValueError):
        line_ceiling = CHUNK_SIZE
    if line_ceiling <= 0:
        line_ceiling = CHUNK_SIZE

    overlap_budget = int(budget * CHUNK_OVERLAP_RATIO)

    try:
        overlap_lines = int(overlap)
    except (TypeError, ValueError):
        overlap_lines = CHUNK_OVERLAP
    overlap_lines = max(0, overlap_lines)

    lines = code.splitlines()
    if not lines:
        return []

    units = _build_units(lines, budget)
    total = len(units)

    chunks: List[CodeChunk] = []
    start = 0
    chunk_index = 0

    while start < total:
        end = start
        size = 0
        while end < total:
            unit = units[end]
            addition = unit.size + _separator_size(unit, end == start)
            lines_so_far = units[end].line_no - units[start].line_no
            if end > start and (size + addition > budget or lines_so_far >= line_ceiling):
                break
            size += addition
            end += 1

        # ``end > start`` תמיד: היחידה הראשונה נכנסת ללא תנאי, וכל יחידה
        # בפני עצמה כבר קטנה מהתקציב (שורות ארוכות פוצלו מראש).
        window = units[start:end]
        chunks.append(
            CodeChunk(
                index=chunk_index,
                content=_join_units(window),
                start_line=window[0].line_no,
                end_line=window[-1].line_no,
            )
        )
        chunk_index += 1

        if end >= total:
            break

        # החפיפה: כמה יחידות מהסוף של הצ'אנק הנוכחי נכנסות גם לבא אחריו.
        #
        # מגבלה ידועה ומקובלת: בקובץ **חד-שורתי** (SVG, JS ממוזער) כל יחידה
        # היא בדיוק בגודל התקציב, ולכן היא לעולם לא נכנסת ל-15% של החפיפה —
        # הצ'אנקים יוצאים ללא חפיפה כלל. זה מכוון: אין ערך סמנטי בהמשכיות בין
        # שני חצאים של נתיב SVG, וקבצים כאלה ממילא נעצרים ב-
        # ``is_low_information_chunk``. לפצל את היחידות קטן יותר רק כדי לייצר
        # חפיפה היה מקטין כל צ'אנק בקבצים האלה בלי תמורה.
        #
        # התקציב מוגבל גם לחצי מהצ'אנק בפועל, ולא רק ל-15% מתקציב הבייטים.
        # בלי הגבול הזה, כשתקרת השורות היא שבולמת (צ'אנק קטן בהרבה מהתקציב),
        # תקציב החפיפה גדול מהצ'אנק כולו — והחלון היה מתקדם שורה אחת בכל
        # סיבוב, כלומר O(n) צ'אנקים שכל אחד מהם כמעט זהה לקודמו.
        effective_overlap = min(overlap_budget, size // 2)
        next_start = end
        carried = 0
        last_line = units[end - 1].line_no
        while next_start - 1 > start:
            candidate = units[next_start - 1]
            candidate_size = candidate.size + 1
            if carried + candidate_size > effective_overlap:
                break
            # תקרת השורות של ``overlap``. יחידות של אותה שורה ארוכה נספרות
            # כשורה אחת, ולכן ``overlap=0`` עוצר כאן מיד.
            if last_line - candidate.line_no + 1 > overlap_lines:
                break
            carried += candidate_size
            next_start -= 1

        # ``next_start > start`` נשמר תמיד, אחרת הלולאה לא הייתה מתקדמת.
        start = max(next_start, start + 1)

    logger.debug("Split %s lines into %s chunks", len(lines), len(chunks))
    return chunks


def is_low_information_chunk(text: str) -> bool:
    """האם הצ'אנק הוא בעצם dump של מספרים, בלי משמעות סמנטית להצפין.

    מחזירה ``False`` לכל טקסט קצר: שם היחס רועש מדי מכדי להסתמך עליו.
    """
    if not text:
        return False
    non_whitespace = [ch for ch in text if not ch.isspace()]
    if len(non_whitespace) < LOW_INFORMATION_MIN_CHARS:
        return False
    hits = sum(1 for ch in non_whitespace if ch in _LOW_INFORMATION_CHARS)
    return (hits / len(non_whitespace)) >= LOW_INFORMATION_RATIO


def _truncate_to_bytes(text: str, max_bytes: int) -> str:
    """חותך ל-``max_bytes`` בלי לשבור תו UTF-8 באמצע."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def create_embedding_text(
    code_chunk: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    language: Optional[str] = None,
) -> str:
    """Build combined text for embedding.

    Combines metadata (title/description/tags) with code to enable cross-language search.

    המטא-דאטה נקצצת ל-``EMBEDDING_METADATA_MAX_BYTES``: בלי זה תיאור ארוך היה
    יכול להוציא את הטקסט מהתקציב שה-chunker חישב, ולהחזיר בדיוק את החיתוך
    השקט שהתקציב נועד למנוע.

    **התקרה האפקטיבית של הקלט אינה ``CHUNK_MAX_BYTES``.** המחרוזת המקסימלית
    כאן היא 500 (מטא-דאטה) + 8 (``\n\nCode:\n``) + 2,000 (צ'אנק) = **2,508
    בייט**, וזה המספר שצריך להשוות לתקרת ה-2,048 טוקנים של
    ``gemini-embedding-001``. זו החלטה מודעת ולא פספוס: התקציב נבחר 2,000
    דווקא כדי שהתוספת הקבועה הזו תישאר בתוך המרווח.

    מה שלא נמדד: כמה טוקנים 2,508 בייט הם בפועל. אין בריפו מונה טוקנים
    למודל הזה, ו-``countTokens`` דורש מפתח API. עבור ASCII זה ~2,508 תווים
    (בערך 600-700 טוקנים), ועבור עברית ~1,254 תווים. אם בכל זאת תהיה חריגה,
    ``EMBEDDING_AUTO_TRUNCATE=false`` הוא מה שהופך אותה משקטה לגלויה — ראו
    ``scripts/probe_embedding_limits.py``.
    """
    parts: List[str] = []

    if title:
        parts.append(f"Title: {title}")

    if description:
        parts.append(f"Description: {description}")

    if tags:
        parts.append(f"Tags: {', '.join(tags)}")

    if language:
        parts.append(f"Language: {language}")

    metadata = _truncate_to_bytes("\n".join(parts), EMBEDDING_METADATA_MAX_BYTES)

    if code_chunk:
        return f"{metadata}\n\nCode:\n{code_chunk}" if metadata else f"\nCode:\n{code_chunk}"

    return metadata

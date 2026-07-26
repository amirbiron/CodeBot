"""פארסר RST קליל וטהור — לחילוץ סקשנים לפי כותרות.

מודול עצמאי (בלי תלות ב-MCP) שנועד לשמש כלים שקוראים מקבצי RST של התיעוד:
``docs_get_section`` (עכשיו) ובעתיד ``docs_search`` / ``docs_lookup_config``.

עקרונות מנחים:
- היררכיית הכותרות ב-RST נקבעת **דינמית פר-קובץ** לפי סדר הופעת תווי ה-adornment
  (אין הנחה קשיחה ש-``=`` היא רמה 1). תמיכה ב-underline-only וב-overline+underline.
- כותרות מזוהות אך ורק ב-column 0. תוכן מוזח (list-table, note, code-block, literal blocks)
  שייך לסקשן שמעליו ואינו מפורסר פנימה — חיתוך לפי טווח שורות מטפל בזה נכון.
- שורת ``===``/``---`` בתוך literal block (אחרי ``::``) או ``.. code-block::`` אינה כותרת.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import List, Optional, Tuple

# תווי adornment חוקיים לכותרות RST (לא כולל אלפאנומרי/רווח)
_ADORNMENT_CHARS = set("=-`:.'\"~^_*+#<>!$%&()?@[\\]{|}/")

_DIRECTIVE_RE = re.compile(r"^\.\.[ \t]+\S")  # ".. something::" וכו'
_CODE_DIRECTIVE_RE = re.compile(r"^\.\.[ \t]+(code-block|code|sourcecode|parsed-literal)::")
_INCLUDE_RE = re.compile(r"^\.\.[ \t]+include::[ \t]*(\S.*)$")


@dataclass
class Section:
    """סקשן בודד בעץ הכותרות."""
    title: str
    level: int
    title_line: int          # 1-based — שורת הטקסט של הכותרת
    heading_line: int        # 1-based — שורת ה-overline (או == title_line אם אין overline)
    end_line: int            # 1-based inclusive — סוף התוכן (מחושב ב-_finalize)
    adornment: str
    over: bool = False
    parent: Optional[int] = None
    children: List[int] = field(default_factory=list)
    breadcrumb: List[str] = field(default_factory=list)


@dataclass
class Document:
    lines: List[str]
    sections: List[Section]
    includes: List[str] = field(default_factory=list)  # יעדי .. include:: (לא מורחבים)


def _is_indented(line: str) -> bool:
    return line[:1] in (" ", "\t")


def _adornment_char(line: str) -> Optional[str]:
    """מחזיר את תו ה-adornment אם השורה כולה תו-חזרה בודד (בלי הזחה), אחרת None."""
    if not line or _is_indented(line):
        return None
    s = line.rstrip()
    if len(s) < 2:  # לפחות 2 תווים — מונע false-positive על תו בודד
        return None
    ch = s[0]
    if ch not in _ADORNMENT_CHARS:
        return None
    return ch if all(c == ch for c in s) else None


def _is_title_text(line: str) -> bool:
    """שורה שיכולה להיות טקסט של כותרת: לא ריקה, לא מוזחת, לא adornment-only."""
    if not line or _is_indented(line):
        return False
    return _adornment_char(line) is None


def _opens_literal(stripped: str) -> bool:
    """שורה (לא מוזחת) שפותחת literal/code block שבו אין לזהות כותרות."""
    if _CODE_DIRECTIVE_RE.match(stripped):
        return True
    # paragraph המסתיים ב-'::' שאינו דירקטיבה (למשל 'Development::')
    return stripped.endswith("::") and not _DIRECTIVE_RE.match(stripped)


def parse_document(text: str) -> Document:
    """מפרסר טקסט RST לעץ סקשנים. עמיד ל-literal/code blocks ולדירקטיבות מוזחות."""
    lines = (text or "").split("\n")
    n = len(lines)
    sections: List[Section] = []
    includes: List[str] = []
    order: List[str] = []  # סדר הופעת תווי ה-adornment → קובע את הרמות

    def level_for(ch: str) -> int:
        if ch not in order:
            order.append(ch)
        return order.index(ch) + 1

    i = 0
    while i < n:
        raw = lines[i]
        if not _is_indented(raw):
            stripped = raw.rstrip()
            # .. include:: — נאסף בלי הרחבה
            m_inc = _INCLUDE_RE.match(stripped)
            if m_inc:
                includes.append(m_inc.group(1).strip())
                i += 1
                continue
            # literal/code block — דלג על הבלוק המוזח שאחרי השורה הפותחת
            if _opens_literal(stripped):
                i += 1
                while i < n and lines[i].strip() == "":
                    i += 1
                if i < n and _is_indented(lines[i]):
                    block_indent = len(lines[i]) - len(lines[i].lstrip())
                    while i < n:
                        ln = lines[i]
                        if ln.strip() == "":
                            i += 1
                            continue
                        if (len(ln) - len(ln.lstrip())) < block_indent:
                            break
                        i += 1
                continue

        # overline + underline (adornment / title / adornment זהה)
        over = _adornment_char(raw)
        if over is not None and i + 2 < n:
            title_line = lines[i + 1]
            under = _adornment_char(lines[i + 2])
            if _is_title_text(title_line) and under == over:
                lvl = level_for(over)
                sections.append(Section(
                    title=title_line.strip(), level=lvl,
                    title_line=i + 2, heading_line=i + 1, end_line=n,
                    adornment=over, over=True,
                ))
                i += 3
                continue

        # underline-only (title / adornment באורך >= הכותרת)
        if _is_title_text(raw) and i + 1 < n:
            under = _adornment_char(lines[i + 1])
            if under is not None and len(lines[i + 1].rstrip()) >= len(raw.rstrip()):
                lvl = level_for(under)
                sections.append(Section(
                    title=raw.strip(), level=lvl,
                    title_line=i + 1, heading_line=i + 1, end_line=n,
                    adornment=under, over=False,
                ))
                i += 2
                continue

        i += 1

    _finalize(sections, n)
    return Document(lines=lines, sections=sections, includes=includes)


def _finalize(sections: List[Section], total_lines: int) -> None:
    """מחשב end_line, parent/children, ו-breadcrumb לכל סקשן."""
    for idx, sec in enumerate(sections):
        end = total_lines
        for j in range(idx + 1, len(sections)):
            if sections[j].level <= sec.level:
                end = sections[j].heading_line - 1
                break
        sec.end_line = end

    stack: List[int] = []  # אינדקסים של אבות פתוחים
    for idx, sec in enumerate(sections):
        while stack and sections[stack[-1]].level >= sec.level:
            stack.pop()
        if stack:
            parent = stack[-1]
            sec.parent = parent
            sections[parent].children.append(idx)
            sec.breadcrumb = sections[parent].breadcrumb + [sec.title]
        else:
            sec.parent = None
            sec.breadcrumb = [sec.title]
        stack.append(idx)


def normalize_title(s: str) -> str:
    """נרמול סלחני להשוואת כותרות: רווחים, מקפים, ו-case לחלק האנגלי."""
    s = (s or "").strip()
    s = re.sub(r"[‐-―\-]", "-", s)  # מקף/מקף ארוך → מקף אחיד
    s = re.sub(r"\s+", " ", s)                # רווחים כפולים → יחיד
    return s.casefold()                       # case-insensitive (עברית לא מושפעת)


def find_sections(doc: Document, title: str) -> List[Section]:
    """כל הסקשנים שכותרתם תואמת (סלחני). ריק/יחיד/מרובה — המתקשר מחליט."""
    target = normalize_title(title)
    return [s for s in doc.sections if normalize_title(s.title) == target]


def section_bounds(doc: Document, sec: Section, include_subsections: bool) -> Tuple[int, int]:
    """טווח שורות (1-based inclusive) של תוכן הסקשן — עם או בלי תת-סקשנים."""
    start = sec.heading_line
    if include_subsections or not sec.children:
        return start, sec.end_line
    first_child = doc.sections[sec.children[0]]
    return start, first_child.heading_line - 1


def section_text(doc: Document, sec: Section, include_subsections: bool) -> str:
    start, end = section_bounds(doc, sec, include_subsections)
    return "\n".join(doc.lines[start - 1:end])


def direct_subsections(doc: Document, sec: Section) -> List[Section]:
    return [doc.sections[c] for c in sec.children]


def neighbors(doc: Document, sec: Section) -> Tuple[Optional[Section], Optional[Section]]:
    """הסקשן הקודם והבא באותה רמה תחת אותו אב (לניווט בלי TOC)."""
    siblings = ([doc.sections[c] for c in doc.sections[sec.parent].children]
                if sec.parent is not None
                else [s for s in doc.sections if s.parent is None])
    ids = [s.title_line for s in siblings]
    try:
        pos = ids.index(sec.title_line)
    except ValueError:
        return None, None
    prev = siblings[pos - 1] if pos > 0 else None
    nxt = siblings[pos + 1] if pos + 1 < len(siblings) else None
    return prev, nxt


def build_toc(doc: Document) -> List[dict]:
    """עץ כותרות: כותרת, רמה, טווח שורות, גודל משוער (bytes) — בלי תוכן."""
    toc = []
    for sec in doc.sections:
        approx = len("\n".join(doc.lines[sec.heading_line - 1:sec.end_line]).encode("utf-8"))
        toc.append({
            "title": sec.title,
            "level": sec.level,
            "breadcrumb": list(sec.breadcrumb),
            "line_range": [sec.heading_line, sec.end_line],
            "approx_bytes": approx,
        })
    return toc


def suggest(doc: Document, query: str, n: int = 5) -> List[str]:
    """כותרות קרובות לשאילתה שלא נמצאה (difflib), לשילוב ב-not-found."""
    titles = [s.title for s in doc.sections]
    norm_map = {normalize_title(t): t for t in titles}
    close = get_close_matches(normalize_title(query), list(norm_map.keys()), n=n, cutoff=0.5)
    # שמור על סדר ייחודי
    out, seen = [], set()
    for c in close:
        t = norm_map[c]
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

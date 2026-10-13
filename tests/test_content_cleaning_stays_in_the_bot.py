"""שומר מבני: ניקוי תוכן לא נכנס לשכבת השמירה, לוובאפ או ל-MCP.

עד ספטמבר 2026 ``Repository.save_code_snippet`` ועוד שתי פונקציות שמירה הריצו
``normalize_code`` על כל קובץ, מכל כניסה, ושכתבו תוכן של משתמשים בלי שאיש ידע.
הניקוי שייך רק לקוד שמודבק בבוט (``code_service.clean_pasted_code``). הטסט
נופל אם מודול כלשהו תחת ``database/``, ``webapp/`` או ``mcp_server/`` — או אחד
המודולים בשורש שפתקים עוברים בהם (``GUARDED_ROOT_MODULES``) — מייבא, קורא או
ניגש בשמו לאחת מפונקציות הניקוי — הנוכחית או אלה שנמחקו.

**ו-``unescape``, בכל צורה** (``html.unescape``, ``from html import unescape``):
עד אוקטובר 2026 פתקים עברו אותו בשמירה ובקריאה, בוובאפ וב-MCP, ו-``&amp;`` שמשתמש
הקליד נשמר כ-``&``. escape ופענוח שייכים לשלב ההצגה, בדפדפן, ולא לשכבות האלה.

**``decode_form_newlines`` מותר במכוון:** הוא לא מנקה תוכן אלא מבטל את ה-CRLF
ששליחת טופס HTML מוסיפה (``services/line_endings.py``).

הסריקה היא על ה-AST ולא על הטקסט, כדי שהערה שמזכירה את השם לא תפיל אותה.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
GUARDED_DIRS = ("database", "webapp", "mcp_server")

#: מודולים בשורש שמסלולי הכתיבה והקריאה של פתקים עוברים בהם, מהוובאפ ומה-MCP —
#: וגם שרשורי התגובות עליהם (``note_threads.py``), שגוף תגובה נשמר בהם כמו שנשלח.
GUARDED_ROOT_MODULES = (
    "sticky_notes_target.py", "sticky_notes_scope.py", "sticky_notes_tasks.py", "note_boards.py",
    "note_threads.py",
)

#: הפונקציה של היום, והשמות שנמחקו איתה — כדי שלא יחזרו בשם הישן. ``unescape`` הוא
#: מה שפתקים עברו עד אוקטובר 2026, ו-``_sanitize_note_text`` הפונקציה שהריצה אותו ב-MCP.
FORBIDDEN = frozenset({
    "clean_pasted_code", "normalize_code", "CodeNormalizer", "strip_hidden_escapes",
    "unescape", "_sanitize_note_text",
})


def _offences(source: str, filename: str) -> List[Tuple[int, str]]:
    """כל שימוש בשם אסור: ייבוא, שם, מאפיין (``code_service.clean_pasted_code``),
    או מחרוזת שהיא בדיוק השם (``getattr(mod, "normalize_code")``)."""
    found: List[Tuple[int, str]] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name.rsplit(".", 1)[-1] in FORBIDDEN:
                    found.append((node.lineno, alias.name))
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN:
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN:
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in FORBIDDEN:
            found.append((node.lineno, repr(node.value)))
    return found


def _guarded_files() -> Iterable[Path]:
    for directory in GUARDED_DIRS:
        yield from sorted((ROOT / directory).rglob("*.py"))
    for name in GUARDED_ROOT_MODULES:
        yield ROOT / name


def test_no_content_cleaning_in_the_save_layer_webapp_or_mcp():
    files = list(_guarded_files())
    assert any(p.parts[-2:] == ("database", "repository.py") for p in files), "הסריקה לא הגיעה ל-database/repository.py"
    assert all((ROOT / name).is_file() for name in GUARDED_ROOT_MODULES), "מודול שמור בשורש זז או נמחק"
    offences = [
        f"{path.relative_to(ROOT)}:{line}: {name}"
        for path in files
        for line, name in _offences(path.read_text(encoding="utf-8"), str(path))
    ]
    assert not offences, "ניקוי תוכן מחוץ לבוט:\n" + "\n".join(offences)


def test_the_scanner_catches_every_form_it_claims_to():
    """בלי זה, סורק שבור היה עובר על כל הריפו בירוק."""
    caught = [
        "from utils import normalize_code",
        "from services.code_service import clean_pasted_code as clean",
        "import src.domain.services.code_normalizer as cn\ncn.CodeNormalizer()",
        "code_service.clean_pasted_code(text, name)",
        "fn = getattr(utils, 'normalize_code')",
        "from src.domain.services.code_normalizer import strip_hidden_escapes",
        "import html\ntext = html.unescape(text)",
        "from html import unescape",
        "from html import unescape as decode",
    ]
    for snippet in caught:
        assert _offences(snippet, "<snippet>"), snippet


def test_decoding_a_form_and_mentioning_the_name_in_a_comment_are_allowed():
    allowed = (
        "from services.line_endings import decode_form_newlines\n"
        "code = decode_form_newlines(request.form.get('code') or '')\n"
        "# normalize_code used to run here; clean_pasted_code is for the bot only\n"
    )
    assert _offences(allowed, "<snippet>") == []

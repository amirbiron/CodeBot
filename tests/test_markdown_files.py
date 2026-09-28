"""‏``services/markdown_files.py`` — מה נחשב קובץ Markdown שמור, בכלל אחד לוובאפ ול-MCP.

הטבלה כאן היא **החוזה**, ולא מדגם: כל שורה היא מקרה שבו כלל שני, שנכתב ביד,
היה יכול לחלוק על הראשון. היא רצה פעמיים — מול הפונקציה המשותפת, ומול הצרכן
בוובאפ (``_is_markdown_file``) — כדי שהוובאפ לא יוכל לחזור להחזיק עותק משלו
בלי שהטבלה תשים לב.
"""

import re
from pathlib import Path

import pytest

from services.markdown_files import (
    MARKDOWN_FILE_SUFFIXES,
    MARKDOWN_LANGUAGES,
    is_markdown_file,
)

_REPO = Path(__file__).resolve().parents[1]

_CASES = [
    # (שפה, שם קובץ, מצופה, למה)
    ("markdown", "notes.md", True, "שני השדות מסכימים"),
    ("markdown", "notes.py", True, "שפת markdown בלי .md — מספיקה השפה"),
    ("md", "notes", True, "md הוא שם שפה בכלל של הוובאפ"),
    ("Markdown", "notes", True, "השפה בלי תלות ברישיות"),
    ("python", "README.md", True, ".md עם שפה אחרת — מספיקה הסיומת"),
    ("text", "guide.markdown", True, "הסיומת הארוכה"),
    (None, "README.MD", True, "הסיומת בלי תלות ברישיות"),
    ("python", "main.py", False, "אף אחד מהשניים"),
    ("python", "notes.amd", False, "הנקודה היא חלק מהסיומת — amd אינו md"),
    ("python", "notes.md.txt", False, "רק הסיומת האחרונה נחשבת"),
    ("python", "notes.mdx", False, ".mdx אינו בכלל (עדיין)"),
    (" markdown", "notes", False, "אין קיצוץ רווחים — הכלל של הוובאפ מעולם לא קיצץ"),
    ("", "", False, "שני שדות ריקים"),
    (None, None, False, "שני שדות חסרים"),
    (5, None, False, "שפה שאינה מחרוזת אינה מפילה ואינה מעידה"),
    (None, ["x.md"], False, "שם שאינו מחרוזת אינו מפיל ואינו מעיד"),
]


@pytest.mark.parametrize(("language", "file_name", "expected", "why"), _CASES)
def test_the_rule(language, file_name, expected, why):
    assert is_markdown_file(language, file_name) is expected, why


@pytest.mark.parametrize(("language", "file_name", "expected", "why"), _CASES)
def test_the_webapp_decides_by_the_same_rule(language, file_name, expected, why):
    """הצרכן בוובאפ מחזיר בדיוק את מה שהכלל מחזיר, על כל שורה בטבלה.

    מוטציה שמפילה: להחזיר ל-``_is_markdown_file`` ב-``webapp/app.py`` את הגוף
    הישן שלו — ``(language or '').lower()`` — ואז השורה עם השפה ``5`` נופלת
    ב-``AttributeError`` במקום להחזיר ``False``.
    """
    from webapp.app import _is_markdown_file

    assert _is_markdown_file(language, file_name) is expected, why


def test_the_webapp_holds_no_second_copy_of_the_lists():
    """הרשימות עצמן אינן מוקלדות שוב בוובאפ.

    עד המודול המשותף, ``webapp/app.py`` החזיק את הכלל במקום אחד ועוד שני
    עותקים מוטבעים במסלולי השמירה (איסוף התמונות של Markdown), ורשימת
    הסיומות גם בשמירת קובץ משותף. כולם עוברים עכשיו דרך המודול — והטסט הזה
    הוא מה שיתפוס עותק חמישי, כי עותק כזה לא היה מפיל אף טסט התנהגות:
    ביום שלו הוא נכון.
    """
    source = (_REPO / "webapp" / "app.py").read_text(encoding="utf-8")
    suffix_lists = re.findall(r"""['"]\.md['"]\s*,\s*['"]\.markdown['"]""", source)
    language_lists = re.findall(r"""['"]markdown['"]\s*,\s*['"]md['"]""", source)
    assert suffix_lists == [], suffix_lists
    assert language_lists == [], language_lists
    assert "from services.markdown_files import" in source


def test_the_lists_are_the_ones_the_docs_state():
    """‏``docs/mcp-server.rst`` נוקב בשני השדות, ולכן הערכים מעוגנים כאן.

    שינוי מכוון של הכלל (``.mdx``, למשל) נוגע בשלושה מקומות בכוונה: המודול,
    הטסט הזה והתיעוד — כי הוא משנה גם מה הוובאפ מציג וגם אילו קבצים סוכן
    יכול לקרוא לפי סעיף.
    """
    assert MARKDOWN_LANGUAGES == frozenset({"markdown", "md"})
    assert MARKDOWN_FILE_SUFFIXES == (".md", ".markdown")

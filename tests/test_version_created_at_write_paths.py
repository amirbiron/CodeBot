"""כל מסמך גרסה שהוובאפ כותב נושא את זמן הכתיבה שלו.

**למה בדיקה על צורת הקוד ולא על ההתנהגות.** ``code_snippets`` נכתב משבעה
מקומות שונים: ``save_code_snippet`` בשכבת ה-DB, וששה ראוטים בוובאפ שכותבים
לאוסף **ישירות** בחיבור מונגו משלהם. אותו פיצול כבר עלה פעמיים — בתיקון
``created_at`` נדרשו שבעה ראוטים, ובתיקון ``updated_at`` התברר שהתיקון
בשכבת ה-DB לא הגיע לוובאפ בכלל. הסיכון אינו בקוד שקיים היום אלא במסלול
**הבא** שייכתב: הוא ייראה כמו שכניו, יעבור ריוויו, ויפיל שורת היסטוריה
אחת בשקט.

בדיקה התנהגותית לכל ראוט דורשת מונגו אמיתי ומדלגת בלעדיו, כלומר בדיוק
בסביבה שבה השגיאה נכנסת. הבדיקה כאן רצה תמיד, קוראת את הקוד עצמו, ונופלת
על מסמך גרסה חדש שנולד בלי החותמת.

ההתנהגות של מסלול ה-DB נבדקת ב-``tests/test_version_created_at.py``; שם
השדה אינו חלק ממילון ספרותי אלא נוסף אחרי ``asdict``, ולכן הוא אינו נסרק כאן.
"""

import ast
import io
from pathlib import Path
from typing import List, Tuple

import pytest

from file_dates import VERSION_CREATED_AT_FIELD

REPO_ROOT = Path(__file__).resolve().parents[1]

#: הקבצים שכותבים מסמכי גרסה ישירות לאוסף, בלי לעבור דרך ה-repository.
SCANNED = ("webapp/app.py", "webapp/collections_api.py")

#: מה מזהה מילון ספרותי כ**מסמך גרסה** ולא כשאילתה או כמסמך אחר. ``code``
#: ו-``version`` יחד הם מה שמפריד אותו מפילטר (שיש בו ``user_id`` ו-
#: ``file_name`` אבל לא תוכן) ומקובץ גדול (שנושא ``content`` ובלי ``version``).
VERSION_DOC_KEYS = {"user_id", "file_name", "code", "version", "updated_at"}


def _string_keys(node: ast.Dict) -> set:
    return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _carries_the_stamp(node: ast.Dict) -> bool:
    for key in node.keys:
        if isinstance(key, ast.Name) and key.id == "VERSION_CREATED_AT_FIELD":
            return True
        if isinstance(key, ast.Constant) and key.value == VERSION_CREATED_AT_FIELD:
            return True
    return False


def _version_doc_literals(path: Path) -> List[Tuple[ast.Dict, int]]:
    tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and VERSION_DOC_KEYS <= _string_keys(node):
            found.append((node, node.lineno))
    return found


@pytest.mark.parametrize("relative", SCANNED)
def test_every_version_document_literal_carries_the_write_time(relative):
    path = REPO_ROOT / relative
    literals = _version_doc_literals(path)

    assert literals, f"לא נמצא אף מסמך גרסה ב-{relative} — הזיהוי בטח נשבר"

    missing = [line for node, line in literals if not _carries_the_stamp(node)]
    assert not missing, (
        f"{relative}: מסמכי גרסה בלי {VERSION_CREATED_AT_FIELD} בשורות {missing}. "
        "כל מסלול שיוצר גרסה חייב לחתום מתי השורה נכתבה — ראו file_dates.version_created_at."
    )


def test_the_scan_actually_finds_the_known_paths():
    """שומר על הבדיקה עצמה: זיהוי ששבר יעבור בשקט ולא יבדוק כלום."""
    counts = {rel: len(_version_doc_literals(REPO_ROOT / rel)) for rel in SCANNED}
    assert counts["webapp/app.py"] >= 5, counts
    assert counts["webapp/collections_api.py"] >= 1, counts

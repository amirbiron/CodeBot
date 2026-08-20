"""אוכף שהמתכון של ``safe_rmtree`` בתיעוד בודק גבול נתיב ולא קידומת מחרוזת.

הבאג: ``str(p).startswith(str(base))`` מאשר גם נתיב-אח. עבור
``allow_under=/tmp/app-test`` המחרוזת ``/tmp/app-test-evil`` עוברת את
הבדיקה, כי היא באמת מתחילה באותם תווים — ואז ``shutil.rmtree`` מוחק
תיקייה שלמה שמחוץ ל-allowlist.

זה מתכון שהמדיניות מורה להעתיק (``CLAUDE.md``, ``docs/testing.rst``,
``docs/quickstart-ai.rst``, ``docs/ai-guidelines.rst``), ולכן נוסח שגוי
מתפשט לכל מקום שמישהו מדביק אותו. המימושים שרצים בפועל בריפו כבר
בודקים נכון — הם מוסיפים ``os.sep`` — והבדיקה כאן שומרת על התיעוד.

הבדיקה הנכונה היא ``p == base or base in p.parents``: היא עובדת על
רכיבי נתיב ולא על תווים, ולכן ``/tmp/app-test-evil`` פשוט אינו תחת
``/tmp/app-test``.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

# הקבצים שמכילים את המתכון להעתקה
RECIPE_FILES = [
    "CLAUDE.md",
    "docs/testing.rst",
    "docs/quickstart-ai.rst",
    "docs/ai-guidelines.rst",
    "FEATURE_SUGGESTIONS/DOCUMENTATION_NEEDS.md",
]

# ``startswith`` על ``str(base)`` בלי מפריד אחריו — זה הדפוס השבור.
# ``str(base) + os.sep`` או ``str(base) + "/"`` תקינים ואינם נתפסים כאן.
_BAD = re.compile(r"startswith\(\s*str\(\s*(?:base|rp_base|b)\s*\)\s*\)")


def test_recipe_files_do_not_teach_prefix_matching():
    """אף קובץ מדיניות אינו מציג בדיקת קידומת ללא גבול נתיב."""
    offenders = []
    for rel in RECIPE_FILES:
        p = ROOT / rel
        if not p.is_file():
            continue
        for num, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
            if _BAD.search(line):
                offenders.append(f"{rel}:{num}: {line.strip()}")
    assert not offenders, (
        "בדיקת קידומת מחרוזת במקום גבול נתיב — נתיב-אח יעבור:\n  "
        + "\n  ".join(offenders)
    )


def test_recipe_files_show_the_parents_check():
    """המתכון מופיע בפועל, כדי שהבדיקה לא תעבור על קובץ ריק."""
    found = [
        rel for rel in RECIPE_FILES
        if (ROOT / rel).is_file()
        and "base in p.parents" in (ROOT / rel).read_text(encoding="utf-8")
    ]
    assert len(found) >= 4, f"המתכון המתוקן נמצא רק ב-{found}"


def test_the_documented_check_rejects_a_sibling_path(tmp_path):
    """הרצה של הבדיקה עצמה: נתיב-אח נדחה, תת-תיקייה מאושרת.

    בלי המקרה הזה הבדיקות שמעליה הן בדיקות טקסט בלבד — הן היו עוברות
    גם על נוסחה שגויה אחרת שאינה תואמת את הרג'קס.
    """
    base = tmp_path / "app-test"
    sibling = tmp_path / "app-test-evil"
    base.mkdir()
    sibling.mkdir()

    def allowed(path: Path, allow_under: Path) -> bool:
        p = path.resolve()
        b = allow_under.resolve()
        return p == b or b in p.parents

    assert allowed(base / "sub", base), "תת-תיקייה חוקית נדחתה"
    assert allowed(base, base), "ה-base עצמו נדחה"
    assert not allowed(sibling, base), "נתיב-אח אושר — זה בדיוק הבאג"
    assert not allowed(Path("/etc"), base), "נתיב חיצוני אושר"

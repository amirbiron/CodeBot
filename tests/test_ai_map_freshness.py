"""אוכף ש-``AI-MAP.md`` המקומט תואם את התיעוד שבריפו.

המפה היא תוצר נגזר: ``scripts/generate_ai_map.py`` בונה אותה מה-toctree
של Sphinx ומהפסקה הראשונה של כל עמוד. תוצר נגזר שמתעדכן בנפרד מהמקור
שלו נשאר מאחור בשקט — סוכן שקורא אותו מקבל מפה של מצב קודם ואין לו שום
דרך לדעת.

למה בדיקה ולא אוטומציה שכותבת: ``main`` מוגן, וכל ניסיון לתת לאוטומציה
לכתוב אליו נתקל באותו קיר בצורה אחרת (git push, PR fallback, PAT,
Contents API). הבדיקה הזו מבטלת את הצורך — מי שערך את התיעוד מרענן את
המפה באותו PR, וה-CI מסרב למיזוג בלי זה. אין טוקן, אין הרשאת כתיבה,
אין מרוץ מול עדכון מקביל.

היקף: הבדיקה רצה גם על ``pull_request`` וגם על ``push`` ל-main
(``.github/workflows/ci.yml`` מפעילה את ``unit-tests`` על שניהם, בלי
מסנן ``paths``), כך שגם עריכה ישירה של ``docs/`` מממשק הווב — שעוקפת
PR לגמרי — מסמנת את הקומיט ב-X אדום במקום להשאיר מפה ישנה בשקט.
"""

import difflib
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / "scripts" / "generate_ai_map.py"
MAP = ROOT / "AI-MAP.md"

# הפקודה שמרעננת. מופיעה גם בהודעת הכשל — מי שנתקל בה צריך לדעת מה
# להריץ בלי לחפש, כי בדרך כלל הוא לא זה שכתב את הבדיקה.
REFRESH_CMD = "python3 scripts/generate_ai_map.py --out AI-MAP.md"


def _run(*args: str) -> subprocess.CompletedProcess:
    """מריץ את המחולל כתהליך נפרד, בדיוק כמו הצרכן.

    לא ``import build_map``: הבדיקה אמורה לאמת את מה שאדם או CI מריצים
    בפועל, כולל פענוח הדגלים וקוד היציאה. ייבוא ישיר היה עוקף את ה-CLI
    ומשאיר את המסלול האמיתי לא בדוק.
    """
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_generator_exists() -> None:
    """בלי המחולל אין למפה מקור אמת, ושאר הבדיקות כאן חסרות משמעות."""
    assert GENERATOR.is_file(), f"המחולל חסר: {GENERATOR.relative_to(ROOT)}"


def test_map_is_committed() -> None:
    """המפה חייבת להיות בריפו — הצרכן שלה קורא את עץ הקבצים, לא רשת."""
    assert MAP.is_file(), (
        f"AI-MAP.md חסר בשורש הריפו. ליצירה: {REFRESH_CMD}"
    )


def test_map_matches_the_current_docs() -> None:
    """המפה המקומטת זהה בייט-בבייט למה שהמחולל יוצר מהתיעוד הנוכחי."""
    check = _run("--check", "AI-MAP.md")
    if check.returncode == 0:
        return

    # רק במסלול הכשל: מייצרים את המפה הטרייה ל-stdout (בלי --out, כדי
    # לא לכתוב כלום מתוך בדיקה) ומראים את ההפרש. בלי זה הודעת הכשל היא
    # "לא תואם" בלבד, ומי שקורא אותה לא יודע מה זז.
    fresh = _run()
    assert fresh.returncode == 0, (
        "המחולל עצמו נכשל, ולכן אי אפשר להשוות:\n"
        f"{fresh.stderr.strip() or fresh.stdout.strip()}"
    )

    current = MAP.read_text(encoding="utf-8") if MAP.exists() else ""
    diff = "\n".join(
        list(
            difflib.unified_diff(
                current.splitlines(),
                fresh.stdout.splitlines(),
                fromfile="AI-MAP.md (מקומט)",
                tofile="AI-MAP.md (מהתיעוד הנוכחי)",
                lineterm="",
            )
        )[:60]
    )
    raise AssertionError(
        "AI-MAP.md אינו תואם את התיעוד. שינית עמוד תיעוד בלי לרענן את "
        f"המפה — הרץ וקמט באותו PR:\n\n    {REFRESH_CMD}\n\n{diff}"
    )

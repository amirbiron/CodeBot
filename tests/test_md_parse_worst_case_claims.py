"""הטענות שנגזרות מ-``WORST_CASE_CPU_SECONDS`` — נבדקות כאן, ולא רק נכתבות (#3391).

``services/md_parser.py`` מגדיר את זמן המעבד של הפרסור הגרוע ביותר שנמדד תחת תקרות
ה-Markdown (``MAX_LINES`` ו-``MAX_TOKENS``). שני מספרים בשירות נשענים עליו, ולכל אחד
טענה אחת שאפשר לבדוק:

- ``DEFAULT_RATE_LIMIT_PER_MINUTE`` (``mcp_server/limits.py``): זהות אחת אינה עוברת
  דקת מעבד אחת בדקה, גם כשכל הקריאות שלה הן הקלט הגרוע.
- ``DEADLINE_SECONDS`` (``mcp_server/read_batch.py``): באץ' עונה בתוך הזמן שהלקוח
  ממתין, גם כשהפריט האחרון שהתחיל הוא הקלט הגרוע, ובעומס מלא על מאגר הקריאות.

עד #3391 שתי הטענות נשענו על מדידה אחת שהוקלדה בכמה מקומות, והיא התיישנה: הקלט הגרוע
של אז לא היה חסום בכלל. כאן כל אחת נגזרת מהקבועים, והחשבון שהתיעוד מציג
(``docs/mcp-server.rst``) נבדק מול אותם קבועים — כך ששינוי במדידה, במגבלה, בדדליין או
ברוחב המאגר בלי לעדכן את השאר מפיל את הקובץ הזה.

**מה שאינו בקוד, ולכן כתוב כאן פעם אחת עם המקור שלו:** מכסת המעבד ומגבלת הזיכרון של
הפריסה (השירות קורא אותן מ-cgroup בזמן ריצה), והזמן שהלקוח ממתין (הלקוח קובע אותו).
"""

from pathlib import Path

from mcp_server import limits, read_batch
from mcp_server.server import _read_pool_size
from services import md_parser

_REPO = Path(__file__).resolve().parents[1]

#: מכסת המעבד של השירות בייצור, במעבדים: ``cpu quota cgroup v2: 0.50 cpu`` בשורת
#: הקיבולת (מתועד ב"מודל הריצה" ב-``docs/mcp-server.rst``). השירות קורא אותה מ-cgroup
#: ב-``_cpu_budget`` ואינו מקבע אותה, ולכן היא מוקלדת רק כאן.
_PRODUCTION_CPUS = 0.5

#: מגבלת הזיכרון של הפריסה (512MiB) — מה ש-``_read_pool_size`` מקבל בייצור, ומה ש-
#: ``tests/test_mcp_to_thread.py::test_the_pool_is_sized_from_the_memory_budget`` מעביר לו.
_PRODUCTION_MEMORY_BYTES = 512 * 1024 * 1024

#: הזמן שהלקוח ממתין לבית הראשון של התשובה: הטיימר של 60 שניות של Claude Code על
#: קריאת כלי לשרת HTTP (``code.claude.com/docs/en/mcp.md``, נקרא ב-2026-09-23; הנימוק
#: המלא ב-docstring של ``DEADLINE_SECONDS``).
_CLIENT_SECONDS = 60

_SECONDS_PER_MINUTE = 60


def _wall_seconds_of_the_worst_parse() -> float:
    """כמה שניות קיר עולה הפרסור הגרוע כשכל חוטי מאגר הקריאות חולקים את המכסה.

    תחת ה-GIL החוטים אינם מוסיפים מעבד, ולכן כל אחד מקבל ``מכסה ÷ חוטים`` —
    והפרסור מתארך פי ``חוטים ÷ מכסה``: עשרה חוטים על חצי מעבד הם פי עשרים.
    """
    workers = _read_pool_size(_PRODUCTION_MEMORY_BYTES).workers
    return md_parser.WORST_CASE_CPU_SECONDS * workers / _PRODUCTION_CPUS


def test_one_identity_cannot_spend_more_cpu_than_the_service_has():
    """``DEFAULT_RATE_LIMIT_PER_MINUTE × WORST_CASE_CPU_SECONDS`` לא עובר את שניות-המעבד בדקה.

    זו הטענה שבגללה המגבלה ירדה מ-60 ל-45: עם 60, זהות אחת שכל קריאותיה הן הקלט
    הגרוע הייתה עוברת את המכסה — טענה שצריך להסביר במקום לבדוק.
    """
    spent = limits.DEFAULT_RATE_LIMIT_PER_MINUTE * md_parser.WORST_CASE_CPU_SECONDS
    available = _PRODUCTION_CPUS * _SECONDS_PER_MINUTE
    assert spent <= available, (
        f"{limits.DEFAULT_RATE_LIMIT_PER_MINUTE} קריאות × {md_parser.WORST_CASE_CPU_SECONDS} שניות "
        f"= {spent:.1f} שניות-מעבד בדקה, מעל {available:g}"
    )


def test_a_batch_whose_last_item_is_the_worst_parse_still_answers_in_time():
    """הדדליין נבדק בין פריטים, ולכן הפריט שהתחיל לפניו רץ עד סופו — וגם אז יש זמן.

    ``DEADLINE_SECONDS`` ועוד הפרסור הגרוע בזמן קיר, תחת עומס מלא על המאגר, קטנים
    מהזמן שהלקוח ממתין.
    """
    total = read_batch.DEADLINE_SECONDS + _wall_seconds_of_the_worst_parse()
    assert total < _CLIENT_SECONDS, f"{total:g} שניות, והלקוח ממתין {_CLIENT_SECONDS}"


def test_a_full_batch_fits_inside_the_default_rate_limit():
    """באץ' נשקל כמספר הפריטים שלו, ולכן תקרת הכלי חייבת להיכנס במגבלה לדקה.

    אחרת באץ' מלא היה נדחה תמיד ב-``rate_limited``. המגבלה ירדה ב-#3391, וזו הטענה
    ב-docstring של ``MAX_BATCH_ITEMS`` שהירידה הייתה יכולה לשבור.
    """
    assert read_batch.MAX_BATCH_ITEMS <= limits.DEFAULT_RATE_LIMIT_PER_MINUTE


def test_the_limits_table_carries_the_values_the_code_enforces():
    """טבלת ``mcp-limits`` ב-``docs/mcp-server.rst``: ארבעת הקבועים ש-#3391 הוסיף או שינה.

    הערך בכל שורה מחושב כאן מהקבוע, באותה צורה שהטבלה כותבת (פסיקים באלפים),
    ולא מוקלד לצידו — כמו בטסט המקביל של ``codekeeper_read_batch``.
    """
    lines = (_REPO / "docs" / "mcp-server.rst").read_text(encoding="utf-8").splitlines()

    def table_value(name: str) -> str:
        row = lines.index(f"   * - ``{name}``")
        cell = lines[row + 1].strip()
        assert cell.startswith("- "), f"השורה של {name} בטבלה אינה בצורה שהטסט קורא"
        return cell[2:]

    assert table_value("MAX_LINES") == f"{md_parser.MAX_LINES:,}"
    assert table_value("MAX_TOKENS") == f"{md_parser.MAX_TOKENS:,}"
    assert table_value("WORST_CASE_CPU_SECONDS") == f"{md_parser.WORST_CASE_CPU_SECONDS:g}"
    rate = limits.DEFAULT_RATE_LIMIT_PER_MINUTE
    assert table_value("DEFAULT_RATE_LIMIT_PER_MINUTE") == f"{rate:,}"


def test_the_documented_arithmetic_is_the_constants_arithmetic():
    """``docs/mcp-server.rst`` מציג את שני החשבונות במספרים — והם מחושבים כאן מהקבועים.

    קובץ RST אינו יכול לגזור דבר (``prose-restates-code-fact``), ולכן המחרוזת המצופה
    **מחושבת**: מי שמשנה את המדידה, את המגבלה, את הדדליין או את רוחב המאגר בלי
    לעדכן את החשבון בתיעוד מפיל את הטסט, וכך גם מי שמשנה את התיעוד בלי הקוד.
    """
    page = (_REPO / "docs" / "mcp-server.rst").read_text(encoding="utf-8")
    rate = limits.DEFAULT_RATE_LIMIT_PER_MINUTE
    # הגרוע-לקריאה אינו הפרסור לבדו: מסלול ה-not-found מוסיף suggest חסום, ולכן החשבון
    # הוא ``rate × (WORST_CASE_CPU_SECONDS × _NOT_FOUND_CPU_FACTOR)`` — שני הקבועים, לא
    # מספר מוקלד. עיגול לשתי ספרות כמו בתיעוד (WARN-001).
    worst_call = round(md_parser.WORST_CASE_CPU_SECONDS * limits._NOT_FOUND_CPU_FACTOR, 2)
    available = _PRODUCTION_CPUS * _SECONDS_PER_MINUTE
    rate_line = f"**{rate} × {worst_call:g} = {rate * worst_call:g} שניות-מעבד בדקה, מתוך {available:g}**"
    assert rate_line in page, f"החשבון של מגבלת הקצב אינו בתיעוד בצורה: {rate_line}"

    deadline = read_batch.DEADLINE_SECONDS
    wall = _wall_seconds_of_the_worst_parse()
    deadline_line = f"**{deadline:g} + {wall:g} = {deadline + wall:g}, מתחת ל-{_CLIENT_SECONDS}**"
    assert deadline_line in page, f"החשבון של הדדליין אינו בתיעוד בצורה: {deadline_line}"

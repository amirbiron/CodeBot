"""אוכף שהצהרות התקציר אינן מכילות ספירות או הבטחות יכולת.

הרקע: שלושה סבבי ריוויו רצופים נפלו על אותו דבר — לא על פירסור, אלא על
**טענות שנכתבו בלי לאמת מול הקוד**. תקציר אמר "שבעה מסלולי API" כשהיו
תשעה; תקציר אחר אמר "דוגמאות מוכנות להרצה" כשהקוד בעמוד מכיל ``...``
ופונקציה שאינה מוגדרת; שלישי הציג ``SearchType.SEMANTIC`` כנתמך, בעוד
``AdvancedSearchEngine.search`` נופל עבורו ל-``_text_search``.

ספירה מתיישנת בשקט, והבטחת יכולת דורשת קריאה בקוד. תקציר אמור לתאר מה
יש בעמוד — לא כמה, ולא מה עובד. הבדיקה הזו הופכת שיפוט חוזר לכלל מכני.

מה הבדיקה הזו **אינה** תופסת, ובכוונה — כדי שלא תיקרא כאישור גורף:

* ספירה במילים שאינן ברשימה: "אחד", "אחת", "כמה", "מספר", "עשרות". הן
  נפוצות מדי בפרוזה תקינה ("כל אחד", "פעם אחת", "מספר גרסה") מכדי לסנן
  אותן בלי להפיל תקצירים נכונים.
* ספירה בספרות שאינה מלווה במילה עברית: "3 endpoints".
* טענה עובדתית שאינה ספירה ואינה הבטחת הרצה — "נתמך", "אוטומטי",
  "בזמן אמת". אלה נשארים לריוויו אנושי.

הבדיקה היא רשת לצורה שכבר נפלה כאן שלוש פעמים, לא הוכחה שהתקציר נכון.
"""

import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# מילות ספירה, כמילה שלמה — כולל צורת נסמך ("שלושת ה-Endpoints")
_COUNT_WORDS = (
    "שניים", "שתיים", "שני", "שתי",
    "שלושה", "שלוש", "שלושת", "ארבעה", "ארבע", "ארבעת",
    "חמישה", "חמש", "חמשת", "שישה", "שש", "ששת",
    "שבעה", "שבע", "שבעת", "שמונה", "שמונת",
    "תשעה", "תשע", "תשעת", "עשרה", "עשר", "עשרת",
    "עשרים", "שלושים", "ארבעים", "חמישים",
    "שישים", "שבעים", "שמונים", "תשעים", "מאה", "אלף",
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "dozen",
)
_COUNT_RE = re.compile(r"(?<![\w֐-׿])(?:" + "|".join(_COUNT_WORDS) + r")(?![\w֐-׿])")

# ספירה בספרות: מספר שלם ואחריו מילה עברית — "28 אייקונים".
# מה שמוחרג, ולמה, לפי מה שבאמת מופיע היום בתקצירים:
#   * ספרה שדבוקה לאותיות — ``p95``, ``V2``, ``H3``, ``200ms``, ``i18n``
#   * שבר עשרוני — "1.8 שניות", "99.9%"
#   * אחוז — "80%"
#   * שנה בת ארבע ספרות — "עד אוגוסט 2026"
#   * מספר שאחריו מילה באנגלית — "304 Not Modified" (קוד סטטוס, לא ספירה)
_DIGIT_COUNT_RE = re.compile(r"(?<![\w.%])\d{1,3}[  ]+(?=[֐-׿])")

# הבטחות יכולת שדורשות אימות מול הקוד
_CLAIM_WORDS = ("מוכנות להרצה", "מוכן להרצה", "ניתן להרצה", "ready to run", "runnable")
_CLAIM_RE = re.compile("|".join(re.escape(w) for w in _CLAIM_WORDS))


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_ai_map", ROOT / "scripts" / "generate_ai_map.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_ai_map"] = mod
    spec.loader.exec_module(mod)
    return mod


def _declared_summaries(docs_root: Path = DOCS) -> dict[str, str]:
    """ההצהרות כפי ש**המחולל** קורא אותן, לא לפי פרסר שני משלנו.

    הגרסה הראשונה כאן סרקה את הקובץ כולו אחרי שורה שמתחילה ב-
    ``:summary: `` — עם רווח אחד בדיוק, ובכל מקום בעמוד. זה עבד, אבל זה
    היה פרסר שני: כל שינוי במחולל היה מסיט את הלינט מהמפה בלי שאיש ישים
    לב, ואז הבדיקה הייתה מאשרת תקציר שהמפה בכלל לא מציגה. עכשיו יש מקור
    אחד — ``_rst_field_summary`` ו-``_front_matter_summary``.

    בלי ה-cap של :func:`_declared_summary`: הלינט צריך לראות את ההצהרה
    המלאה, גם מעבר ל-220 התווים שנכנסים לשורת המפה.
    """
    g = _load_generator()
    out = {}
    for path in sorted(list(docs_root.rglob("*.rst")) + list(docs_root.rglob("*.md"))):
        lines = path.read_text(encoding="utf-8").split("\n")
        summary = (
            g._front_matter_summary(lines)
            if path.suffix == ".md"
            else g._rst_field_summary(lines)
        )
        if summary:
            out[path.relative_to(docs_root.parent).as_posix()] = summary
    return out


def test_there_are_summaries_to_check():
    """שומר אי-ריקנות: בלעדיו הבדיקות למטה עוברות על אוסף ריק."""
    assert len(_declared_summaries()) > 100, len(_declared_summaries())


def test_the_lint_reads_the_same_summaries_as_the_map():
    """כל תקציר שמופיע במפה הוא בדיוק מה שהלינט כאן בודק.

    זו הבדיקה שמחזיקה את המקור היחיד. אם מישהו יחזיר לכאן פרסר עצמאי —
    אחד שסורק את כל הקובץ, או שדורש רווח אחד בדיוק אחרי ``:summary:`` —
    הוא יאסוף אוסף אחר מזה שהמפה מציגה, והבדיקה תיפול. בלעדיה שתי
    הקריאות יכולות להיפרד בשקט, והלינט יאשר תקצירים שאיש לא רואה.

    ההשוואה היא מול שורות המפה עצמן, בפורמט ``- `נתיב` — **כותרת**: תקציר``.
    """
    g = _load_generator()
    lint = _declared_summaries()
    line_re = re.compile(r"^\s*- `([^`]+)` — \*\*.*?\*\*: (.+)$")

    in_map = {}
    for line in g.build_map().split("\n"):
        if m := line_re.match(line):
            in_map[m.group(1)] = m.group(2)

    assert len(in_map) > 100, f"רק {len(in_map)} שורות עם תקציר במפה"
    for rel, mapped in in_map.items():
        assert rel in lint, f"{rel}: מופיע במפה עם תקציר, והלינט לא רואה אותו"
        expected = g._declared_summary(
            (ROOT / rel).read_text(encoding="utf-8").split("\n"), ROOT / rel
        )
        assert mapped == expected, f"{rel}: המפה ומה שנקרא כאן נפרדו"


def test_the_reader_is_the_maps_reader_and_not_a_second_parser(tmp_path):
    """שני עמודים שמפרידים בין הקריאה הנכונה לסריקת-קובץ נאיבית.

    הגרסה הראשונה כאן סרקה את כל הקובץ אחרי שורה שמתחילה ב-
    ``:summary: ``. על שני העמודים שלמטה היא נותנת תשובה אחרת מהמפה:

    * ``late.rst`` — ``:summary:`` באמצע הגוף. סריקת-קובץ הייתה אוספת
      אותו; המפה לא מציגה אותו, כי הוא אינו רשימת השדות שמתחת לכותרת.
    * ``wrapped.rst`` — הצהרה שנמשכת לשורה שנייה. סריקת-קובץ הייתה
      עוצרת בשורה הראשונה ובודקת חצי תקציר.

    זו הבדיקה שנופלת אם מישהו יחזיר לכאן פרסר שני.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "late.rst").write_text(
        "כותרת\n=====\n\nפסקה בגוף.\n\n:summary: לא הצהרה.\n", encoding="utf-8"
    )
    (docs / "wrapped.rst").write_text(
        "כותרת\n=====\n:summary: שורה ראשונה\n   והמשכה.\n\nגוף.\n", encoding="utf-8"
    )

    got = _declared_summaries(docs)

    assert "docs/late.rst" not in got, got.get("docs/late.rst")
    assert got["docs/wrapped.rst"] == "שורה ראשונה והמשכה."


def test_no_counts_in_summaries():
    """אין ספירה בתקציר — לא במילים ולא בספרות. ספירה מתיישנת בשקט."""
    offenders = []
    for rel, summ in _declared_summaries().items():
        for rx in (_COUNT_RE, _DIGIT_COUNT_RE):
            if m := rx.search(summ):
                offenders.append(f"{rel}: {m.group(0)!r} ← {summ[:70]}")
    assert not offenders, (
        "ספירה בתקציר. תארו מה יש בעמוד, לא כמה:\n  " + "\n  ".join(offenders)
    )


def test_no_runnability_claims_in_summaries():
    """אין הבטחה שקוד בעמוד ניתן להרצה — זו טענה שדורשת אימות."""
    offenders = [
        f"{rel}: {summ[:70]}"
        for rel, summ in _declared_summaries().items()
        if _CLAIM_RE.search(summ)
    ]
    assert not offenders, (
        "הבטחת הרצה בתקציר, בלי אימות:\n  " + "\n  ".join(offenders)
    )

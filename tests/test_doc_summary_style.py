"""אוכף שהצהרות התקציר אינן מכילות ספירות או הבטחות יכולת.

הרקע: שלושה סבבי ריוויו רצופים נפלו על אותו דבר — לא על פירסור, אלא על
**טענות שנכתבו בלי לאמת מול הקוד**. תקציר אמר "שבעה מסלולי API" כשהיו
תשעה; תקציר אחר אמר "דוגמאות מוכנות להרצה" כשהקוד בעמוד מכיל ``...``
ופונקציה שאינה מוגדרת; שלישי הציג ``SearchType.SEMANTIC`` כנתמך, בעוד
``AdvancedSearchEngine.search`` נופל עבורו ל-``_text_search``.

ספירה מתיישנת בשקט, והבטחת יכולת דורשת קריאה בקוד. תקציר אמור לתאר מה
יש בעמוד — לא כמה, ולא מה עובד. הבדיקה הזו הופכת שיפוט חוזר לכלל מכני.

מה **לא** נתפס כאן בכוונה: מספרים שהם חלק משם (``Observability v7``,
``OAuth 2.1``, ``p95``), כי הם מזהים ולא ספירה.
"""

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# מילות ספירה בעברית ובאנגלית, כמילה שלמה
_COUNT_WORDS = (
    "שני", "שתי", "שלושה", "שלוש", "ארבעה", "ארבע", "חמישה", "חמש",
    "שישה", "שש", "שבעה", "שבע", "שמונה", "תשעה", "תשע", "עשרה", "עשר",
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
)
_COUNT_RE = re.compile(r"(?<![\w֐-׿])(?:" + "|".join(_COUNT_WORDS) + r")(?![\w֐-׿])")

# הבטחות יכולת שדורשות אימות מול הקוד
_CLAIM_WORDS = ("מוכנות להרצה", "מוכן להרצה", "ניתן להרצה", "ready to run", "runnable")
_CLAIM_RE = re.compile("|".join(re.escape(w) for w in _CLAIM_WORDS))


def _declared_summaries() -> dict[str, str]:
    out = {}
    for p in sorted(list(DOCS.rglob("*.rst")) + list(DOCS.rglob("*.md"))):
        lines = p.read_text(encoding="utf-8").split("\n")
        if p.suffix == ".rst":
            for line in lines:
                if line.startswith(":summary: "):
                    out[p.relative_to(ROOT).as_posix()] = line[len(":summary: "):].strip()
                    break
        elif lines and lines[0].strip() == "---":
            end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
            if end is None:
                continue
            try:
                data = yaml.safe_load("\n".join(lines[1:end])) or {}
            except yaml.YAMLError:
                continue
            if isinstance(data, dict) and data.get("summary"):
                out[p.relative_to(ROOT).as_posix()] = str(data["summary"]).strip()
    return out


def test_there_are_summaries_to_check():
    """שומר אי-ריקנות: בלעדיו הבדיקות למטה עוברות על אוסף ריק."""
    assert len(_declared_summaries()) > 100, len(_declared_summaries())


def test_no_counts_in_summaries():
    """אין מילת ספירה בתקציר — ספירה מתיישנת בלי שאיש ישים לב."""
    offenders = [
        f"{rel}: {m.group(0)!r} ← {summ[:70]}"
        for rel, summ in _declared_summaries().items()
        if (m := _COUNT_RE.search(summ))
    ]
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

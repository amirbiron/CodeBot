"""יומן העדכונים — עמוד לכל חודש: כל יום בעמוד של החודש שלו, כל עמוד רשום ברשימת החודשים, אף עמוד אינו גדל בלי סוף,
וכל הפניה לרשומה מגיעה אליה.

**למה עמוד לכל חודש.** הבדיקה שפתיח של עדכון ייחודי בעמוד (``_usable_headline`` ב-``services/docs_index_service.py``)
סופרת כל פתיח בכל הטקסט של העמוד שלו, ולכן העבודה שלה גדלה כמו מספר העדכונים כפול אורך העמוד. עמוד אחד שגדל בלי
סוף היה מאט את המעבר של אינדקס התיעוד ומגדיל את הזיכרון שלו — והמעבר רץ ב-worker היחיד של הוובאפ. רשומה נכתבת
לעמוד של החודש שלה ולא זזה משם: המפתח של רשומה באינדקס כולל את קובץ המקור, ולכן העברה של חודש לקובץ אחר הייתה שולחת
את כל העדכונים שלו להטמעה מחדש, ומשאירה הפניות לרשומות שלו מצביעות על הקובץ הישן.

**ומה מונע מעמוד לגדול.** ``test_every_day_is_on_the_page_of_its_month`` נכשל ברגע שרשומה של חודש חדש נכתבת לעמוד של
החודש הקודם, וההודעה שלו אומרת איזה עמוד לפתוח. ככה החלוקה קורית בעצמה, בלי תזכורת ובלי אוטומציה.
``MAX_UPDATE_LOG_PAGE_BYTES`` הוא רשת ביטחון לחודש חריג: הגודל של יומן העדכונים כשהיה עמוד אחד, ב-20.11.2026, לפני
החלוקה לחודשים. על העמוד הזה העלות נמדדה ונמצאה סבירה (``scripts/measure_docs_index_memory.py``, השלב
``build_records``).

**למה בודקים הפניות.** קוד ותיעוד מפנים לרשומה ביומן בשם העמוד ובתאריך שלה. בחלוקה לחודשים, הפניות כאלה בקוד
ובתיעוד עדיין הצביעו על ``docs/whats-new.rst``, שהרשומות כבר לא שם — ושום דבר לא נכשל.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import docs_index_service as index  # noqa: E402

#: גודל מרבי לעמוד של יומן העדכונים, בבתים של קובץ המקור. ההסבר בראש הקובץ.
MAX_UPDATE_LOG_PAGE_BYTES = 668_325

#: עמוד רשימת החודשים: ``toctree`` של עמודי היומן, והחדש ביותר ראשון.
LANDING = ROOT / "docs" / "whats-new.rst"

#: העמוד של הימים שלפני החודש הראשון שיש לו עמוד משלו.
EARLIER = "earlier"

_MONTH_RE = re.compile(r"\d{4}-\d{2}")
_DATE_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.M)
#: כותרת של יום ביומן: תאריך בשורה משלו, ומתחתיו קו מקפים.
_DAY_HEADING_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\n-+$", re.M)

#: הפניה לעמוד של היומן, בשלוש הצורות שבהן היא נכתבת: נתיב בקוד ובתיעוד (בגרש כפול או בודד), ו-``:doc:`` בעמוד RST
#: (גם עם טקסט משלו, ``:doc:`טקסט <יעד>```).
_PATH_REF_RE = re.compile(r"`(docs/whats-new(?:/[\w-]+)?\.rst)`")
_DOC_REF_RE = re.compile(r":doc:`(?:[^`<]*<)?/?(whats-new(?:/[\w-]+)?)>?`")

#: תאריך בשתי הצורות שבהן ההפניות כותבות אותו: 2026-10-11 ו-11.10.2026.
_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _update_log_pages() -> list[Path]:
    """העמודים של יומן העדכונים בריפו, לפי אותו כלל שהאינדקס מזהה בו יומן (``is_update_log_source``)."""
    candidates = sorted((ROOT / index.UPDATE_LOG_DIR).glob("*"))
    return [path for path in candidates if path.is_file() and index.is_update_log_source(_rel(path))]


def _days(path: Path) -> list[str]:
    """הימים בעמוד. תאריך בשורה משלו שאינו כותרת של יום היה נעלם מהבדיקות כאן בשקט, ולכן הוא נכשל."""
    text = path.read_text(encoding="utf-8")
    days = _DAY_HEADING_RE.findall(text)
    assert len(days) == len(_DATE_LINE_RE.findall(text)), (
        f"{_rel(path)}: תאריך בשורה משלו שאינו כותרת של יום (קו מקפים מתחתיו)"
    )
    return days


def _months() -> list[str]:
    return sorted((path.stem for path in _update_log_pages() if path.stem != EARLIER), reverse=True)


def test_the_month_pages_are_found():
    """בלי זה, סריקה שלא מצאה כלום הייתה "עוברת" את כל הבדיקות כאן."""
    assert _months(), _update_log_pages()


def test_every_page_is_named_after_its_month():
    misnamed = [
        _rel(path) for path in _update_log_pages() if path.stem != EARLIER and not _MONTH_RE.fullmatch(path.stem)
    ]
    assert not misnamed, f"עמוד ביומן העדכונים שאינו בשם של חודש (YYYY-MM.rst) או {EARLIER}.rst: {misnamed}"


def test_every_day_is_on_the_page_of_its_month():
    """רשומה של חודש חדש נכתבת לעמוד חדש. בלי זה היא הייתה נכתבת לעמוד של החודש הקודם, והעמוד היה גדל בלי
    סוף."""
    first_month = min(_months())
    misplaced = []
    for path in _update_log_pages():
        for day in _days(path):
            month = day[:7]
            if path.stem == EARLIER and month >= first_month:
                misplaced.append(
                    f"{day} ב-{_rel(path)}: הוא כבר בחודש שיש לו עמוד ({index.UPDATE_LOG_DIR}/{month}.rst)"
                )
            elif path.stem != EARLIER and month != path.stem:
                misplaced.append(f"{day} ב-{_rel(path)}: מקומו ב-{index.UPDATE_LOG_DIR}/{month}.rst")
    assert not misplaced, (
        "יום ביומן העדכונים שאינו בעמוד של החודש שלו:\n  " + "\n  ".join(misplaced) + "\n"
        f"לחודש חדש פותחים עמוד חדש באותה צורה כמו של החודש הקודם (תקציר, כותרת), ומוסיפים אותו בראש ה-toctree של "
        f"{_rel(LANDING)} — docs/doc-authoring.rst, \"רשומה ב-What’s New\"."
    )


def test_the_landing_page_lists_every_page_newest_first():
    """עמוד שאינו באף ``toctree`` מפיל את בניית התיעוד (``document isn't included in any toctree``), וגם לא היה מופיע
    בתפריט. כאן זה נתפס כבר בטסט, עם השם של העמוד — וגם הסדר: החדש ביותר ראשון, והימים שלפני החודשים בסוף."""
    listed = re.findall(r"(?m)^\s+(whats-new/[\w-]+)\s*$", LANDING.read_text(encoding="utf-8"))
    folder = index.UPDATE_LOG_DIR.name
    expected = [f"{folder}/{month}" for month in _months()]
    if any(path.stem == EARLIER for path in _update_log_pages()):
        expected.append(f"{folder}/{EARLIER}")
    assert listed == expected


def test_every_update_log_page_is_below_the_ceiling():
    sizes = {_rel(path): path.stat().st_size for path in _update_log_pages()}
    too_big = {rel: size for rel, size in sizes.items() if size > MAX_UPDATE_LOG_PAGE_BYTES}
    assert not too_big, (
        f"עמוד ביומן העדכונים גדול מ-{MAX_UPDATE_LOG_PAGE_BYTES:,} בתים: {too_big}. זה חודש חריג: לפני שמגדילים "
        f"את התקרה מודדים את המעבר של אינדקס התיעוד על העמוד הזה (scripts/measure_docs_index_memory.py), כמו "
        f"בהסבר בראש הטסט."
    )


def _iso(match: re.Match[str]) -> str:
    if match[1]:
        return f"{match[1]}-{match[2]}-{match[3]}"
    return f"{match[6]}-{int(match[5]):02d}-{int(match[4]):02d}"


def _references() -> list[tuple[str, int, list[str], list[str]]]:
    """כל שורה בריפו שמפנה לעמוד של היומן: (קובץ, שורה, העמודים שהיא מפנה אליהם, התאריכים שבה).

    הקבצים הם מה שגיט עוקב אחריו (``git ls-files -z``, כמו ``tests/test_config_definitions_coverage.py``), ונקראים
    כבתים: רק שורה שיש בה ``whats-new`` מפוענחת, כך שגם קובץ שאינו טקסט נסרק ולא מדלגים עליו. העמודים של היומן עצמם
    לא נבדקים — הרשומות שבהם הן היסטוריה, ומה שהן מתארות נכון ליום שבו נכתבו.
    """
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    tracked = [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]
    assert "README.md" in tracked, "git ls-files לא החזיר את קבצי הריפו"

    found = []
    for rel in tracked:
        path = ROOT / rel
        if not path.is_file() or index.is_update_log_source(rel):
            continue
        for number, raw in enumerate(path.read_bytes().split(b"\n"), 1):
            if b"whats-new" not in raw:
                continue
            line = raw.decode("utf-8", "replace")
            pages = _PATH_REF_RE.findall(line) + [f"docs/{target}.rst" for target in _DOC_REF_RE.findall(line)]
            if pages:
                found.append((rel, number, pages, [_iso(m) for m in _DATE_RE.finditer(line)]))
    return found


def test_the_reference_scan_finds_the_references_it_is_meant_to_check():
    """הבדיקה שאחרי זה עוברת גם כשהסריקה לא מצאה אף הפניה — ולכן כאן נבדק שהיא מוצאת את כל הצורות, עם תאריך."""
    dated = {(rel, page) for rel, _number, pages, dates in _references() if dates for page in pages}
    assert ("main.py", "docs/whats-new/2026-10.rst") in dated  # ``נתיב``, ISO
    assert ("webapp/sticky_notes_api.py", "docs/whats-new/2026-10.rst") in dated  # D.M.YYYY
    assert ("GUIDES/REPO_SYNC_ENGINE_GUIDE.md", "docs/whats-new/2026-10.rst") in dated  # גרש בודד
    assert ("docs/webapp/code-browser.rst", "docs/whats-new/2026-10.rst") in dated  # :doc:`/...`
    assert ("docs/mcp-server.rst", "docs/whats-new/2026-10.rst") in dated  # :doc:`...` יחסי


def test_a_dated_reference_points_at_the_page_that_holds_that_day():
    """הפניה לרשומה כותבת את העמוד ואת התאריך באותה שורה, והתאריך חייב להיות כותרת של יום באחד העמודים שהשורה מפנה
    אליהם. עמוד רשימת החודשים אינו מחזיק אף יום, ולכן הפניה אליו עם תאריך נכשלת, עם העמוד שבו היום נמצא."""
    days = {_rel(path): set(_days(path)) for path in _update_log_pages()}
    days[_rel(LANDING)] = set()
    missing_page = sorted(
        {f"{rel}:{number}: {page}" for rel, number, pages, _ in _references() for page in pages if page not in days}
    )
    assert not missing_page, f"הפניה לעמוד שאינו עמוד של יומן העדכונים: {missing_page}"

    stale = [
        f"{rel}:{number}: {date} אינו בעמוד {' / '.join(pages)}"
        + "".join(f" — הוא ב-{page}" for page, page_days in days.items() if date in page_days)
        for rel, number, pages, dates in _references()
        for date in dates
        if not any(date in days[page] for page in pages)
    ]
    assert not stale, "הפניות לרשומה ביומן העדכונים שאינן מגיעות אליה:\n  " + "\n  ".join(stale)

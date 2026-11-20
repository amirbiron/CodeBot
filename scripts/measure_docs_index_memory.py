#!/usr/bin/env python3
"""כמה זיכרון מעבר של אינדקס התיעוד מקצה, שלב אחר שלב, על קובץ ייצוא אמיתי.

**למה.** המעבר (``run_pass`` ב-``services/docs_index_service.py``) רץ בתהליך של הוובאפ ומחזיק את קובץ הייצוא
כולו בזיכרון. ``EXPORT_MAX_BYTES`` ב-``services/docs_export_client.py`` אומר שהגדלה שלו צריכה מדידת זיכרון קודם,
וזו המדידה. ``docs/webapp/global-search.rst`` (המעבר) ו-``docs/whats-new.rst`` מצטטים את מה שהיא מדפיסה.

**מה נמדד: השיא, ולא מה שנשאר.** המכסה של הוובאפ היא הקונטיינר כולו, ופייתון לא מחזיר למערכת זיכרון ששוחרר,
ולכן גם שיא רגעי נשאר כגודל התהליך (``host-metric-in-container`` ב-amir-bug-patterns). לכל שלב מודפס שיא
ההקצאות של פייתון (``tracemalloc``) מעל מה שהיה בזיכרון כשהשלב התחיל, ומה שנשאר ממנו אחריו.

**השלבים, בסדר שבו המעבר מריץ אותם:**

- **הורדה ופענוח** — ``fetch_export``, מול תעבורה מדומה שמגישה את בתי הקובץ בחתיכות חדשות של
  :data:`CHUNK_BYTES` (:class:`_ChunkedBody`): אותו מסלול כמו מול האתר, כולל איסוף החתיכות וחיבורן, בלי רשת.
- **בניית הרשומות** — ``build_records``: הסעיפים והנתחים לחיפוש, וביומן עדכונים גם הפירוק לעדכונים.
- **בניית העמודים** — ``build_pages``.

``compute_plan`` בונה את שתיהן ומוסיף קריאה של המזהים וה-sha מהמסד, שקטנה מהן בהרבה. לכן הוא אינו כאן,
והסקריפט לא צריך מסד.

**חימום לפני המדידה:** בניית הרשומות והעמודים על עמוד אחד מהקובץ, ועל יומן העדכונים אם יש בו. כך ייבוא עצל
ומטמונים של ספריות (regex, markdown-it) אינם נספרים כעבודה של המעבר.

**מה לא נמדד:** RSS, שגדל פחות מהשיא כשזיכרון ששוחרר חוזר לשימוש; וזיכרון של המסד ושל Gemini.

**שימוש,** מהאתר החי או מקובץ מקומי. ``services/docs_index_service.py`` טוען את הקונפיג של האפליקציה (``config.py``),
ולכן הסקריפט דורש את משתני הסביבה שלו (``BOT_TOKEN``, ``MONGODB_URL``), אף שאינו מתחבר למסד::

    python scripts/measure_docs_index_memory.py https://amirbiron.github.io/CodeBot/_export/sections.json
    python scripts/measure_docs_index_memory.py docs/_build/html/_export/sections.json
"""

from __future__ import annotations

import gc
import json
import platform
import sys
import tracemalloc
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from scripts.measure_docs_export import _load  # noqa: E402
from services import docs_export_client as export_client  # noqa: E402
from services import docs_index_service as index  # noqa: E402

#: השלבים, בסדר שבו הם רצים ובשמות שבהם הם מודפסים.
STAGES = ("download + parse (fetch_export)", "build_records", "build_pages")

#: גודל החתיכה שהגוף מוגש בה: ``READ_NUM_BYTES`` של httpcore 1.0.9 (``httpcore/_sync/http11.py``), הכמות הגדולה
#: ביותר שקריאה אחת מהרשת מחזירה. רשת יכולה להחזיר פחות בכל קריאה, וזה משנה את מספר החתיכות ולא את סכומן.
CHUNK_BYTES = 64 * 1024


class _ChunkedBody(httpx.SyncByteStream):
    """הגוף כמו שהוא מגיע מהרשת: חתיכות ``bytes`` חדשות, אחת בכל פעם.

    ``httpx.Response(content=data)`` מגיש את ``data`` עצמו בחתיכה אחת (``ByteStream`` ב-``httpx/_content.py``,
    0.28.1), ו-``b"".join`` של חתיכה אחת מחזיר אותה בלי להעתיק. כך ``fetch_export`` לא הקצה לא את החתיכות ולא את
    החיבור שלהן, שבמעבר האמיתי קורים שניהם, והשלב נמדד נמוך מהאמת. ``tobytes`` מעתיק תמיד, גם כשהחתיכה היא
    הקובץ כולו.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __iter__(self) -> Iterator[bytes]:
        view = memoryview(self._data)
        for start in range(0, len(view), CHUNK_BYTES):
            yield view[start:start + CHUNK_BYTES].tobytes()


def _transport(data: bytes) -> httpx.MockTransport:
    """תעבורה שמגישה את הקובץ בחתיכות (:class:`_ChunkedBody`) לכל בקשה."""
    return httpx.MockTransport(lambda request: httpx.Response(200, stream=_ChunkedBody(data)))


def _warm_up(data: bytes) -> None:
    """בניית רשומות ועמודים על עמוד אחד מהקובץ ועל יומן העדכונים, לפני שהמדידה מתחילה."""
    raw = json.loads(data)
    pages = raw["pages"][:1] + [
        page for page in raw["pages"][1:] if page.get("source_path") in index.UPDATE_LOG_SOURCES
    ]
    raw.update(pages=pages, page_count=len(pages), section_count=sum(len(page["sections"]) for page in pages))
    document = export_client.parse_export(json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    index.build_records(document)
    index.build_pages(document)


def measure(data: bytes) -> Dict[str, Any]:
    """מודד את השלבים על הבתים של קובץ ייצוא. כל שלב: ``peak`` ו-``kept`` בבתים, מעל מה שהיה כשהתחיל.

    התקרה של הוובאפ על גודל הקובץ (``EXPORT_MAX_BYTES``) אינה חלה כאן, כי המדידה היא בדיוק מה שצריך כדי להחליט
    עליה: הקובץ נקרא בלי לבדוק את גודלו.
    """
    _warm_up(data)
    transport = _transport(data)
    limit = export_client.EXPORT_MAX_BYTES
    export_client.EXPORT_MAX_BYTES = max(limit, len(data))
    stages: List[Dict[str, Any]] = []
    tracemalloc.start()
    try:
        def stage(name: str, run: Callable[[], Any]) -> Any:
            gc.collect()
            before, _ = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
            value = run()
            after, peak = tracemalloc.get_traced_memory()
            stages.append({"stage": name, "peak": peak - before, "kept": after - before})
            return value

        with export_client.new_export_http_client(transport=transport) as http:
            fetched = stage(STAGES[0], lambda: export_client.fetch_export(http))
        document = fetched.document
        records = stage(STAGES[1], lambda: index.build_records(document))
        pages = stage(STAGES[2], lambda: index.build_pages(document))
    finally:
        tracemalloc.stop()
        export_client.EXPORT_MAX_BYTES = limit
    return {
        "python": platform.python_version(),
        "source_commit": document.source_commit,
        "bytes": len(data),
        "pages": len(document.pages),
        "sections": document.section_count,
        "records": len(records[0]),
        "chunks": len(records[1]),
        "rst_pages": len(pages),
        "stages": stages,
    }


def main(argv: List[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    result = measure(_load(argv[0]))
    mib = 1024 * 1024
    print(
        f"python {result['python']}, export {result['source_commit']}: {result['bytes'] / mib:.2f} MiB, "
        f"{result['pages']} pages, {result['sections']} sections -> {result['records']} records, "
        f"{result['chunks']} chunks, {result['rst_pages']} rst pages"
    )
    for row in result["stages"]:
        print(f"{row['stage']:34s} peak +{row['peak'] / mib:6.1f} MiB   kept +{row['kept'] / mib:6.1f} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

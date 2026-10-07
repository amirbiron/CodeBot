#!/usr/bin/env python3
"""מודד את קובץ הייצוא של אתר התיעוד: הגודל, והערך הארוך ביותר בכל שדה.

התקרות ב-``services/docs_export_client.py`` (``EXPORT_MAX_BYTES``, ``MAX_PATH_BYTES``,
``MAX_TITLE_BYTES``, ``MAX_ANCHOR_BYTES``, ``MAX_BREADCRUMB_BYTES``) כתובות ככפולה של מדידה, והסקריפט
הזה הוא מה שמייצר את המדידה. הוא קורא את הקובץ כמו שהוא, בלי הבדיקות של הוובאפ, כדי שאפשר
יהיה למדוד גם קובץ שחורג מהתקרות הנוכחיות — זה בדיוק המקרה שבו צריך מדידה חדשה.

שימוש — מהאתר החי, או מקובץ מקומי (למשל ``docs/_build/html/_export/sections.json``)::

    python scripts/measure_docs_export.py https://amirbiron.github.io/CodeBot/_export/sections.json
    python scripts/measure_docs_export.py docs/_build/html/_export/sections.json
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

#: המפריד שבו השביל מחובר לטקסט שמוטמע. עותק של ``BREADCRUMB_SEPARATOR`` ב-
#: ``services/docs_export_client.py`` — הסקריפט לא מייבא את הוובאפ, כדי לרוץ גם בלעדיו.
BREADCRUMB_SEPARATOR = " › "


def _load(source: str) -> bytes:
    if source.startswith("https://"):
        with urllib.request.urlopen(source, timeout=60) as response:  # noqa: S310 — https בלבד
            return response.read()
    return Path(source).read_bytes()


def measure(data: bytes) -> dict:
    document = json.loads(data)
    pages = document["pages"]
    sections = [section for page in pages for section in page["sections"]]

    def longest(values) -> int:
        return max((len(value.encode("utf-8")) for value in values), default=0)

    return {
        "source_commit": document.get("source_commit"),
        "bytes": len(data),
        "pages": len(pages),
        "sections": len(sections),
        "path": longest(page["path"] for page in pages),
        "source_path": longest(page["source_path"] for page in pages),
        "page_title": longest(page["title"] for page in pages),
        "section_title": longest(section["title"] for section in sections),
        "anchor": longest(section["anchor"] for section in sections),
        "breadcrumb": longest(BREADCRUMB_SEPARATOR.join(section["breadcrumb"]) for section in sections),
        "markdown": longest(section["markdown"] for section in sections),
        "empty_markdown": sum(1 for section in sections if not section["markdown"].strip()),
    }


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    for name, value in measure(_load(argv[0])).items():
        print(f"{name}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

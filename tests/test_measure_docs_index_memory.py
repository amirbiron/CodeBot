"""``scripts/measure_docs_index_memory.py``: המדידה שהתיעוד מצטט רצה על קובץ ייצוא, בלי מסד, ומחזירה את השלבים
בסדר של המעבר — וקובץ גדול מהתקרה של הוובאפ לא נדחה ולא משאיר את התקרה מוגדלת."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from _docs_index_harness import SHA_A, export_bytes, page, section, site_pages  # noqa: E402
from scripts import measure_docs_index_memory as measure  # noqa: E402
from services import docs_export_client as export_client  # noqa: E402
from services import docs_index_service as index  # noqa: E402


def _log_page():
    """יומן עדכונים: החימום בונה גם אותו, כי הפירוק לעדכונים טוען את markdown-it."""
    return page(
        "whats-new.html", sorted(index.UPDATE_LOG_SOURCES)[0], section("whats-new", "What’s New", markdown=""),
        section("id1", "What’s New", "2026-11-20", markdown="-   **fix: א.** טקסט העדכון."),
    )


def test_the_stages_are_measured_in_the_order_the_pass_runs_them():
    data = export_bytes(SHA_A, [*site_pages(), _log_page()])

    result = measure.measure(data)

    assert [row["stage"] for row in result["stages"]] == list(measure.STAGES)
    assert all(row["peak"] >= 0 and row["peak"] >= row["kept"] for row in result["stages"]), result["stages"]
    assert (result["bytes"], result["source_commit"]) == (len(data), SHA_A)
    assert result["records"] > 0 and result["chunks"] > 0 and result["rst_pages"] > 0


def test_the_body_arrives_in_new_chunks_like_from_the_network():
    """השלב של ההורדה נמדד רק אם ``fetch_export`` מקצה את החתיכות ואת החיבור שלהן, כמו מול הרשת. גוף שמוגש כ-``data``
    עצמו בחתיכה אחת לא מקצה אף אחד מהם: ``b"".join`` של חתיכה אחת מחזיר אותה בלי להעתיק."""
    data = bytes(range(256)) * (2 * measure.CHUNK_BYTES // 256 + 3)

    with httpx.Client(transport=measure._transport(data)) as client:
        with client.stream("GET", "https://docs.example.test/_export/sections.json") as response:
            parts = list(response.iter_bytes())

    assert len(parts) == math.ceil(len(data) / measure.CHUNK_BYTES)
    assert all(len(part) <= measure.CHUNK_BYTES and part is not data for part in parts)
    assert b"".join(parts) == data


def test_a_file_over_the_webapp_ceiling_is_measured_and_the_ceiling_is_put_back(monkeypatch):
    """הסקריפט נועד בדיוק להחליט על התקרה, ולכן קובץ גדול ממנה נמדד. אחרי המדידה התקרה חוזרת לערך שלה."""
    data = export_bytes(SHA_A, site_pages())
    monkeypatch.setattr(export_client, "EXPORT_MAX_BYTES", len(data) - 1)

    result = measure.measure(data)

    assert result["bytes"] == len(data)
    assert export_client.EXPORT_MAX_BYTES == len(data) - 1


def test_the_cli_prints_every_stage(tmp_path, capsys):
    path = tmp_path / "sections.json"
    path.write_bytes(export_bytes(SHA_A, site_pages()))

    assert measure.main([str(path)]) == 0

    out = capsys.readouterr().out
    assert all(name in out for name in measure.STAGES), out

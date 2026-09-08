"""שדות החיפוש הסמנטי לא יוצאים בתשובות ה-MCP.

הרקע: ``codekeeper_get_file`` החזיר בכל קריאה את ``snippetEmbedding`` — 768
מספרים, כ-9KB — יחד עם תשעה שדות מטא-דאטה של האמבדינג. על קובץ בן 1.8KB
הווקטור גדול פי חמישה מהקובץ, ופי חמישה־עשר מטווח של שש שורות. זה מבטל
בדיוק את מה שקריאת הטווח נועדה לחסוך.
"""

from __future__ import annotations

import json

import pytest

from mcp_server import backend as be


def _doc(**extra):
    """מסמך קובץ כפי שהוא יושב במונגו, כולל תשתית האמבדינג."""
    doc = {
        "_id": "6a96b1d4ed30235e55ab8767",
        "user_id": 42,
        "file_name": "notes.md",
        "code": "line1\nline2\nline3\n",
        "programming_language": "markdown",
        "description": "",
        "tags": [],
        "version": 4,
        "is_favorite": False,
        "file_size": 1814,
        "lines_count": 14,
        "snippetEmbedding": [0.001 * i for i in range(768)],
        "needs_embedding": False,
        "needs_chunking": False,
        "contentHash": "68dcf86e2e1f7407b00df36cd42adeab7a0edbf2003a9c8787bac55aae9ae57e",
        "embeddingUpdatedAt": "2026-09-01T11:07:18.431000+00:00",
        "embeddingModelKey": "gemini-embedding-001/768",
        "embeddingModel": "gemini-embedding-001",
        "embeddingApiVersion": "v1beta",
        "embeddingDim": 768,
        "chunkCount": 1,
    }
    doc.update(extra)
    return doc


# ---------------------------------------------------------------------------
# הדליפה עצמה
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", be._SEMANTIC_FIELDS)
def test_no_semantic_field_survives_serialization(field):
    """כל אחד מהעשרה, בשני מצבי ``include_code``."""
    assert field not in be._clean(_doc())
    assert field not in be._clean(_doc(), include_code=True)
    assert field not in be._full(_doc())


def test_the_vector_is_gone_from_the_serialized_payload():
    """לא רק המפתח — גם התוכן.

    בדיקה על המחרוזת עצמה, כי שדה מקונן היה עובר בדיקת מפתחות ברמה העליונה.
    """
    payload = json.dumps(be._full(_doc()), default=str)

    assert "snippetEmbedding" not in payload
    assert "0.767" not in payload  # ערך מתוך הווקטור הסינתטי


def test_the_payload_actually_shrinks():
    """המדד שבגללו התיקון הזה נעשה: כמה בייטים נחסכים בפועל."""
    with_vector = len(json.dumps(_doc(), default=str))
    without = len(json.dumps(be._full(_doc()), default=str))

    assert without < with_vector / 5, (without, with_vector)


# ---------------------------------------------------------------------------
# מה שחייב לשרוד
# ---------------------------------------------------------------------------


def test_the_fields_the_reader_came_for_are_untouched():
    """החרגה גורפת מדי גרועה בדיוק כמו דליפה.

    ``lines_count`` מתועד ב-``docs/mcp-server.rst``, ו-``code`` הוא כל העניין.
    """
    out = be._full(_doc())

    assert out["code"] == "line1\nline2\nline3\n"
    assert out["lines_count"] == 14
    assert out["file_size"] == 1814
    assert out["version"] == 4
    assert out["is_favorite"] is False
    assert out["id"] == "6a96b1d4ed30235e55ab8767"
    assert out["language"] == "markdown"  # האליאס הידידותי


def test_the_edit_path_still_gets_everything_it_reads():
    """``edit_file``/``append_file`` בונים גרסה חדשה מהמסמך הזה.

    ``_load_editable`` ← ``_resave_edited`` קוראים בדיוק את הארבעה האלה;
    אם אחד מהם יורד בהחרגה, עריכה מאבדת מטא-דאטה בלי להיכשל.
    """
    out = be._full(_doc(description="הערות", tags=["md"]))

    assert out["code"]
    assert out["programming_language"] == "markdown"
    assert out["description"] == "הערות"
    assert out["tags"] == ["md"]


def test_a_field_nobody_listed_still_passes_through():
    """ההחרגה ממוקדת ולא הפכה את הסריאלייזר לרשימת היתר.

    שינוי כזה הוא שינוי חוזה, והוא היה מפיל שדות מתועדים בלי שאיש יבחין.
    """
    assert be._full(_doc(some_future_field="x"))["some_future_field"] == "x"


# ---------------------------------------------------------------------------
# מניעת דריפט מול מקור האמת
# ---------------------------------------------------------------------------


def test_the_local_list_equals_the_schema_definition():
    """שוויון מלא בשני הכיוונים מול ``SNIPPET_SEMANTIC_FIELDS``.

    הרשימה ב-``backend.py`` משוכפלת במכוון: ייבוא ישיר של ``database.schemas``
    מריץ את ``database/__init__.py``, שבונה ``DatabaseManager()`` בזמן טעינה,
    בניגוד לכלל הייבוא של החבילה. הטסט הזה הוא מה שמחזיק את שתי הרשימות
    צמודות, ולכן הוא נדרש **בשני הכיוונים**: שדה שיתווסף שם היה דולף לכאן,
    ושדה שיוסר שם היה נשאר כאן תלוי באוויר.

    כאן הייבוא הכבד מותר — טסט אינו מסלול הגשה.
    """
    from database.schemas import SNIPPET_SEMANTIC_FIELDS

    assert set(be._SEMANTIC_FIELDS) == set(SNIPPET_SEMANTIC_FIELDS)


def test_the_local_list_has_no_duplicates():
    """מקור אמת משוכפל שגם חוזר על עצמו קשה עוד יותר לקרוא נכון."""
    assert len(be._SEMANTIC_FIELDS) == len(set(be._SEMANTIC_FIELDS))

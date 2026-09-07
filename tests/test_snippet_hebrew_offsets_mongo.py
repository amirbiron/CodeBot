"""#3353 מול מונגו אמיתי — היחידות של חיתוך ה-snippet על טקסט עברי.

**למה הקובץ הזה קיים, ולמה סטאב לא יכול להחליף אותו.** הבאג הוא בסמנטיקה של
מונגו עצמה: ``$regexFind`` מחזיר ``idx`` בתווים, ``$substrBytes`` מצפה לבייטים,
ובעברית זה או חותך שגוי או **זורק**. אף דמה כתובה-ביד בריפו אינה מדגמנת את זה —
``tests/_fake_mongo.py`` אפילו אין בו ``aggregate``, והוספת אחד פירושה לכתוב
מפרש ביטויי BSON. לכן זה הקובץ היחיד שבאמת מריץ את השאילתה.

**הוא מדולג ב-CI**, כי הג'וב ``unit-tests`` מגדיר שירות ``mongodb`` בלי ``ports:``
ואינו רץ בקונטיינר, ולכן שם המארח אינו נפתר. זה מתועד ב-``.github/workflows/ci.yml``
וב-``tests/conftest.py``. האח שלו שכן רץ בכל PR הוא
``tests/test_snippet_offsets_are_code_points.py``, שבודק את **יחידות** הצינור
בלי להריץ אותו. אף אחד מהשניים אינו מספיק לבדו.

**כל הערכים שבאסרשנים כאן נמדדו** מול MongoDB 8.0 לפני שנכתבו, ולא חושבו בראש.

הרצה מקומית::

    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \\
        pytest tests/test_snippet_hebrew_offsets_mongo.py -v
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

USER_ID = 987654321
NEEDLE = "שלום"  # ארבעה תווים, שמונה בייטים


def _doc(file_name: str, code: str) -> dict:
    """מסמך בלי ``file_size`` — כדי שענף ה-``$ifNull`` המחשב באמת ירוץ."""
    now = datetime.now(timezone.utc)
    return {
        "user_id": USER_ID,
        "file_name": file_name,
        "code": code,
        "programming_language": "text",
        "tags": [],
        "version": 1,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def _search(wa, monkeypatch, query: str):
    """קורא ל-``_safe_search`` במסלול ה-regex.

    ``search_type="regex"`` במכוון: הוא נמנע מ-``$text``, שהיה דורש אינדקס
    טקסט על המסד הזמני ומפיל את הריצה מסיבה שאינה קשורה לבאג.
    """
    monkeypatch.setattr(wa, "search_engine", None, raising=False)
    return wa._safe_search(USER_ID, query, limit=50, search_type="regex")


# --------------------------------------------------------------------------
# מסלול החיפוש
# --------------------------------------------------------------------------


def test_a_hebrew_match_is_sliced_and_highlighted_in_characters(wired_mongo, monkeypatch, caplog):
    """**כשל שקט — בלי חריגה בכלל.** זה החצי שקל לפספס.

    עם 100 אותיות לפני ההתאמה, ``_snippet_start`` הוא 50, ובייט 50 הוא
    **תחילת** תו. לכן ``$substrBytes`` אינו זורק — הוא פשוט מחזיר את בייטים
    50..250, שהם תווים 25..125. נמדד: 100 תווים במקום 154.

    ובמקביל ``_match_len`` היה 8 (בייטים) במקום 4 (תווים), ולכן ההדגשה סימנה
    כפול מאורך המילה.
    """
    wa = wired_mongo
    code = ("ש" * 100) + NEEDLE + ("ש" * 100)  # 204 תווים, 408 בייטים
    wa.db.code_snippets.insert_one(_doc("hebrew_silent.txt", code))

    with caplog.at_level(logging.WARNING):
        results = _search(wa, monkeypatch, NEEDLE)

    assert len(results) == 1, "המסמך לא נמצא בכלל"
    result = results[0]

    # נמדד: $substrCP(code, 50, 200) מחזיר 154 תווים (204-50), הישן החזיר 100
    assert result.snippet_preview == code[50:250]
    assert len(result.snippet_preview) == 154

    start, end = result.highlight_ranges[0]
    assert result.snippet_preview[start:end] == NEEDLE, (
        f"ההדגשה מסמנת {result.snippet_preview[start:end]!r} ולא את המילה עצמה"
    )
    assert end - start == 4, "אורך ההדגשה בתווים, לא בבייטים"

    # נעילת היקף: גודל קובץ הוא באמת בייטים
    assert result.file_size == len(code.encode("utf-8")) == 408

    assert not [r for r in caplog.records if "primary aggregation" in r.getMessage()], (
        "המסלול המהיר נפל, כלומר הבדיקה לא בדקה את מה שהיא טוענת"
    )


def test_a_hebrew_match_on_an_odd_boundary_does_not_crash_the_pipeline(
    wired_mongo, monkeypatch, caplog
):
    """**הכשל שמפיל את השאילתה.**

    עם 101 אותיות לפני ההתאמה, ``_snippet_start`` הוא 51 — הבייט השני של תו.
    נמדד מול מונגו: ``$substrBytes: Invalid range, starting index is a UTF-8
    continuation byte``. הצינור המהיר מת, והקוד יורד לסריקה מלאה בלי אינדקס.
    """
    wa = wired_mongo
    code = ("ש" * 101) + NEEDLE + ("ש" * 100)
    wa.db.code_snippets.insert_one(_doc("hebrew_crash.txt", code))

    with caplog.at_level(logging.WARNING):
        results = _search(wa, monkeypatch, NEEDLE)

    # בודקים גם את הלוג ולא רק את התוצאות: הפולבאק הישן עשוי להחזיר משהו
    # סביר, ואז אסרשן על התוצאות בלבד היה עובר במקרה.
    assert not [r for r in caplog.records if "primary aggregation" in r.getMessage()], (
        "הצינור המהיר נפל על גבול UTF-8 — זה הבאג עצמו"
    )
    assert len(results) == 1
    assert results[0].snippet_preview == code[51:251]


# --------------------------------------------------------------------------
# מסלול השיתוף
# --------------------------------------------------------------------------


def _share(wa, file_id):
    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
    return client.post(f"/api/share/{file_id}", json={})


def test_a_hebrew_file_is_previewed_at_its_full_length(wired_mongo):
    """כשל שקט בשיתוף: ה-preview חוזר בשני שלישים מאורכו.

    נמדד: ``$substrBytes(code, 0, 2000)`` על 1500 אותיות עבריות (3000 בייטים)
    מחזיר **1000** תווים. בייט 2000 הוא תחילת תו, ולכן אין חריגה — רק חצי
    תוכן.
    """
    wa = wired_mongo
    code = "ש" * 1500
    inserted = wa.db.code_snippets.insert_one(_doc("hebrew_preview.txt", code))

    resp = _share(wa, str(inserted.inserted_id))
    assert resp.status_code == 200, resp.get_data(as_text=True)

    share = wa.db.internal_shares.find_one({"share_id": resp.get_json()["share_id"]})
    assert share is not None, "השיתוף לא נשמר"
    assert len(share["snippet_preview"]) == 1500
    assert share["file_size"] == len(code.encode("utf-8")) == 3000


def test_a_hebrew_file_is_not_reported_as_missing(wired_mongo):
    """**404 שקרי על קובץ שקיים** — הסימפטום הגרוע ביותר ב-#3353.

    נמדד: בייט 2000 של ``"x" + "ש"*1500`` נופל באמצע תו, ומונגו מחזירה
    ``ending index is in the middle of a UTF-8 character`` — בדיוק נוסח
    השגיאה שהופיע בלוג הפרודקשן. ה-``except`` בלע אותה והתשובה הייתה 404.
    """
    wa = wired_mongo
    code = "x" + ("ש" * 1500)
    inserted = wa.db.code_snippets.insert_one(_doc("hebrew_404.txt", code))

    resp = _share(wa, str(inserted.inserted_id))

    assert resp.status_code == 200, (
        "קובץ קיים דווח כלא נמצא: " + resp.get_data(as_text=True)
    )
    share = wa.db.internal_shares.find_one({"share_id": resp.get_json()["share_id"]})
    assert len(share["snippet_preview"]) == 1501

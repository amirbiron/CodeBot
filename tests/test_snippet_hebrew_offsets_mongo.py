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

**גישה למסד: תמיד ``wa.get_db()``, לעולם לא ``wa.db``.** הפיקסצ'ר מאפס את
הגלובל ``wa.db`` ל-``None`` (``tests/conftest.py``) כדי לכפות חיבור מחדש למסד
הזמני; ``get_db()`` הוא זה שמאתחל אותו. גישה ישירה ל-``wa.db`` מקבלת ``None``
ונופלת ב-``AttributeError`` לפני האסרשן הראשון. זה הדפוס בכל שאר הבדיקות
שמשתמשות בפיקסצ'ר.

הרצה מקומית::

    NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \\
        pytest tests/test_snippet_hebrew_offsets_mongo.py -v
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

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
    db = wa.get_db()
    code = ("ש" * 100) + NEEDLE + ("ש" * 100)  # 204 תווים, 408 בייטים
    db.code_snippets.insert_one(_doc("hebrew_silent.txt", code))

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
    db = wa.get_db()
    code = ("ש" * 101) + NEEDLE + ("ש" * 100)
    db.code_snippets.insert_one(_doc("hebrew_crash.txt", code))

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


#
# עד התיקון של הקטיעה בשיתוף, ``POST /api/share/<id>`` חתך את הקובץ באגרגציה
# (``$substrBytes`` ואחר כך ``$substrCP``) ושמר רק את התחלתו. היום השיתוף שומר
# את התוכן המלא ואין בו אגרגציה בכלל — אבל שני הסימפטומים של #3353 נשארים
# שווים בדיקה מול המסד, כי שניהם היו שקטים: קובץ עברי שחוזר חלקי, ו-404 על
# קובץ שקיים. ולצידם הסימפטום של הקטיעה עצמה: עמוד ציבורי שמציג רק את תחילת
# הקובץ, ושיתוף מהבוט שמוצג ריק — זה האחרון נראה מלא מול דמת המונגו כל עוד
# היא התעלמה מהיטלת החרגה, ולכן הוא נבדק כאן מול מסד אמיתי. הגרסה שרצה ב-CI:
# ``tests/test_public_share_full_content.py``.


def _share(wa, file_id):
    client = wa.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "Test"}
    return client.post(f"/api/share/{file_id}", json={"type": "temporary", "permanent": False})


def _md_text(html: str):
    import json
    import re

    match = re.search(r'<script type="application/json" id="mdText">(.*?)</script>', html, re.S)
    assert match, "העמוד לא נשא את בלוק ה-mdText"
    return json.loads(match.group(1))


def test_a_hebrew_file_is_shared_at_its_full_length(wired_mongo):
    """הקישור מציג את כל הקובץ, ולא את 2000 התווים הראשונים שנשמרו בו עד התיקון.

    5000 אותיות עבריות — יותר מפי שניים מהתקרה הישנה, בתווים וגם בבייטים —
    כך שכל חיתוך שיחזור, באיזו יחידה שתהיה, ייראה כאן.
    """
    wa = wired_mongo
    db = wa.get_db()
    code = "ש" * 5000
    doc = _doc("hebrew_share.md", code)
    doc["programming_language"] = "markdown"
    inserted = db.code_snippets.insert_one(doc)

    resp = _share(wa, str(inserted.inserted_id))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    share_id = resp.get_json()["share_id"]

    share = db.internal_shares.find_one({"share_id": share_id})
    assert share is not None, "השיתוף לא נשמר"
    assert share["code"] == code
    # נעילת היקף: גודל קובץ הוא באמת בייטים
    assert share["file_size"] == len(code.encode("utf-8")) == 10000

    page = wa.app.test_client().get(f"/share/{share_id}?view=md")
    assert page.status_code == 200
    assert _md_text(page.get_data(as_text=True)) == code


def test_a_hebrew_file_is_not_reported_as_missing(wired_mongo):
    """**404 שקרי על קובץ שקיים** — הסימפטום הגרוע ביותר ב-#3353.

    נמדד אז: בייט 2000 של ``"x" + "ש"*1500`` נופל באמצע תו, ומונגו מחזירה
    ``ending index is in the middle of a UTF-8 character`` — בדיוק נוסח
    השגיאה שהופיע בלוג הפרודקשן. ה-``except`` בלע אותה והתשובה הייתה 404.
    """
    wa = wired_mongo
    db = wa.get_db()
    code = "x" + ("ש" * 1500)
    inserted = db.code_snippets.insert_one(_doc("hebrew_404.txt", code))

    resp = _share(wa, str(inserted.inserted_id))

    assert resp.status_code == 200, (
        "קובץ קיים דווח כלא נמצא: " + resp.get_data(as_text=True)
    )
    share = db.internal_shares.find_one({"share_id": resp.get_json()["share_id"]})
    assert share["code"] == code


def test_a_share_made_by_the_bot_is_not_an_empty_page(wired_mongo, monkeypatch):
    """הבוט שומר ``code`` מלא בלי תצוגה מקדימה, והעמוד קרא את המסמך בלי ``code``.

    מול מונגו אמיתי זה החזיר עמוד ריק עם 200 — ומול הדמה, שהתעלמה מהיטלת
    החרגה, את הקובץ המלא. השיתוף נוצר דרך הכותב של הבוט עצמו.
    """
    import types
    from urllib.parse import urlparse

    import database
    import integrations

    wa = wired_mongo
    db = wa.get_db()
    # הצורה של ``DatabaseManager``: גם ``internal_shares_collection`` וגם ``db``.
    # מול מונגו אמיתי ``internal_shares_collection or ...`` בכותב זורק (pymongo
    # אוסר בדיקת אמת על ``Collection``), והכותב נופל ל-``_db.db.internal_shares``
    # — כך זה עובד גם בפרודקשן.
    monkeypatch.setattr(
        database, "db",
        types.SimpleNamespace(internal_shares_collection=db.internal_shares, db=db),
        raising=False,
    )
    code = "".join(f"## כותרת {i}\nשורה {i}\n\n" for i in range(300))
    result = integrations.CodeSharingService()._create_internal_share(
        "bot_share.md", code, "markdown", "שיתוף פנימי של bot_share.md",
    )

    page = wa.app.test_client().get(urlparse(result["url"]).path + "?view=md")

    assert page.status_code == 200
    assert _md_text(page.get_data(as_text=True)) == code

"""ערך שנשמר ב-``query_raw`` חוזר מהמסע **כטיפוס שלו**, ולא כמחרוזת.

**למה זה נבדק דרך הראוטים ולא דרך השירות.** ה-``explain`` לא רץ על מה שהשירות
שמר — הוא רץ על מה שחזר מהדפדפן. המסע המלא הוא: הרשומה ← ``/api/profiler/slow-queries``
← הדפדפן ← ``/api/profiler/recommendations`` ← ``explain``. הכשל שהסבב הזה מתקן
חי **בין** שני הראוטים האלה, ולכן טסט ברמת השירות לא היה רואה אותו: השירות שמר
``datetime`` תקין, ו-``jsonify`` הפך אותו למחרוזת HTTP-date בדרך החוצה.

**מה זה עולה, במספרים.** נמדד מול הקלאסטר על ``code_snippets``:
``created_at < <תאריך אמיתי>`` מתאים ל-1,157 מסמכים; אותו תאריך כמחרוזת
(``"Sun, 06 Sep 2026 12:00:00 GMT"``, מה ש-Flask פולט) מתאים ל-**0**. כלומר
ה-``explain`` היה מתאר שאילתה מהירה עם אפס סריקה ויעילות מושלמת — דוח שנראה
מצוין ומסקנתו הפוכה. זה גרוע מ-``<value>``, כי ``<value>`` **נראה** שבור.

הטסטים כאן לא נוגעים ב-DB ולא ברשת: אוסף דמה בזיכרון ושירות מזויף.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from bson import ObjectId

WHEN = datetime(2026, 9, 6, 12, 0, 0)
OID = ObjectId("6a8e6c04cfb3849504b6e210")
ME = 6865105071

#: הצורה האמיתית מהפרודקשן — העמוד השני של ``/files``, זו שהובילה לסבב 292.
RAW_QUERY = {
    "user_id": ME,
    "$and": [
        {"is_active": True},
        {"$or": [
            {"created_at": {"$lt": WHEN}},
            {"$and": [{"created_at": {"$eq": WHEN}}, {"_id": {"$lt": OID}}]},
        ]},
    ],
}


class _Record:
    """מה ש-``_serialize_slow_query`` קורא. לא ``SlowQueryRecord`` אמיתי בכוונה —

    הטסט בודק את **שכבת ההגשה**, ובניית רשומה אמיתית הייתה גוררת לכאן את כל
    מסלול ההחלטה על הערכים, שנבדק במקום אחר.
    """

    query_id = "q1"
    collection = "code_snippets"
    operation = "find"
    query_shape = {"user_id": "<value>"}
    query_raw = RAW_QUERY
    raw_withheld_reason = None
    execution_time_ms = 1500.0
    timestamp = WHEN


@pytest.fixture
def app_module(monkeypatch):
    import webapp.app as webapp_app

    monkeypatch.setattr(webapp_app, "_profiler_is_authorized", lambda: True, raising=True)
    monkeypatch.setattr(webapp_app, "_profiler_rate_limit_ok", lambda: True, raising=True)
    return webapp_app


@pytest.fixture
def seen(monkeypatch, app_module):
    """מה שהשירות באמת קיבל מהראוט — הדלת שאחריה רץ ה-``explain``."""
    captured = {}

    class _Svc:
        def get_slow_queries_page(self, **kwargs):
            return {"records": [_Record()], "total": 1, "next_cursor": None}

        def get_explain_plan(self, *, collection, query, verbosity):
            captured["query"] = query
            raise RuntimeError("stop-here")

    monkeypatch.setattr(app_module, "_get_webapp_profiler_service", lambda: _Svc(), raising=True)
    return captured


def test_the_api_sends_the_type_and_not_a_string(app_module, seen):
    """מה שיוצא לדפדפן נושא ``{"$date": …}`` ולא מחרוזת תאריך."""
    with app_module.app.test_client() as client:
        resp = client.get("/api/profiler/slow-queries")

    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    raw = resp.get_json()["data"][0]["query_raw"]
    inner = raw["$and"][1]["$or"][0]["created_at"]["$lt"]

    assert isinstance(inner, dict) and "$date" in inner, (
        f"התאריך יצא כ-{inner!r} — כמחרוזת הוא מתאים ל-0 מסמכים במקום 1,157"
    )
    assert raw["$and"][1]["$or"][1]["$and"][1]["_id"]["$lt"] == {"$oid": str(OID)}


def test_what_the_browser_sends_back_arrives_as_real_types(app_module, seen):
    """הסיבוב המלא: מה שיצא מהראוט הראשון, מוחזר לשני, מגיע כטיפוס."""
    with app_module.app.test_client() as client:
        outgoing = client.get("/api/profiler/slow-queries").get_json()["data"][0]["query_raw"]
        client.post(
            "/api/profiler/recommendations",
            json={"collection": "code_snippets", "query": outgoing, "encoding": "extended_json"},
        )

    assert seen["query"] == RAW_QUERY, "מה שהגיע ל-explain אינו מה שרץ בפרודקשן"
    assert isinstance(seen["query"]["$and"][1]["$or"][0]["created_at"]["$lt"], datetime)
    assert isinstance(seen["query"]["$and"][1]["$or"][1]["$and"][1]["_id"]["$lt"], ObjectId)


def test_without_the_declared_encoding_nothing_is_decoded(app_module, seen):
    """ברירת המחדל היא ``json``, וההתנהגות שם זהה לקודם — במכוון.

    זה גם מה שמראה שהדגל אינו קישוט: בלעדיו אותו גוף בדיוק מגיע כמילון
    ``{"$date": …}`` ולא כתאריך. הפענוח **מוצהר** ולא מוסק, כי זיהוי אוטומטי
    היה מופעל גם על השלד המנורמל — ושם ``{"$options": "<value>"}`` הופך בשקט
    ל-``Regex`` עם דגלים אקראיים במקום לייצר שגיאה רועשת ממונגו.
    """
    with app_module.app.test_client() as client:
        outgoing = client.get("/api/profiler/slow-queries").get_json()["data"][0]["query_raw"]
        client.post(
            "/api/profiler/recommendations",
            json={"collection": "code_snippets", "query": outgoing},
        )

    assert seen["query"]["$and"][1]["$or"][0]["created_at"]["$lt"] == {"$date": "2026-09-06T12:00:00Z"}


def test_an_unknown_encoding_is_rejected_and_not_guessed(app_module, seen):
    with app_module.app.test_client() as client:
        resp = client.post(
            "/api/profiler/recommendations",
            json={"collection": "code_snippets", "query": {}, "encoding": "bson"},
        )

    assert resp.status_code == 400
    assert resp.get_json()["message"] == "invalid_encoding"
    assert "query" not in seen, "הבקשה לא הייתה אמורה להגיע לשירות בכלל"


@pytest.mark.parametrize("bad", [["json"], {"a": 1}, 5, None])
def test_a_non_string_encoding_is_a_400_and_not_a_crash(app_module, seen, bad):
    """קלט לא תקין הוא 400, גם כשהוא מהטיפוס הלא נכון.

    ``encoding not in frozenset`` קורא ל-``hash()``, ורשימה או מילון מגוף
    ה-JSON זורקים שם ``TypeError`` — כלומר 500 על קלט משתמש. זה מופע של
    ``CORE-PATTERNS`` U3: פעולה שמניחה טיפוס על ערך שהגיע מחוץ לתהליך.
    הפרמטרים מכסים את שני הצדדים — ``list``/``dict`` שזרקו, ו-``int``/``None``
    שנדחו נכון גם קודם.
    """
    with app_module.app.test_client() as client:
        resp = client.post(
            "/api/profiler/recommendations",
            json={"collection": "code_snippets", "query": {}, "encoding": bad},
        )

    assert resp.status_code == 400, resp.get_data(as_text=True)[:300]
    assert resp.get_json()["message"] == "invalid_encoding"
    assert "query" not in seen


def test_a_record_without_raw_values_still_serializes(app_module, monkeypatch):
    """``None`` נשאר ``None`` — אין ערכים, אין מה לקודד."""

    class _Empty(_Record):
        query_raw = None
        raw_withheld_reason = "owner_missing"

    class _Svc:
        def get_slow_queries_page(self, **kwargs):
            return {"records": [_Empty()], "total": 1, "next_cursor": None}

    monkeypatch.setattr(app_module, "_get_webapp_profiler_service", lambda: _Svc(), raising=True)

    with app_module.app.test_client() as client:
        row = client.get("/api/profiler/slow-queries").get_json()["data"][0]

    assert row["query_raw"] is None
    assert row["raw_withheld_reason"] == "owner_missing"

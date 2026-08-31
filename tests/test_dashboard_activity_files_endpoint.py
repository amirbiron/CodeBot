"""‏"טען עוד" בהיסטוריית הפעולות מציג קבצים, לא מסמכי גרסה.

**למה זה קיים.** כל עריכה יוצרת מסמך חדש ב-``code_snippets``. הטיימליין
הראשי מקבץ לפי שם קובץ ומציג שורה אחת לקובץ, אבל ה-endpoint שמאחורי
הכפתור היה עותק נפרד שלא קובץ — הוא עשה ``find(...).skip(offset)`` על
מסמכי הגרסה הגולמיים.

**והפער היה מדיד בשרשרת שלמה:** המונה שהכפתור מציג נספר בקבצים,
ה-``data-offset`` שהלקוח שולח הוא מספר האירועים שהוצגו — כלומר קבצים —
וה-endpoint דילג עליו על זרם של מסמכים. קובץ עם שלוש גרסאות: הטיימליין
מציג שורה אחת, ולחיצה על "טען עוד" החזירה את גרסאות 2 ו-3 של אותו קובץ
כשורות חדשות.

זה לא נתפס כי ל-endpoint לא הייתה שום בדיקה.
"""

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

pytest.importorskip("flask")

USER_ID = 7


def _seed_versions(wired_mongo, file_name="amir.md", versions=3):
    """קובץ אחד עם כמה גרסאות, כולן בטווח שבעת הימים."""
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    now = datetime.now(timezone.utc)
    for v in range(1, versions + 1):
        db.code_snippets.insert_one({
            "_id": ObjectId(),
            "user_id": USER_ID,
            "file_name": file_name,
            "code": f"# גרסה {v}",
            "programming_language": "markdown",
            "version": v,
            "is_active": True,
            # ``created_at`` אחיד לכל הגרסאות, כמו אחרי תיקון הירושה
            "created_at": now - timedelta(days=14),
            "updated_at": now - timedelta(minutes=versions - v),
        })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    return client


def test_load_more_does_not_return_older_versions_of_the_same_file(wired_mongo):
    """‏offset=1 על קובץ עם שלוש גרסאות אינו מחזיר את גרסאות 2 ו-3.

    זו הטענה המרכזית. הטיימליין הראשי הציג שורה אחת עבור הקובץ הזה, ולכן
    הלקוח שולח ``offset=1``; אם ה-endpoint מדלג על **מסמך** אחד במקום על
    **קובץ** אחד, הוא מחזיר את אותו קובץ שוב.
    """
    client = _seed_versions(wired_mongo, versions=3)

    resp = client.get("/api/dashboard/activity/files?offset=1&limit=12")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    data = resp.get_json()
    assert data.get("ok") is True, data

    titles = [ev.get("title") for ev in data.get("events", [])]
    assert titles == [], f"הוחזרו כפילויות של אותו קובץ: {titles}"


def test_the_endpoint_counts_files_not_version_documents(wired_mongo):
    """‏``total_recent`` נספר באותה יחידה שבה נספרות השורות המוצגות.

    המונה הזה מזין את הטקסט על הכפתור ואת ``remaining``. כשהוא סופר
    מסמכים והשורות הן קבצים, הכפתור מבטיח יותר ממה שיתקבל.
    """
    client = _seed_versions(wired_mongo, versions=3)

    data = client.get("/api/dashboard/activity/files?offset=0&limit=12").get_json()
    assert data["total_recent"] == 1, data
    assert len(data["events"]) == 1, [e.get("title") for e in data["events"]]
    assert data["remaining"] == 0, data
    assert data["has_more"] is False, data


def test_the_endpoint_agrees_with_the_dashboard_timeline(wired_mongo):
    """שני המסלולים חייבים להסכים — הם הצדדים של אותו כפתור.

    מונה שנחשב בשתי דרכים הוא בדיוק מה שנשבר כאן, ולכן הבדיקה משווה את
    ה-endpoint לטיימליין הראשי במקום לקבע מספר.
    """
    import webapp.app as wa

    client = _seed_versions(wired_mongo, versions=3)
    # קובץ שני, כדי שהשוואה של אחד-מול-אחד לא תעבור במקרה
    wired_mongo.get_db().code_snippets.insert_one({
        "_id": ObjectId(), "user_id": USER_ID, "file_name": "other.py",
        "code": "print(1)", "programming_language": "python", "version": 1,
        "is_active": True,
        "created_at": datetime.now(timezone.utc) - timedelta(hours=1),
        "updated_at": datetime.now(timezone.utc) - timedelta(hours=1),
    })

    timeline = wa._build_activity_timeline(
        wired_mongo.get_db(), user_id=USER_ID, active_query=None,
        now=datetime.now(timezone.utc),
    )
    files_group = {g["id"]: g for g in timeline["groups"]}["files"]

    data = client.get("/api/dashboard/activity/files?offset=0&limit=12").get_json()

    assert data["total_recent"] == files_group["total_recent"], (
        data["total_recent"], files_group["total_recent"])
    assert len(data["events"]) == len(files_group["events"])

    # השוואה שדה-שדה ולא רק לפי כותרת: ``icon_lang`` הוא מה שצד הלקוח
    # משתמש בו כדי לבנות את האייקון, וסחיפה בו היא בדיוק הרגרסיה שקרתה
    # בעבר — אמוג'ים שנכנסו לרשימה של אייקונים מצוירים ב"טען עוד".
    for key in ("title", "subtitle", "icon_lang", "badge", "badge_variant", "href"):
        assert [e.get(key) for e in data["events"]] == \
               [e.get(key) for e in files_group["events"]], key

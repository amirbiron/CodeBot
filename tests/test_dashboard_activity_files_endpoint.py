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


def _titles(client, offset=0, limit=12):
    data = client.get(f"/api/dashboard/activity/files?offset={offset}&limit={limit}").get_json()
    return [e.get("title") for e in data.get("events", [])], data


def test_a_file_without_updated_at_is_not_pushed_to_the_bottom(wired_mongo):
    """קובץ בלי ``updated_at`` ממוין לפי ``created_at``, ולא נופל לסוף.

    ה-``$match`` מכליל אותו — שניים מענפי ה-``$or`` קיימים בדיוק בשבילו —
    אבל מונגו משווה שדה חסר כאילו היה ``null``, ו-``null`` נמוך מ-``Date``
    בסדר ההשוואה של BSON. כלומר מיון יורד על ``updated_at`` לבדו היה
    מטביע קובץ טרי מתחת לכל מי שיש לו חותמת.
    """
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    now = datetime.now(timezone.utc)

    # ישן, אבל יש לו updated_at
    db.code_snippets.insert_one({
        "_id": ObjectId(), "user_id": USER_ID, "file_name": "old.py",
        "code": "x", "programming_language": "python", "version": 1, "is_active": True,
        "created_at": now - timedelta(days=3), "updated_at": now - timedelta(days=3),
    })
    # טרי, בלי updated_at כלל
    db.code_snippets.insert_one({
        "_id": ObjectId(), "user_id": USER_ID, "file_name": "fresh.py",
        "code": "y", "programming_language": "python", "version": 1, "is_active": True,
        "created_at": now - timedelta(minutes=5),
    })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}

    titles, data = _titles(client)
    assert len(titles) == 2, data
    assert titles[0].endswith("fresh.py"), f"הקובץ הטרי לא הופיע ראשון: {titles}"


def test_pagination_is_stable_when_timestamps_are_equal(wired_mongo):
    """שני קבצים עם ``updated_at`` **זהה** מדפדפים בלי כפילות ובלי דילוג.

    ‏``$sort`` אינו יציב, ולכן מפתח מיון לא ייחודי נותן סדר אחר בין
    קריאות — ועם ``$skip`` זה מתורגם לשורה שחוזרת פעמיים ולשורה שנעלמת.
    """
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    same = datetime.now(timezone.utc) - timedelta(hours=1)
    for name in ("a.py", "b.py", "c.py"):
        db.code_snippets.insert_one({
            "_id": ObjectId(), "user_id": USER_ID, "file_name": name,
            "code": "x", "programming_language": "python", "version": 1,
            "is_active": True, "created_at": same, "updated_at": same,
        })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}

    # אותו סדר בשתי קריאות זהות
    first, _ = _titles(client)
    again, _ = _titles(client)
    assert first == again, f"הסדר השתנה בין שתי קריאות זהות: {first} / {again}"

    # ודפדוף עמוד-עמוד מכסה את כל השלושה, בלי חזרות
    paged = []
    for off in range(3):
        page, _ = _titles(client, offset=off, limit=1)
        paged.extend(page)
    assert len(paged) == len(set(paged)) == 3, f"כפילות או דילוג בדפדוף: {paged}"
    assert sorted(paged) == sorted(first), (paged, first)


def test_a_failed_count_does_not_hide_the_load_more_button(wired_mongo, monkeypatch):
    """כשל בספירה אינו מסתיר קבצים שקיימים.

    צד הלקוח מסיר את הכפתור כשהוא מקבל ``remaining`` אפס
    (``dashboard.html``: ``parseInt(remaining || '0')`` ואז ``rem <= 0``),
    ולכן ספירה שנבלעת לאפס הייתה מסתירה מהמשתמש את שאר הקבצים.
    """
    import webapp.app as wa

    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.code_snippets.insert_one({
            "_id": ObjectId(), "user_id": USER_ID, "file_name": f"f{i}.py",
            "code": "x", "programming_language": "python", "version": 1,
            "is_active": True, "created_at": now, "updated_at": now - timedelta(minutes=i),
        })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}

    monkeypatch.setattr(wa, "_timeline_recent_files_count", lambda *a, **k: None)

    # עמוד מלא (limit=2 מתוך 3) — הכפתור חייב לשרוד
    data = client.get("/api/dashboard/activity/files?offset=0&limit=2").get_json()
    assert data["ok"] is True, data
    assert len(data["events"]) == 2, data
    assert data["total_recent"] is None, "הספירה לא ידועה — אסור לדווח מספר"
    assert data["remaining"] > 0, f"הכפתור נעלם למרות שהעמוד התמלא: {data}"
    assert data["has_more"] is True, data

    # עמוד חלקי — סיימנו ממילא
    tail = client.get("/api/dashboard/activity/files?offset=2&limit=2").get_json()
    assert len(tail["events"]) == 1, tail
    assert tail["remaining"] == 0, tail
    assert tail["has_more"] is False, tail


def test_an_exact_page_multiple_does_not_offer_an_empty_click(wired_mongo, monkeypatch):
    """מספר קבצים שהוא כפולה מדויקת של גודל העמוד אינו מציג לחיצת סרק.

    קודם הוסק "יש עוד" מכך שהעמוד התמלא, ולכן ארבעה קבצים ב-``limit=4``
    הציגו "טען עוד 1" — ולחיצה עליו החזירה רשימה ריקה. עכשיו נשלפת שורה
    אחת מעבר לעמוד, וקיומה (או היעדרה) הוא התשובה.

    הבדיקה רצה במסלול שבו הספירה נכשלה, כי שם ההחלטה נשענה על האומדן.
    """
    import webapp.app as wa

    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    now = datetime.now(timezone.utc)
    for i in range(4):
        db.code_snippets.insert_one({
            "_id": ObjectId(), "user_id": USER_ID, "file_name": f"f{i}.py",
            "code": "x", "programming_language": "python", "version": 1,
            "is_active": True, "created_at": now, "updated_at": now - timedelta(minutes=i),
        })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}

    monkeypatch.setattr(wa, "_timeline_recent_files_count", lambda *a, **k: None)

    page = client.get("/api/dashboard/activity/files?offset=0&limit=4").get_json()
    assert len(page["events"]) == 4, page
    assert page["has_more"] is False, "הובטחה לחיצה נוספת על עמוד שאין אחריו כלום"
    assert page["remaining"] == 0, page

    # ולראיה: הלחיצה שהייתה מוצעת אכן מחזירה ריק
    nxt = client.get(f"/api/dashboard/activity/files?offset={page['next_offset']}&limit=4").get_json()
    assert nxt["events"] == [], nxt


def test_more_files_than_one_page_still_offers_the_button(wired_mongo, monkeypatch):
    """הכיוון ההפוך — אחרת התיקון היה מסתיר את הכפתור תמיד."""
    import webapp.app as wa

    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    now = datetime.now(timezone.utc)
    for i in range(5):
        db.code_snippets.insert_one({
            "_id": ObjectId(), "user_id": USER_ID, "file_name": f"g{i}.py",
            "code": "x", "programming_language": "python", "version": 1,
            "is_active": True, "created_at": now, "updated_at": now - timedelta(minutes=i),
        })

    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = USER_ID
        sess["user_data"] = {"id": USER_ID, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}

    monkeypatch.setattr(wa, "_timeline_recent_files_count", lambda *a, **k: None)

    page = client.get("/api/dashboard/activity/files?offset=0&limit=4").get_json()
    assert len(page["events"]) == 4, page
    assert page["has_more"] is True, page
    nxt = client.get(f"/api/dashboard/activity/files?offset={page['next_offset']}&limit=4").get_json()
    assert len(nxt["events"]) == 1, nxt

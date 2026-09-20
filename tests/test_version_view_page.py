"""גרסה קודמת היא עמוד שאפשר לפתוח — ומה שנלווה לזה.

**למה זה קיים.** ``/file/<id>`` תמיד שלף לפי ``_id`` בלבד, וכל גרסה היא
מסמך נפרד ב-``code_snippets``. כלומר העמוד *כבר* ידע להציג גרסה ישנה,
ומה שחסר היה הדרך להגיע לשם והסימון שמה שרואים אינו העדכני. הבדיקות
כאן מגנות על הסימון ועל תופעות הלוואי שהוא מחייב, לא על יכולת הרינדור —
היא לא נכתבה מחדש, ובזה כל העניין.

הכול מול מונגו אמיתי ודרך ה-HTTP client, כי הטענות הן על מה שהראוט
עושה למסד ועל מה שיוצא ב-HTML — ודמה מחזירה את מה שכתבו בה.
"""

import pytest
from bson import ObjectId

pytest.importorskip("flask")

USER_ID = 4242
OTHER_USER_ID = 9999

BANNER_MARK = "אתה צופה בגרסה"
TRASH_MARK = "הקובץ נמצא בסל המיחזור"
RESTORE_MARK = "versionBannerRestore"


def _client(wired_mongo, user_id=USER_ID):
    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        # ``view_file`` מרנדר את ``session['user_data']`` ישירות.
        sess["user_data"] = {"id": user_id, "first_name": "בדיקה",
                             "is_admin": False, "is_premium": False}
    return client


def _seed(
    wired_mongo,
    versions=3,
    user_id=USER_ID,
    name="amir.py",
    is_active=True,
    code_for=None,
    language="python",
):
    """יוצר שרשרת גרסאות ומחזיר ``{מספר גרסה: מזהה מחרוזת}``."""
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    db.large_files.delete_many({})
    db.recent_opens.delete_many({})
    ids = {}
    for version in range(1, versions + 1):
        oid = ObjectId()
        code = code_for(version) if code_for else f"print({version})\n"
        db.code_snippets.insert_one({
            "_id": oid,
            "user_id": user_id,
            "file_name": name,
            "code": code,
            "programming_language": language,
            "version": version,
            "is_active": is_active,
        })
        ids[version] = str(oid)
    return ids


# ---------------------------------------------------------------- הבאנר


def test_an_old_version_page_shows_which_version_it_is(wired_mongo):
    ids = _seed(wired_mongo, versions=3)
    body = _client(wired_mongo).get(f"/file/{ids[1]}").get_data(as_text=True)
    assert "גרסה 1 מתוך 3" in body, "עמוד הגרסה הישנה אינו אומר שהיא ישנה"


def test_the_latest_version_page_carries_no_banner(wired_mongo):
    ids = _seed(wired_mongo, versions=3)
    resp = _client(wired_mongo).get(f"/file/{ids[3]}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert BANNER_MARK not in body, "באנר גרסה ישנה הופיע על הגרסה העדכנית"


def test_an_old_version_of_another_users_file_is_not_found(wired_mongo):
    """הבעלות נאכפת בפילטר של מונגו, ולכן גרסה ישנה מקבלת אותה הגנה."""
    ids = _seed(wired_mongo, versions=3, user_id=OTHER_USER_ID)
    assert _client(wired_mongo).get(f"/file/{ids[1]}").status_code == 404


def test_html_inside_an_old_version_is_escaped(wired_mongo):
    """אין מסלול רינדור שני — ולכן גם אין מסלול הברחה שני.

    הטסט מוודא את התוצאה ולא את המנגנון: הסקריפט אינו יוצא כמו שהוא.
    """
    payload = "<script>alert(1)</script>"
    ids = _seed(wired_mongo, versions=2,
                code_for=lambda v: payload if v == 1 else "clean\n")
    body = _client(wired_mongo).get(f"/file/{ids[1]}").get_data(as_text=True)
    assert payload not in body, "תוכן הגרסה הישנה יצא בלי הברחה"
    assert "alert(1)" in body, "התוכן כלל לא הוצג"


# ------------------------------------------------- פעולות שמשנות מצב


def test_state_changing_actions_are_hidden_on_an_old_version(wired_mongo):
    """עריכה, מחיקה, נעיצה ושיתוף פועלים על ה-``_id`` שבכתובת.

    על עמוד של גרסה ישנה ה-``_id`` הזה הוא המסמך הישן, ולכן הן מוסתרות.
    """
    ids = _seed(wired_mongo, versions=3)
    client = _client(wired_mongo)

    old = client.get(f"/file/{ids[1]}").get_data(as_text=True)
    current = client.get(f"/file/{ids[3]}").get_data(as_text=True)

    assert f'/edit/{ids[3]}' in current, "כפתור העריכה נעלם גם מהגרסה הנוכחית"
    assert f'/edit/{ids[1]}' not in old, "אפשר לערוך גרסה ישנה"
    assert 'data-menu-action="trash"' in current
    assert 'data-menu-action="trash"' not in old, "אפשר להעביר גרסה ישנה לסל"
    assert 'data-menu-action="share"' not in old
    assert 'id="favoriteBtn"' not in old


def test_viewing_an_old_version_does_not_move_recently_opened(wired_mongo):
    """``last_opened_file_id`` נקרא מאוחר יותר כדי לפתוח את הקובץ.

    בלי הדילוג, "נפתחו לאחרונה" היה מתחיל להוביל לגרסה הישנה.
    """
    ids = _seed(wired_mongo, versions=3)
    db = wired_mongo.get_db()
    client = _client(wired_mongo)

    client.get(f"/file/{ids[3]}")
    after_current = db.recent_opens.find_one({"user_id": USER_ID})
    assert after_current is not None, "צפייה בגרסה הנוכחית לא נרשמה כלל"
    assert str(after_current.get("last_opened_file_id")) == ids[3]

    client.get(f"/file/{ids[1]}")
    after_old = db.recent_opens.find_one({"user_id": USER_ID})
    assert str(after_old.get("last_opened_file_id")) == ids[3], (
        "צפייה בגרסה ישנה הזיזה את 'נפתחו לאחרונה' אליה"
    )


def test_the_etag_changes_when_a_newer_version_is_added(wired_mongo):
    """הבאנר נושא את מספר הגרסה האחרונה, שאינו נגזר מהמסמך המוצג.

    בלי שהוא ייכנס לוולידטור, ``If-None-Match`` היה מחזיר 304 ומגיש
    "גרסה 1 מתוך 3" אחרי שכבר יש 4.
    """
    ids = _seed(wired_mongo, versions=3)
    client = _client(wired_mongo)
    etag_before = client.get(f"/file/{ids[1]}").headers["ETag"]

    unchanged = client.get(f"/file/{ids[1]}", headers={"If-None-Match": etag_before})
    assert unchanged.status_code == 304, "הוולידטור אינו עובד כלל"

    wired_mongo.get_db().code_snippets.insert_one({
        "_id": ObjectId(), "user_id": USER_ID, "file_name": "amir.py",
        "code": "print(4)\n", "programming_language": "python",
        "version": 4, "is_active": True,
    })
    fresh = client.get(f"/file/{ids[1]}", headers={"If-None-Match": etag_before})
    assert fresh.status_code == 200, "304 עם באנר ישן אחרי שנוספה גרסה"
    assert "גרסה 1 מתוך 4" in fresh.get_data(as_text=True)


# ------------------------------------------------------- מקרי קצה


def test_a_file_in_the_trash_offers_the_trash_and_not_a_version_restore(wired_mongo):
    """העברה לסל מסמנת את **כל** הגרסאות, ולכן אין "גרסה אחרונה פעילה".

    שחזור גרסה היה מוסיף גרסה פעילה לקובץ שאמור להיות מחוק; הפעולה
    הנכונה היא שחזור הקובץ מהסל, והיא כבר קיימת.
    """
    ids = _seed(wired_mongo, versions=3, is_active=False)
    body = _client(wired_mongo).get(f"/file/{ids[1]}").get_data(as_text=True)
    assert TRASH_MARK in body
    assert RESTORE_MARK not in body, "הוצע לשחזר גרסה של קובץ שבסל"
    assert BANNER_MARK not in body


def test_a_large_file_page_has_no_banner_and_does_not_raise(wired_mongo):
    """``large_files`` הוא אוסף דריסה ואין בו שדה ``version`` בכלל."""
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    db.large_files.delete_many({})
    oid = ObjectId()
    db.large_files.insert_one({
        "_id": oid, "user_id": USER_ID, "file_name": "big.txt",
        "content": "x" * 50, "programming_language": "text", "is_active": True,
    })
    resp = _client(wired_mongo).get(f"/file/{oid}")
    assert resp.status_code == 200
    assert BANNER_MARK not in resp.get_data(as_text=True)


def test_a_large_file_is_never_matched_against_a_snippet_of_the_same_name(wired_mongo):
    """שני אוספים, שני עולמות — ושם קובץ אינו מזהה חוצה-אוסף.

    ``large_files`` הוא אוסף דריסה ואין בו ``version``; ``code_snippets``
    הוא append ויש בו. בלי השומר על סוג המסמך, קובץ גדול בשם ``shared.md``
    היה נמדד מול שרשרת הגרסאות של קובץ **אחר** בשם הזהה — והמשתמש היה
    מקבל "אתה צופה בגרסה 1 מתוך 3" על קובץ שאין לו גרסאות בכלל.

    הגרסה הראשונה של הבדיקה הזו ספרה שאילתות, ובדיקת מוטציה הראתה
    שהיא עוברת גם בלי השומר — כי ``version`` החסר עוצר קודם. זו הבדיקה
    שבאמת מתארת את מה שהשומר מונע.
    """
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    db.large_files.delete_many({})

    for version in (1, 2, 3):
        db.code_snippets.insert_one({
            "_id": ObjectId(), "user_id": USER_ID, "file_name": "shared.md",
            "code": f"# גרסה {version}\n", "programming_language": "markdown",
            "version": version, "is_active": True,
        })

    large_id = ObjectId()
    db.large_files.insert_one({
        "_id": large_id, "user_id": USER_ID, "file_name": "shared.md",
        "content": "x" * 50, "programming_language": "markdown",
        "is_active": True,
        # שדה תועה: אם מישהו יוסיף אותו אי פעם, השומר הוא מה שמונע
        # מהקובץ הגדול להימדד מול שרשרת של אוסף אחר.
        "version": 1,
    })

    resp = _client(wired_mongo).get(f"/file/{large_id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert BANNER_MARK not in body, "קובץ גדול נמדד מול גרסאות של קובץ אחר"


def test_the_public_share_page_never_shows_the_banner(wired_mongo):
    """``/share/<id>`` מרנדר את אותן תבניות בלי ``version_context``.

    "משתנה לא מוגדר הוא שקרי" נראה כמו הגנה ואינו כזו, ולכן זה נבדק.
    """
    db = wired_mongo.get_db()
    db.internal_shares.delete_many({})
    db.internal_shares.insert_one({
        "share_id": "sh-test-1",
        "file_name": "readme.md",
        "code": "# כותרת\n",
        "language": "markdown",
    })
    client = wired_mongo.app.test_client()
    for url in ("/share/sh-test-1", "/share/sh-test-1?view=md"):
        body = client.get(url).get_data(as_text=True)
        assert BANNER_MARK not in body, f"באנר במסלול הציבורי: {url}"
        assert TRASH_MARK not in body, f"הערת סל במסלול הציבורי: {url}"
        assert RESTORE_MARK not in body, f"כפתור שחזור במסלול הציבורי: {url}"


# --------------------------------------------------------- Markdown


def test_the_markdown_view_of_an_old_version_shows_the_banner(wired_mongo):
    ids = _seed(wired_mongo, versions=3, name="readme.md", language="markdown",
                code_for=lambda v: f"# גרסה {v}\n")
    body = _client(wired_mongo).get(f"/md/{ids[1]}").get_data(as_text=True)
    assert "גרסה 1 מתוך 3" in body


def test_an_old_markdown_version_is_not_written_to_the_cache(wired_mongo, monkeypatch):
    """ייצוג שתלוי במשהו שמחוץ למפתח אינו אמור להישמר.

    ה-HTML של גרסה ישנה נושא את מספר הגרסה האחרונה, שמשתנה בכל שמירה
    ואינו חלק ממפתח הקאש. עמוד הגרסה הנוכחית אינו נושא באנר, ולכן
    ממשיך להישמר — וזה מה שהחצי השני של הבדיקה מוודא.
    """
    ids = _seed(wired_mongo, versions=3, name="readme.md", language="markdown",
                code_for=lambda v: f"# גרסה {v}\n")

    stored = []

    class _Cache:
        is_enabled = True

        def get(self, key):
            return None

        def set_dynamic(self, key, value, *args, **kwargs):
            stored.append(key)

        def set(self, key, value, *args, **kwargs):
            stored.append(key)

    monkeypatch.setattr(wired_mongo, "cache", _Cache())
    client = _client(wired_mongo)

    client.get(f"/md/{ids[3]}")
    assert stored, "גם עמוד הגרסה הנוכחית הפסיק להישמר בקאש"

    stored.clear()
    client.get(f"/md/{ids[1]}")
    assert not stored, "עמוד של גרסה ישנה נשמר בקאש"

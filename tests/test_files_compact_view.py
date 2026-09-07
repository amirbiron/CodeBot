"""תצוגה מצומצמת בעמוד הקבצים — ההעדפה, הרינדור, ומפתח הקאש.

הפיצ'ר מסתיר מכרטיס הקובץ את אייקון השפה, מספר השורות, הגודל, התיאור,
התאריכים וכפתור ההורדה. הבאדג' של השפה, התגיות, שם הקובץ, צ'קבוקס הבחירה
ושאר הכפתורים נשארים.

**המלכודת שהבדיקות כאן קיימות בשבילה.** ``/files`` שומר את ה-HTML המרונדר
ב-Redis, והמפתח נבנה מפרמטרי החיפוש בלבד. העדפה שמרונדרת לתוך ה-HTML ואינה
במפתח פירושה שמשתמש שמדליק את המתג מקבל את ה-HTML של המצב הקודם עד שה-TTL
פוקע — הוא יסיק שהפיצ'ר שבור. אין בקוד שום מקום שמבטל את ``web:files:user:*``.

**ומלכודת שנייה, מתועדת בריפו.** מפתח שאינו מטופל במפורש ב-``/api/ui_prefs``
מקבל 200 ואינו נשמר. ``docs/webapp/smooth-scrolling.rst`` מתעד את ``smooth_scroll``
שנשלח מהלקוח עד היום ומעולם לא נשמר. לכן בדיקת השמירה כאן קוראת את מה שנכתב
בפועל, ולא מסתפקת בסטטוס התשובה.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from webapp import app as webapp_app

#: הערך שמזהה את אייקון השפה של הכרטיס. ``width="44"`` הוא מה שמבדיל אותו
#: משני המופעים האחרים של ``lang-icon`` בעמוד, שהם מחרוזות בתוך ה-JS של
#: ``base.html`` ובונות את הרוחב בזמן ריצה. נמדד, לא הונח.
CARD_LANG_ICON = '<svg class="lang-icon" width="44"'

#: העוגנים בכרטיס. ``data-testid`` מתאר את המצב שרונדר ולא את הניסוח, לפי
#: ``docs/webapp/theming_and_css.rst`` — כדי ששינוי טקסט בעברית לא יפיל בדיקה.
HIDDEN_IN_COMPACT = (
    'data-testid="file-card-lines"',
    'data-testid="file-card-size"',
    'data-testid="file-card-description"',
    'data-testid="file-card-dates"',
    'data-testid="file-card-download"',
)

FILE_DOC = {
    "_id": "0123456789abcdef01234567",
    "file_name": "demo.py",
    "programming_language": "python",
    "description": "תיאור לדוגמה",
    "tags": ["alpha"],
    "file_size": 11571,
    "lines_count": 143,
    "created_at": datetime(2026, 2, 10, tzinfo=timezone.utc),
    "updated_at": datetime(2026, 3, 11, tzinfo=timezone.utc),
}


# ---------------------------------------------------------------------------
# דמויות מקרטון
# ---------------------------------------------------------------------------

class _Snippets:
    """דמה שמחזירה מסמך אחד קבוע, בלי קשר לתוכן ה-pipeline.

    **מה זה אומר על הכיסוי, במפורש:** בדיקות הרינדור למטה מוכיחות את שכבת
    התבנית בלבד — מה שהראוט עושה עם הדגל. הן **אינן** מכסות את הסינון,
    המיון, העימוד או צינור ה-aggregation של ``/files``, כי הדמה מתעלמת
    מהם. שבירה שם לא תיתפס כאן, ובכוונה: הפיצ'ר הזה אינו נוגע בשאילתה.
    זו אותה דמה שבה משתמשת ``tests/test_webapp_files_aggregate_allow_disk_use.py``,
    שהיא זו שכן בודקת את ה-pipeline.
    """

    def aggregate(self, pipeline, **_kwargs):
        if any(isinstance(stage, dict) and "$count" in stage for stage in pipeline):
            return [{"total": 1}]
        return [dict(FILE_DOC)]

    def distinct(self, _field, _query=None):
        return ["python"]


class _Users:
    """אוסף המשתמשים, עם רישום של מה שנכתב אליו."""

    def __init__(self, prefs: Optional[Dict[str, Any]] = None):
        self.doc: Dict[str, Any] = {"user_id": 123, "ui_prefs": dict(prefs or {})}
        self.writes: List[Dict[str, Any]] = []

    def find_one(self, _query, _projection=None):
        return dict(self.doc)

    def update_one(self, _query, update, **_kwargs):
        self.writes.append(update)
        return type("Result", (), {"matched_count": 1, "modified_count": 1})()


class _DB:
    def __init__(self, users: _Users):
        self.code_snippets = _Snippets()
        self.users = users


class _CacheDisabled:
    is_enabled = False


class _CacheSpy:
    """קאש שמדווח באילו מפתחות נגעו — ומגיש באמת מה שנשמר.

    הגשה אמיתית ולא רק רישום: בדיקה שרק סופרת מפתחות הייתה עוברת גם על קאש
    שמגיש את ה-HTML הלא נכון, וזה בדיוק הכשל שהיא באה לתפוס.
    """

    is_enabled = True

    def __init__(self):
        self.store: Dict[str, str] = {}
        self.keys_read: List[str] = []
        self.keys_written: List[str] = []

    def get(self, key):
        self.keys_read.append(key)
        return self.store.get(key)

    def set(self, key, value, _ttl=None):
        self.keys_written.append(key)
        self.store[key] = value
        return True


def _login(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 123
        sess["user_data"] = {"id": 123, "first_name": "Test"}


def _render_files(monkeypatch, *, compact: bool, cache=None) -> str:
    users = _Users({"files_compact_view": compact})
    monkeypatch.setattr(webapp_app, "get_db", lambda: _DB(users), raising=True)
    monkeypatch.setattr(webapp_app, "cache", cache or _CacheDisabled(), raising=True)
    with webapp_app.app.test_client() as client:
        _login(client)
        response = client.get("/files")
        assert response.status_code == 200
        return response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 1. הכרעת ההעדפה — פונקציה טהורה, בלי מסד ובלי בקשה
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "stored, expected",
    [
        (True, True),
        (False, False),
        # ``"false"`` הוא המקרה שבגללו הבדיקה היא ``is True`` ולא ``bool()``:
        # ``bool("false")`` הוא ``True``, כלומר מסמך שנערך ביד היה מדליק את
        # המצב דווקא כשהערך אומר את ההפך.
        ("false", False),
        ("true", False),
        # ``1 is True`` הוא ``False`` בפייתון, וזה מכוון: הוולידציה
        # ב-``/api/ui_prefs`` דוחה מספרים, וכאן מגן על מה שכבר במסד.
        (1, False),
        (0, False),
        (None, False),
    ],
)
def test_only_a_real_boolean_true_turns_the_mode_on(stored, expected):
    doc = {"ui_prefs": {"files_compact_view": stored}}
    assert webapp_app._resolve_files_compact_view(123, doc) is expected


def test_a_missing_preference_means_the_full_view():
    assert webapp_app._resolve_files_compact_view(123, {"ui_prefs": {}}) is False
    assert webapp_app._resolve_files_compact_view(123, {}) is False


def test_no_user_means_the_full_view():
    """ללא משתמש אין העדפה, ואין גם קריאה למסד."""
    assert webapp_app._resolve_files_compact_view(None, None) is False


# ---------------------------------------------------------------------------
# 2. הרינדור — דרך הראוט האמיתי, על ה-HTML שהדפדפן מקבל
# ---------------------------------------------------------------------------

def test_the_full_view_shows_everything(monkeypatch):
    """ריצת הבקרה: בלי זה הבדיקה שלמטה עוברת גם על תבנית שלא מרנדרת כלום."""
    html = _render_files(monkeypatch, compact=False)

    assert CARD_LANG_ICON in html, "אייקון השפה חסר כבר בתצוגה המלאה"
    for anchor in HIDDEN_IN_COMPACT:
        assert anchor in html, f"{anchor} חסר כבר בתצוגה המלאה"


@pytest.mark.parametrize("anchor", HIDDEN_IN_COMPACT)
def test_the_compact_view_hides_the_secondary_details(monkeypatch, anchor):
    html = _render_files(monkeypatch, compact=True)
    assert anchor not in html


def test_the_compact_view_hides_the_language_icon(monkeypatch):
    assert CARD_LANG_ICON not in _render_files(monkeypatch, compact=True)


def test_the_compact_view_keeps_what_the_page_is_for(monkeypatch):
    """שם, באדג' שפה, תגיות — ומעל הכל הצ'קבוקס.

    ``data-file-id`` ו-``file-checkbox`` הם חוזה עם ``multi-select.js``
    ו-``bulk-actions.js``. הסתרתם הייתה שוברת בחירה מרובה ופעולות קבוצתיות
    בלי שום שגיאה, ולכן הם נבדקים במפורש ולא נשענים על "לא נגעתי בהם".
    """
    html = _render_files(monkeypatch, compact=True)

    assert "demo.py" in html, "שם הקובץ נעלם"
    assert 'class="lang-badge"' in html, "באדג' השפה נעלם"
    assert "#alpha" in html, "התגיות נעלמו"
    assert 'class="file-checkbox"' in html, "צ'קבוקס הבחירה המרובה נעלם"
    assert 'data-file-id="0123456789abcdef01234567"' in html, "מזהה הקובץ נעלם"
    assert "/file/0123456789abcdef01234567" in html, "כפתור הצפייה נעלם"


# ---------------------------------------------------------------------------
# 3. מפתח הקאש — המלכודת המרכזית
# ---------------------------------------------------------------------------

def test_the_two_views_do_not_share_a_cache_entry(monkeypatch):
    """אותו משתמש, אותם פרמטרים, העדפה שונה ← מפתח שונה.

    בלי זה: המשתמש מדליק את המתג, נכנס ל-``/files``, ומקבל את ה-HTML של
    המצב הקודם עד שה-TTL פוקע (ברירת מחדל 90 שניות). אין בקוד שום מקום
    שמבטל את הקאש הזה, ולכן ההפרדה חייבת לחיות במפתח.
    """
    cache = _CacheSpy()

    full = _render_files(monkeypatch, compact=False, cache=cache)
    compact = _render_files(monkeypatch, compact=True, cache=cache)

    assert len(set(cache.keys_written)) == 2, (
        f"שתי התצוגות נכתבו לאותו מפתח: {cache.keys_written}"
    )
    assert CARD_LANG_ICON in full
    assert CARD_LANG_ICON not in compact, (
        "התצוגה המצומצמת קיבלה את ה-HTML של התצוגה המלאה מהקאש"
    )


class _FlippingUsers(_Users):
    """מחזיר ערך שונה בכל קריאה — מדמה שינוי העדפה באמצע הבקשה.

    זה החלון האמיתי: הראוט בונה את מפתח הקאש לפני הרינדור, וה-context
    processor מזין את התבנית. שתי קריאות נפרדות למסד באותה בקשה.
    """

    def __init__(self):
        super().__init__({})
        self.reads = 0

    def find_one(self, _query, _projection=None):
        self.reads += 1
        return {"user_id": 123, "ui_prefs": {"files_compact_view": self.reads > 1}}


def test_the_key_and_the_rendered_html_cannot_disagree(monkeypatch):
    """הכרעה אחת לכל בקשה, גם כשההעדפה משתנה באמצעה.

    בלי זיכרון פר-בקשה: המפתח נבנה מהקריאה הראשונה (מלאה) והתבנית מהשנייה
    (מצומצמת), וה-HTML המצומצם נשמר תחת התגית של המלאה. מאותו רגע כל מי
    שמבקש את התצוגה המלאה מקבל את המצומצמת, עד שה-TTL פוקע.

    הבדיקה נופלת בדיוק על זה: היא משווה את מה שנשמר לתגית שתחתיה נשמר.
    """
    users = _FlippingUsers()
    cache = _CacheSpy()
    monkeypatch.setattr(webapp_app, "get_db", lambda: _DB(users), raising=True)
    monkeypatch.setattr(webapp_app, "cache", cache, raising=True)

    with webapp_app.app.test_client() as client:
        _login(client)
        html = client.get("/files").get_data(as_text=True)

    assert users.reads >= 2, "התרחיש לא נבדק — המסד נקרא פעם אחת בלבד"

    key = cache.keys_written[-1]
    # התגית במפתח היא ``c`` למצומצם ו-``f`` למלא. מה שנשמר חייב להתאים לה.
    tag = key.split(":")[4]
    is_compact_html = CARD_LANG_ICON not in html
    assert (tag == "c") is is_compact_html, (
        f"נשמר HTML של תצוגה {'מצומצמת' if is_compact_html else 'מלאה'} "
        f"תחת התגית {tag!r}"
    )
    assert html == cache.store[key], "מה שנשמר אינו מה שהוגש"


def test_the_cached_entry_is_actually_reused(monkeypatch):
    """ההפרדה לא הושגה בכך שהקאש הפסיק לעבוד.

    בלי הבדיקה הזו, מפתח שנבנה מערך אקראי בכל בקשה היה עובר את הבדיקה
    שמעליה — ומכבה את הקאש של אחד העמודים הכבדים באתר.
    """
    cache = _CacheSpy()

    first = _render_files(monkeypatch, compact=True, cache=cache)
    second = _render_files(monkeypatch, compact=True, cache=cache)

    assert len(set(cache.keys_written)) == 1, "אותה תצוגה נכתבה לשני מפתחות"
    assert first == second
    assert len(cache.keys_written) == 1, "הבקשה השנייה רונדרה מחדש במקום להיקרא מהקאש"


# ---------------------------------------------------------------------------
# 4. השמירה — קריאה של מה שנכתב, לא של מה שהתשובה אמרה
# ---------------------------------------------------------------------------

def _post_pref(monkeypatch, body: Dict[str, Any]):
    users = _Users()
    monkeypatch.setattr(webapp_app, "get_db", lambda: _DB(users), raising=True)
    with webapp_app.app.test_client() as client:
        _login(client)
        response = client.post(
            "/api/ui_prefs",
            data=json.dumps(body),
            content_type="application/json",
        )
    return response, users


@pytest.mark.parametrize("value", [True, False])
def test_the_preference_reaches_the_database(monkeypatch, value):
    """מה שנבדק הוא הכתיבה עצמה, ולא ``ok: true`` בתשובה.

    מפתח שאינו מטופל ב-``/api/ui_prefs`` מחזיר 200 ואינו נשמר — כך קרה
    ל-``smooth_scroll``, שנשלח מהלקוח עד היום ומעולם לא הגיע למסד.
    """
    response, users = _post_pref(monkeypatch, {"files_compact_view": value})

    assert response.status_code == 200
    assert response.get_json().get("files_compact_view") is value

    written = [w for w in users.writes if "$set" in w]
    assert written, "לא בוצעה שום כתיבה למסד"
    assert written[-1]["$set"].get("ui_prefs.files_compact_view") is value


def test_the_write_uses_a_dotted_path_and_not_the_whole_subdocument(monkeypatch):
    """‏``$set`` על ``ui_prefs`` כולו היה מוחק העדפות שכנות.

    לפי תיעוד MongoDB ``$set`` על מסמך מקונן **מחליף** אותו, ולכן שמירת
    התצוגה הייתה מוחקת את ערכת הנושא וגודל הגופן של אותו משתמש.
    """
    _response, users = _post_pref(monkeypatch, {"files_compact_view": True})

    fields = users.writes[-1]["$set"]
    assert "ui_prefs.files_compact_view" in fields
    assert "ui_prefs" not in fields


@pytest.mark.parametrize("value", ["false", "true", 1, 0, "", None, [], {"a": 1}])
def test_a_value_that_is_not_a_boolean_is_rejected_and_nothing_is_written(
    monkeypatch, value
):
    """דחייה ולא המרה. ``bool("false")`` הוא ``True``."""
    response, users = _post_pref(monkeypatch, {"files_compact_view": value})

    assert response.status_code == 400, f"{value!r} התקבל במקום להידחות"
    assert response.get_json().get("ok") is False
    assert not users.writes, f"נכתב למסד למרות ה-400: {users.writes}"


# ---------------------------------------------------------------------------
# 5. המתג בעמוד ההגדרות
# ---------------------------------------------------------------------------

class _Cursor(list):
    """מה ש-``find`` מחזיר. עמוד ההגדרות משרשר ``sort``/``limit``."""

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def skip(self, *_args, **_kwargs):
        return self


class _AnyCollection:
    def find_one(self, *_args, **_kwargs):
        return None

    def find(self, *_args, **_kwargs):
        return _Cursor()

    def count_documents(self, *_args, **_kwargs):
        return 0

    def distinct(self, *_args, **_kwargs):
        return []

    def aggregate(self, *_args, **_kwargs):
        return _Cursor()

    def update_one(self, *_args, **_kwargs):
        return type("Result", (), {"matched_count": 0, "modified_count": 0})()


class _PermissiveDB:
    """עמוד ההגדרות נוגע באוספים רבים; רק ``users`` מעניין כאן."""

    def __init__(self, users: _Users):
        self.users = users

    def __getattr__(self, _name):
        return _AnyCollection()


def _render_settings(monkeypatch, *, compact: bool) -> str:
    users = _Users({"files_compact_view": compact})
    monkeypatch.setattr(webapp_app, "get_db", lambda: _PermissiveDB(users), raising=True)
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)
    with webapp_app.app.test_client() as client:
        _login(client)
        response = client.get("/settings")
        assert response.status_code == 200
        return response.get_data(as_text=True)


@pytest.mark.parametrize("compact", [True, False])
def test_the_settings_toggle_reflects_the_saved_value(monkeypatch, compact):
    html = _render_settings(monkeypatch, compact=compact)

    assert 'id="filesCompactToggle"' in html, "המתג אינו מגיע לעמוד ההגדרות"
    # ``checked`` מרונדר בשרת, ולכן העמוד נטען כשהמתג כבר במצב הנכון
    # ואינו "קופץ" אחרי טעינת JS.
    marker = html.split('id="filesCompactToggle"', 1)[1].split(">", 1)[0]
    assert ("checked" in marker) is compact


def test_the_toggle_is_wired_exactly_once(monkeypatch):
    """הבלוק ``extra_js`` של עמוד ההגדרות מרונדר **פעמיים**.

    ``settings.html`` מצהיר ``{% block extra_js %}`` בתוך ``{% block content %}``,
    ולכן Jinja מרנדר אותו גם במקומו בתוך התוכן וגם שוב ב-``base.html``. נמדד
    בדפדפן: לחיצה אחת על המתג ייצרה אירוע ``change`` אחד ו**שתי** בקשות
    ל-``/api/ui_prefs``, משתי שורות שונות באותו עמוד.

    זו התנהגות קיימת שנוגעת בכל המתגים בעמוד — ``persistentToggle``,
    ``fontMinus`` ו-``themeSelect`` מופיעים שם באותה כפילות בדיוק — ואינה
    מתוקנת כאן. מה שכן: המאזין של המתג הזה מסומן על האלמנט, ולכן העותק
    השני אינו מוסיף מאזין נוסף.

    **הבדיקה אינה מקבעת את מספר העותקים.** אילו הייתה דורשת "בדיוק שניים",
    היא הייתה נכשלת ביום שבו מישהו יתקן את כפילות הרינדור — כלומר חוסמת
    את התיקון הנכון. מה שנדרש כאן הוא רק שהחיווט מוגן, ושהוא נשאר נכון
    בשני המצבים. **ההוכחה ההתנהגותית** — שהרצה כפולה של הסקריפט אכן רושמת
    מאזין אחד — יושבת ב-``tests/files-compact-toggle.test.js``, שמריץ את
    הבלוק פעמיים ב-``vm`` וסופר מאזינים.
    """
    html = _render_settings(monkeypatch, compact=False)

    # אלמנט אחד בדף — זה מה שחייב להישאר נכון בכל מצב.
    assert html.count('id="filesCompactToggle"') == 1
    # והחיווט מוגן, בין אם הסקריפט מרונדר פעם אחת ובין אם פעמיים.
    assert "compactToggle.dataset.wired" in html, (
        "הסימון שמונע חיווט כפול הוסר — כל עוד הבלוק מרונדר פעמיים, "
        "לחיצה אחת תשלח שתי בקשות"
    )

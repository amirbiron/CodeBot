"""הצ'קליסט "צעדים ראשונים" בדשבורד: צעדים שמסתמנים לבד, לפי מה שהמשתמש עשה בפועל.

**אין כאן דגל לכל צעד, ואין סימון ידני.** כל צעד נגזר מהנתונים עצמם: יש ערכת נושא שמורה,
יש אוסף, יש פתק על לוח, יש חיבור סוכן פעיל. ככה הסימון לא יכול לשקר, ואין מה לסנכרן בין
מכשירים. החריג היחיד הוא ערכה שנבחרה "רק במכשיר הזה": היא נשמרת רק ב-cookie של אותו מכשיר,
ולכן ברגע הבחירה נרשם במסמך המשתמש **שנבחרה** ערכה (:func:`record_device_theme_choice`),
כדי שהצעד ייחשב בכל המכשירים. את הערכה עצמה זה לא רושם.

שני דגלים ב-``ui_prefs`` עוצרים את הבדיקות, והם נקראים מתוך מסמך המשתמש שכבר נטען בבקשה:

- :data:`DONE_PREF` — **נעילה.** נכתב כשכל הצעדים מסומנים, והוא סופי: מחיקה של כל האוספים אחר
  כך לא מחזירה את הכרטיס.
- :data:`HIDDEN_PREF` — **הסתרה ידנית** ("הבנתי, להסתיר"). נכתב דרך ``/api/ui_prefs``.

כשאחד מהם קיים, אף שאילתה של הצ'קליסט לא רצה. "הצג שוב" בהגדרות מוחק את שניהם.

**צעד שהבדיקה שלו נכשלה במסד אינו "לא בוצע".** הוא "לא ידוע כרגע" (``None``), כמו
``pending_count`` ש-``_build_push_card`` מחזיר ``None`` כשהספירה נכשלה. הוא לא נספר, והנעילה
לא נכתבת, כי נעילה על סמך בדיקה שלא רצה הייתה רושמת מצב שאיש לא ראה. בבדיקות רק
:data:`DB_UNAVAILABLE_ERRORS` נתפס; כל שגיאה אחרת עולה הלאה.

**הכתיבות כאן הן עזר** — :func:`_write_lock` ו-:func:`record_device_theme_choice`. הנעילה היא
קיצור דרך לטעינות הבאות, והרישום של ערכה במכשיר משרת רק את הצ'קליסט; אף אחת מהן אינה מה
שהמשתמש ביקש. לכן כל כשל של המסד בהן (``PyMongoError``) נרשם כ-WARNING והבקשה ממשיכה; באג,
כלומר חריגה שאינה של המסד, עולה.

התיעוד: ``docs/webapp/user-interfaces.rst``, סעיף ``webapp-first-steps``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from pymongo.errors import ConnectionFailure, ExecutionTimeout, PyMongoError

# אין כאן ייבוא מחבילת ``database`` ברמת המודול, בכוונה: ``webapp/app.py`` מייבא את המודול
# הזה ברמת המודול, ו-``database`` בונה ``DatabaseManager`` בזמן ייבוא, כך שייבוא ממנה כאן היה
# מפיל את ``import webapp.app`` בסביבה בלי ``MONGODB_URL`` (ראו
# ``test_the_shared_write_path_import_stays_inside_the_route``). לכן הוא בתוך הפונקציות.
from mcp_server.oauth_store import subject_has_live_token
from mcp_server.token_store import user_has_live_token
from sticky_notes_target import any_board_note_filter

logger = logging.getLogger(__name__)

#: "המסד לא ענה עכשיו" — אחרי החריגות האלה צעד מוצג "לא ידוע כרגע", ושום דבר לא ננעל. תת-העץ של
#: ``ConnectionFailure`` (חיבור שנפל, אין שרת זמין, החלפת primary) ו-``ExecutionTimeout`` (מגבלת
#: הזמן של השרת), כפי שנבדק ב-``__mro__`` של pymongo 4.15.3 — אותו זוג כמו
#: ``_OUTCOME_UNKNOWN_ERRORS`` ב-``monitoring/metrics_storage.py``. שאר ``PyMongoError`` — הרשאה
#: שגויה, שאילתה פגומה — הם תצורה או באג, ולכן הם עולים ולא מתויגים "לא ידוע" (R10 ב-
#: amir-bug-patterns). ``tests/test_first_steps.py`` מקבע את החלוקה. את הטיפוס הזה תופסים רק מי
#: שהמצב שלהם הוצהר לתקלה חולפת: הבדיקות כאן, ו-``default_board_page`` ב-``webapp/boards_ui.py``,
#: שמפנה ל-``/boards`` כדי שהעמוד ינסה שוב. בכתיבות העזר (:func:`_write_lock`,
#: :func:`record_device_theme_choice`) המצב הוצהר לכל כשל של המסד, ולכן שם נתפס ``PyMongoError``.
DB_UNAVAILABLE_ERRORS = (ConnectionFailure, ExecutionTimeout)

#: נעילה: כל הצעדים הושלמו, והכרטיס לא חוזר. נכתב ב-:func:`_write_lock`.
DONE_PREF = "first_steps_done"
#: הסתרה ידנית של הכרטיס. נכתב ונמחק ב-``api_ui_prefs`` (``webapp/app.py``).
HIDDEN_PREF = "first_steps_hidden"
#: נבחרה ערכה "רק במכשיר הזה" (באחד המכשירים). נכתב ב-:func:`record_device_theme_choice`.
DEVICE_THEME_CHOSEN_PREF = "device_theme_chosen"

STEP_THEME = "theme"
STEP_COLLECTION = "collection"
STEP_NOTE = "note"
STEP_AI = "ai"


def _workspace_tip() -> str:
    """הטיפ של צעד האוספים, עם השם של שולחן העבודה מהקבוע שלו."""
    from database.collections_manager import WORKSPACE_COLLECTION_NAME

    return f"לקבצים שדרושים טיפול בזמן הקרוב השתמש בלוח {WORKSPACE_COLLECTION_NAME} המובנה"


#: הצעדים לפי סדר התצוגה, עם הטקסט שלהם. הסדר, המונה ("X מתוך N") והצעד שמסומן בפס נגזרים מכאן.
#: ``lines`` הן שורות ההסבר; ``how`` עם ``how_label`` היא "איך מגיעים"; ``tip`` אופציונלי — מחרוזת,
#: או פונקציה שמחזירה אותה (:func:`build_card` קורא לה).
STEPS: Tuple[Dict[str, Any], ...] = (
    {
        "key": STEP_THEME,
        "icon": "🎨",
        "title": "התאם את סביבת העבודה שלך",
        "lines": ("בחר ערכת נושא לממשק ולהדגשת תחביר.",),
        "how_label": "איך מגיעים:",
        "how": "לחץ על כפתור ההגדרות ⚙️ בסרגל העליון וגלול למטה עד להגדרת ערכות נושא.",
        "action_label": "לבחירת ערכה",
        # ``id="appearance"`` על כרטיס "ערכת נושא" ב-``settings.html``.
        "action_href": "/settings#appearance",
        "tip": "",
    },
    {
        "key": STEP_COLLECTION,
        "icon": "🗂️",
        "title": "ארגן את הידע שלך",
        "lines": (
            'לשמירת קבצים עם הקשר ביניהם, כנס ל-"האוספים שלי" בסרגל העליון, '
            "שם תוכל ליצור אוספים אישיים לקבצים השמורים שלך.",
            "צור את האוסף הראשון שלך.",
        ),
        "how_label": "",
        "how": "",
        "action_label": "לעמוד האוספים",
        "action_href": "/collections",
        # פונקציה ולא מחרוזת: שם שולחן העבודה הוא ``WORKSPACE_COLLECTION_NAME``, מחבילת
        # ``database``, שאינה מיובאת ברמת המודול (ההסבר ליד הייבואים).
        "tip": _workspace_tip,
    },
    {
        "key": STEP_NOTE,
        "icon": "📝",
        "title": "הכר את לוחות הפתקים",
        "lines": ("נהל משימות ורעיונות על פתקים דביקים",),
        "how_label": "איך מגיעים לפתקים:",
        "how": 'כפתור "סטיקי נוטס" נמצא בעמוד הקבצים הראשי, ממוקם מתחת לשורת החיפוש.',
        "action_label": "לוח העבודה",
        # הפניה ללוח ברירת המחדל, שנוצר אם עוד אין (``webapp/boards_ui.py``).
        "action_href": "/boards/default",
        "tip": "כדאי להציץ בהגדרות ⚙️ בעמוד הלוח",
    },
    {
        "key": STEP_AI,
        "icon": "🤖",
        "title": "חבר את סוכני ה-AI שלך (MCP)",
        "lines": ("תן ל-Claude או ל-Gemini לקרוא ולכתוב ישירות לקבצים ולפתקים שלך.",),
        "how_label": "",
        "how": "",
        "action_label": "אני רוצה להתחבר",
        "action_href": "/settings#ai-connect",
        "tip": (
            "לתיחזוק ואיסוף ידע חשוב שמתחדש בקביעות, כמו החלטות מערכת, או איפיון פיצ'ר מסוים "
            "צור מסמך ייחודי, ותן הוראות קבועות לסוכן שלך לעדכן את המסמך כל פעם שמתעדכן ידע "
            "רלוונטי בנושא."
        ),
    },
)

STEP_KEYS: Tuple[str, ...] = tuple(step["key"] for step in STEPS)


def _ui_prefs(user_doc: Any) -> Mapping[str, Any]:
    """``ui_prefs`` של המסמך, או מילון ריק כשאין או כשהשדה אינו מילון."""
    if not isinstance(user_doc, Mapping):
        return {}
    prefs = user_doc.get("ui_prefs")
    return prefs if isinstance(prefs, Mapping) else {}


def is_dismissed(user_doc: Any) -> bool:
    """האם הכרטיס ננעל או הוסתר — ואז אין לו מה להציג, ואין מה לבדוק.

    ``is True`` ולא אמת כלשהי: הכותבים כותבים רק ``True``, וערך אחר שהגיע למסמך
    (מחרוזת ``"false"``, למשל) לא יסתיר את הכרטיס בשקט.
    """
    prefs = _ui_prefs(user_doc)
    return prefs.get(DONE_PREF) is True or prefs.get(HIDDEN_PREF) is True


def theme_step_done(user_doc: Any, *, stored_theme: str, device_theme: str) -> bool:
    """צעד הערכה: יש בחירת ערכה שמורה. בלי שאילתה — הכל כבר בבקשה.

    כל אחד מהמקורות האלה מספיק:

    - ``stored_theme`` — הערכה שבמסמך המשתמש (``_stored_theme_pref`` ב-``webapp/app.py``),
      כלומר בחירה "לכל המכשירים";
    - ``device_theme`` — הערכה שנבחרה "רק במכשיר הזה" במכשיר של הבקשה
      (``_device_scoped_theme_cookie`` שם). זה גם מה שמכסה בחירה שנעשתה לפני
      :data:`DEVICE_THEME_CHOSEN_PREF`;
    - :data:`DEVICE_THEME_CHOSEN_PREF` — בחירה "רק במכשיר הזה" באחד המכשירים.
    """
    if stored_theme or device_theme:
        return True
    return _ui_prefs(user_doc).get(DEVICE_THEME_CHOSEN_PREF) is True


def _checked(step_key: str, check: Callable[[], bool]) -> Optional[bool]:
    """תוצאת בדיקה אחת, או ``None`` כשהמסד נכשל באמצעה (נרשם כ-WARNING)."""
    try:
        return bool(check())
    except DB_UNAVAILABLE_ERRORS:
        logger.warning("first steps: the %s check failed; showing it as unknown", step_key, exc_info=True)
        return None


def _ai_state(db: Any, user_id: int) -> Optional[bool]:
    """צעד החיבור: טוקן אישי חי **או** חיבור OAuth חי.

    שתי הבדיקות בתורן, והראשונה שמוצאת חיבור עוצרת. ``None`` רק כשאף אחת לא מצאה,
    ולפחות אחת נכשלה במסד — חיבור שנמצא הוא תשובה גם אם השנייה לא רצה.
    """
    unknown = False
    checks = (
        lambda: user_has_live_token(db, user_id),
        # ``subject`` הוא ה-``user_id`` כמחרוזת, כפי ש-``mcp_server/oauth_routes.py`` כותב אותו.
        lambda: subject_has_live_token(db, str(int(user_id))),
    )
    for check in checks:
        state = _checked(STEP_AI, check)
        if state is True:
            return True
        if state is None:
            unknown = True
    return None if unknown else False


def _step_states(db: Any, user_id: int, user_doc: Any, *, stored_theme: str, device_theme: str) -> Dict[str, Optional[bool]]:
    """המצב של כל צעד: ``True`` בוצע, ``False`` לא בוצע, ``None`` לא ידוע כרגע."""
    from database.collections_manager import user_has_own_collection

    uid = int(user_id)
    return {
        STEP_THEME: theme_step_done(user_doc, stored_theme=stored_theme, device_theme=device_theme),
        STEP_COLLECTION: _checked(STEP_COLLECTION, lambda: user_has_own_collection(db, uid)),
        STEP_NOTE: _checked(
            STEP_NOTE,
            lambda: db.sticky_notes.find_one(any_board_note_filter(uid), {"_id": 1}) is not None,
        ),
        STEP_AI: _ai_state(db, uid),
    }


def _write_lock(db: Any, user_id: Any) -> None:
    """שומר את :data:`DONE_PREF`. כשל של המסד נרשם ולא עוצר את הדף: הכרטיס כבר לא מוצג, כי כל
    הצעדים באמת בוצעו, ובטעינה הבאה הבדיקות ירוצו שוב וינסו לנעול שוב."""
    now = datetime.now(timezone.utc)
    try:
        db.users.update_one(
            {"user_id": user_id},
            {"$set": {f"ui_prefs.{DONE_PREF}": True, "updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
    # כל כשל של המסד ולא רק ניתוק: הנעילה היא עזר, והמצב "לא נשמר, ינסו שוב" נכון לכל כשל
    # בכתיבה — גם להרשאה. בלי זה, כתיבת עזר שנכשלה הייתה מעבירה את כל הדשבורד לדף השגיאה שלו.
    except PyMongoError:
        logger.warning("first steps: the lock was not saved; the checks will run again next time", exc_info=True)


def build_card(
    db: Any,
    user_id: Any,
    user_doc: Optional[Mapping[str, Any]],
    *,
    stored_theme: str,
    device_theme: str,
) -> Optional[Dict[str, Any]]:
    """הנתונים של הכרטיס לתבנית, או ``None`` כשאין כרטיס להציג.

    הסדר הוא החוזה: **קודם הדגלים, ורק אחריהם השאילתות.**

    1. ``user_doc`` הוא ``None`` — מסמך המשתמש לא נטען (המסד נכשל), ולכן אי אפשר לדעת אם
       הכרטיס הוסתר. אין כרטיס, ואין שאילתות: משתמש שהסתיר לא יראה אותו חוזר בגלל תקלה.
    2. הכרטיס ננעל או הוסתר (:func:`is_dismissed`) — אין כרטיס, ואין שאילתות.
    3. אחרת רצות הבדיקות. כשכל הצעדים בוצעו נכתבת הנעילה, והכרטיס לא מוצג.

    ``user_id`` הוא הערך מה-session, כמו שהוא — באותה צורה שבה ``inject_globals`` ו-
    ``/api/ui_prefs`` שולפים וכותבים את מסמך המשתמש.
    """
    if user_doc is None or is_dismissed(user_doc):
        return None

    states = _step_states(db, user_id, user_doc, stored_theme=stored_theme, device_theme=device_theme)
    if all(state is True for state in states.values()):
        _write_lock(db, user_id)
        return None

    steps: List[Dict[str, Any]] = []
    next_marked = False
    for step in STEPS:
        state = states[step["key"]]
        # הפס הצבעוני מסמן את הצעד הבא שעוד לא בוצע. צעד "לא ידוע" אינו "הבא": אולי בוצע.
        is_next = state is False and not next_marked
        next_marked = next_marked or is_next
        tip = step["tip"]() if callable(step["tip"]) else step["tip"]
        steps.append({**step, "tip": tip, "state": state, "is_next": is_next})

    done_count = sum(1 for step in steps if step["state"] is True)
    return {"steps": steps, "done_count": done_count, "total": len(steps)}


def record_device_theme_choice(db: Any, user_id: Any) -> None:
    """רושם במסמך המשתמש שנבחרה ערכה "רק במכשיר הזה" — את הבחירה, ולא את הערכה.

    נקרא מכל מסלול שמחיל ערכה במצב ``device``, אחרי שההחלה הצליחה, כדי שצעד הערכה ייחשב בכל
    המכשירים. **כשל של המסד כאן לא מכשיל את ההחלה** — כל ``PyMongoError``, ולא רק ניתוק: הערכה
    כבר הוחלה במכשיר (ה-cookie), והרישום משרת רק את הצ'קליסט. לכן הכשל נרשם כ-WARNING והבקשה
    ממשיכה — במכשיר הזה הצעד עדיין מסומן לפי ה-cookie, ובמכשיר אחר הוא יסומן בבחירה הבאה. הכותבים
    (``api_ui_prefs``, ``apply_shared_theme``, ``activate_theme_endpoint``) קוראים לה בתוך ה-``try``
    של הראוט, שמחזיר 500 על כל חריגה, ולכן חריגה שעולה מכאן זורקת את התשובה עם ה-cookie. באג,
    כלומר חריגה שאינה של המסד, עולה בכל זאת.
    """
    if db is None:
        logger.warning("first steps: device theme choice not recorded; no database connection")
        return
    now = datetime.now(timezone.utc)
    try:
        db.users.update_one(
            {"user_id": user_id},
            {
                "$set": {f"ui_prefs.{DEVICE_THEME_CHOSEN_PREF}": True, "updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    except PyMongoError:
        logger.warning("first steps: device theme choice not recorded", exc_info=True)

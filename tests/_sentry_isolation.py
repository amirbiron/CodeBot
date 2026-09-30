"""בידוד Sentry בין בדיקות: אף בדיקה לא משאירה Sentry מוכן להידלק בבדיקות שאחריה.

**למה זה קיים.** ``sentry_sdk.init`` אמיתי בתוך תהליך הבדיקות אינו רק רעש.
מלבד האינטגרציות שביקשו ממנו, הוא מדליק גם את אלה ש-sentry-sdk מדליק לבד
כשהספרייה שלהן מותקנת (``auto_enabling_integrations``) — Starlette, pymongo,
redis, httpx, aiohttp, flask. הן עוטפות את הספריות האלה עד סוף התהליך, ופועלות
בכל פעם שיש לקוח חי. כך נשבר טסט הטפטוף של ``PUT /api/agent/upload`` בריצה
הסדרתית של ``deploy.yml``: עטיפת ה-route של Starlette קוראת את כל גוף הבקשה
לפני ה-route ובלי דדליין (``StarletteRequestExtractor.extract_request_info``,
נקרא ב-sentry-sdk 2.42.1), ובולעת את הביטול של הטסט בתוך
``capture_internal_exceptions``. לבדו הטסט עבר; הוא נפל רק אחרי שתי בדיקות
אחרות.

**ומה הדליק אותו.** שתי בדיקות, כל אחת תמימה לבדה: אחת השאירה ``SENTRY_DSN``
בסביבה, והשנייה טענה מחדש את ``main`` — ש-``main.py`` קורא ל-``init_sentry()``
ברמת המודול, ו-``init_sentry`` (``observability.py``) לוקח את הכתובת מהסביבה.
הקונפיג בבדיקות הוא ``tests/config.py``, ושם ``SENTRY_DSN`` ריק תמיד, כלומר
הסביבה היא הערוץ היחיד שדרכו מגיעה כתובת.

**מה המודול עושה:**

- בתחילת הריצה מסיר את ``SENTRY_DSN`` מהסביבה, כך שגם כתובת אמיתית מהמעטפת
  של מי שמריץ לא מגיעה לבדיקות.
- אחרי כל בדיקה, אחרי שכל הפיקסצ'רים שלה פורקו — כולל ``monkeypatch``, ולכן
  בדיקה שהשתמשה בו נכון אינה נתפסת — ``SENTRY_DSN`` שנשאר בסביבה או לקוח
  Sentry חי מוחזרים למצב נקי, והבדיקה **שהשאירה אותם** נכשלת בשמה.

**למה להכשיל ולא לנקות בשקט.** ניקוי שקט היה מסתיר את הבדיקה הדולפת, והכשל
הבא היה מופיע שוב אצל בדיקה אחרת, תמימה — בדיוק מה שקרה כאן.

נרשם מ-``tests/conftest.py`` ב-``pytest_configure``, ולכן פעיל בכל ריצה שאוספת
בדיקות מתוך ``tests/`` — כולל הריצה המלאה — ובריצה כזו הוא חל על כל בדיקה, גם
על אלה שמחוץ ל-``tests/``. ראו ``docs/testing.rst``.
"""

from __future__ import annotations

import os

import pytest

try:
    import sentry_sdk
except ImportError:  # בלי sentry-sdk מותקן אין לקוח שיכול להישאר דלוק; בדיקת הסביבה נשארת
    sentry_sdk = None

#: המשתנה ש-``init_sentry`` ב-``observability.py`` קורא ממנו את הכתובת.
DSN_ENV = "SENTRY_DSN"

#: קידומת לכל שורה שהמודול מוסיף לדיווח, כדי שיהיה ברור מאיפה היא באה.
REPORT_PREFIX = "[sentry-isolation]"


def pytest_configure(config: pytest.Config) -> None:
    os.environ.pop(DSN_ENV, None)


def shut_down_sentry() -> bool:
    """מכבה כל לקוח Sentry שרשום באחד משלושת ה-scopes, ומחזיר האם היה לקוח פעיל.

    זה הניקוי שבדיקה שחייבת לקוח אמיתי קוראת לו בסופה, וזה מה שהשומר עושה
    כשבדיקה לא ניקתה. כל מה שכאן נקרא בקוד של sentry-sdk 2.42.1:

    - **``close()`` לבדו אינו מספיק.** ``_Client.is_active`` מחזיר ``True`` תמיד
      (``sentry_sdk/client.py``), ולכן לקוח סגור שעדיין רשום ב-scope ממשיך להיחשב
      פעיל עבור ``get_client``. רק ``Scope.set_client(None)`` מכבה אותו — הוא שם
      במקומו ``NonRecordingClient``, שאינו פעיל (``sentry_sdk/scope.py``).
    - **כל שלושת ה-scopes, וכל לקוח שנמצא בהם.** ``Scope.get_client`` מחזיר רק את
      הלקוח הפעיל הראשון — ב-current, אחר כך ב-isolation ורק אז ב-global — ו-
      ``sentry_sdk.init`` שם לקוח ב-global בלבד. אבל קוד אחר יכול לשים לקוחות
      שונים ב-scopes שונים, וסגירה של "הלקוח" בלבד הייתה משאירה את האחרים פתוחים,
      עם החוטים שלהם. לכן הלקוחות נאספים מכל ה-scopes, כל אחד נסגר פעם אחת גם
      כשהוא רשום בכמה מהם, וכל ה-scopes מנותקים.
    - ``close(timeout=0)`` עוצר את החוטים של הלקוח בלי להמתין: ``flush`` עם אפס
      אינו ממתין, ו-``kill`` חוזר מיד (``sentry_sdk/transport.py``,
      ``sentry_sdk/worker.py``). מה שכבר עמד בתור לשליחה עשוי עדיין לצאת.
    """
    if sentry_sdk is None:
        return False
    scopes = (
        sentry_sdk.get_current_scope(),
        sentry_sdk.get_isolation_scope(),
        sentry_sdk.get_global_scope(),
    )
    live: list = []
    for scope in scopes:
        client = scope.client
        if client.is_active() and not any(client is seen for seen in live):
            live.append(client)
    if not live:
        return False
    for scope in scopes:
        scope.set_client(None)
    for client in live:
        client.close(timeout=0)
    return True


def restore_sentry_isolation() -> list[str]:
    """מחזיר את Sentry למצב כבוי, ומחזיר מה היה צריך לתקן — רשימה ריקה כשהכול היה תקין."""
    problems: list[str] = []
    if os.environ.pop(DSN_ENV, None) is not None:
        problems.append(
            f"{DSN_ENV} נשאר בסביבה. כותבים אותו ב-monkeypatch.setenv ולא ב-os.environ[...] = ..., "
            "ו-monkeypatch.delenv אחרי השמה ישירה אינו ניקוי: הוא זוכר את הערך שמצא ומחזיר אותו "
            "בסוף הבדיקה."
        )
    if shut_down_sentry():
        problems.append(
            "לקוח Sentry חי נשאר דלוק. בדיקה שבודקת את האתחול מחליפה את sentry_sdk או את "
            "sentry_sdk.init בדמה דרך monkeypatch, ובדיקה שחייבת לקוח אמיתי קוראת בסופה ל-"
            "_sentry_isolation.shut_down_sentry(), שמנתקת אותו מכל ה-scopes וסוגרת אותו. "
            "close() לבדו אינו מספיק: לקוח סגור שעדיין רשום ב-scope נחשב פעיל."
        )
    return problems


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None):
    # עוטף את ה-teardown המובנה, ולכן הבדיקה כאן רצה אחרי שהפיקסצ'רים של הבדיקה פורקו.
    try:
        result = yield
    except BaseException as exc:
        # ה-teardown של הבדיקה נכשל בעצמו, והשגיאה שלו היא שעולה. הבידוד משוחזר בכל זאת
        # כדי שהבדיקות הבאות לא ירשו אותו, ומה שנמצא מוצמד לשגיאה כהערה (PEP 678) —
        # pytest מציג אותה מתחת לשגיאה, גם תחת xdist.
        for problem in restore_sentry_isolation():
            exc.add_note(f"{REPORT_PREFIX} {problem}")
        raise
    problems = restore_sentry_isolation()
    if problems:
        pytest.fail(
            f"{REPORT_PREFIX} הבדיקה השאירה את Sentry מוכן להידלק בבדיקות שאחריה. המצב הוחזר לנקי:\n- "
            + "\n- ".join(problems)
            + "\nראו docs/testing.rst, הסעיף על Sentry בבדיקות.",
            pytrace=False,
        )
    return result

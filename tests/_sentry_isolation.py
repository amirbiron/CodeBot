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
  בדיקה שהשתמשה בו נכון אינה נתפסת — ``SENTRY_DSN`` שנשאר בסביבה, לקוח Sentry
  חי, או מודול מזויף של ``sentry_sdk`` שנשאר ב-``sys.modules`` מוחזרים למצב
  נקי, והבדיקה **שהשאירה אותם** נכשלת בשמה.

**ומודול מזויף.** קוד שמייבא את ``sentry_sdk`` בזמן הקריאה — ``_set_sentry_tag``
ב-``observability.py`` — מקבל את מה שיש ב-``sys.modules`` באותו רגע. בדיקה ששמה
שם מודול מזויף בלי להחזיר את האמיתי גרמה לכך שבכל הבדיקות שאחריה התגיות לא
הגיעו ל-scope האמיתי, בזמן שבדיקה שייבאה את ``sentry_sdk`` בזמן האיסוף קיבלה
אירועים אמיתיים — בלי תגיות. כך נפלו טסטים של ``tests/test_webserver_observability_scope.py``
בריצה הסדרתית של ``deploy.yml`` ב-28.11.2026, אחרי ``tests/test_observability_basic.py``.

**למה להכשיל ולא לנקות בשקט.** ניקוי שקט היה מסתיר את הבדיקה הדולפת, והכשל
הבא היה מופיע שוב אצל בדיקה אחרת, תמימה — בדיוק מה שקרה כאן.

נרשם מ-``tests/conftest.py`` ב-``pytest_configure``, ולכן פעיל בכל ריצה שאוספת
בדיקות מתוך ``tests/`` — כולל הריצה המלאה — ובריצה כזו הוא חל על כל בדיקה, גם
על אלה שמחוץ ל-``tests/``. ראו ``docs/testing.rst``.
"""

from __future__ import annotations

import os
import sys
from types import ModuleType

import pytest

try:
    import sentry_sdk
except ImportError:  # בלי sentry-sdk מותקן אין לקוח שיכול להישאר דלוק; בדיקת הסביבה נשארת
    sentry_sdk = None

#: המשתנה ש-``init_sentry`` ב-``observability.py`` קורא ממנו את הכתובת.
DSN_ENV = "SENTRY_DSN"

#: קידומת לכל שורה שהמודול מוסיף לדיווח, כדי שיהיה ברור מאיפה היא באה.
REPORT_PREFIX = "[sentry-isolation]"


#: המודולים האמיתיים של sentry-sdk שנטענו עד תחילת הריצה, לפי שם (``pytest_configure``). בדיקה שהחליפה אחד מהם
#: ב-``sys.modules`` ולא החזירה אותו נתפסת מול הרשימה הזו.
_REAL_SENTRY_MODULES: dict[str, ModuleType] = {}


def _is_sentry_module_name(name: str) -> bool:
    return name == "sentry_sdk" or name.startswith("sentry_sdk.")


def pytest_configure(config: pytest.Config) -> None:
    os.environ.pop(DSN_ENV, None)
    _REAL_SENTRY_MODULES.update({name: mod for name, mod in sys.modules.items() if _is_sentry_module_name(name)})


def _comes_from_the_installed_sentry_sdk(module: object) -> bool:
    """האם המודול נטען מהחבילה המותקנת. מודול מזויף (``types.ModuleType``) אין לו ``__spec__``.

    התיקיות של החבילה נלקחות מ-``sentry_sdk.__path__`` ולא מה-``origin`` של ``__init__.py``, ש-``None`` בחבילה בלי
    ``__init__.py``. מודול בלי ``origin`` נחשב לא-מהחבילה: ב-sentry-sdk 2.42.1 לכל תיקייה יש ``__init__.py``, ולכן לכל
    תת-מודול אמיתי יש ``origin``.
    """
    if sentry_sdk is None:
        return False
    origin = getattr(getattr(module, "__spec__", None), "origin", None)
    if not origin:
        return False
    origin = os.path.abspath(origin)
    return any(origin.startswith(os.path.abspath(path) + os.sep) for path in sentry_sdk.__path__)


def _undo_replacement(name: str, found: object, real: ModuleType | None) -> None:
    """מחזיר את ``real`` ל-``sys.modules`` במקום ``found`` (או מוציא את השם כש-``real`` הוא ``None``).

    גם המאפיין על המודול ההורה מתוקן — אבל רק כשהוא מצביע על ``found``. ``import x.y`` ו-``importlib.import_module``
    קוראים מ-``sys.modules``, ו-``x.y`` קורא מהמאפיין, ובדיקה שהחליפה את שניהם הייתה משאירה אחרי ניקוי של
    ``sys.modules`` בלבד שני מודולים שונים לאותו שם. ולמה רק כשהוא ``found``: לא כל מאפיין בשם של תת-מודול הוא
    התת-מודול.
    ב-sentry-sdk 2.42.1 ``sentry_sdk.monitor`` הוא הדקורטור מ-``sentry_sdk.crons``, ולא המודול ``sentry_sdk.monitor``.
    """
    if real is None:
        del sys.modules[name]
    else:
        sys.modules[name] = real
    parent_name, _, child = name.rpartition(".")
    parent = sys.modules.get(parent_name) if parent_name else None
    if parent is None or found is None or getattr(parent, child, None) is not found:
        return
    if real is None:
        delattr(parent, child)
    else:
        setattr(parent, child, real)


def restore_real_sentry_modules() -> list[str]:
    """מחזיר ל-``sys.modules`` את המודולים האמיתיים של sentry-sdk, ומחזיר את שמות אלה שהיו מוחלפים.

    שם שהיה ברשימה של תחילת הריצה ומוחזק עכשיו במודול אחר — חוזר למודול האמיתי. שם שלא היה ברשימה (תת-מודול
    שנטען מאוחר יותר) ואינו מהחבילה המותקנת — יוצא מ-``sys.modules``, והייבוא הבא טוען את האמיתי. בשני המקרים גם
    המאפיין על המודול ההורה מתוקן, כשהוא מצביע על המודול שהוחלף (``_undo_replacement``).
    """
    replaced: list[str] = []
    # ההורה לפני הילדים: כשגם ``sentry_sdk`` עצמו הוחלף, המאפיין של כל ילד נבדק על ההורה האמיתי.
    names = sorted(
        {name for name in sys.modules if _is_sentry_module_name(name)} | set(_REAL_SENTRY_MODULES),
        key=lambda name: (name.count("."), name),
    )
    for name in names:
        real = _REAL_SENTRY_MODULES.get(name)
        found = sys.modules.get(name)
        if real is not None:
            if found is not real:
                _undo_replacement(name, found, real)
                replaced.append(name)
        elif found is not None and not _comes_from_the_installed_sentry_sdk(found):
            _undo_replacement(name, found, None)
            replaced.append(name)
    return sorted(replaced)


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
    replaced = restore_real_sentry_modules()
    if replaced:
        problems.append(
            f"מודול של sentry_sdk הוחלף ב-sys.modules ולא הוחזר ({', '.join(replaced)}). מחליפים אותו ב-"
            "monkeypatch.setitem(sys.modules, ...), שמחזיר את האמיתי בסוף הבדיקה. השמה ישירה נשארת לכל שאר "
            "הריצה, וכל קוד שמייבא את sentry_sdk בזמן הקריאה מקבל אחריה את המזויף."
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

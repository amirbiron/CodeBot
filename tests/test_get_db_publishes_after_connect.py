"""``get_db`` מפרסם את הגלובלים רק כשהחיבור מוכן — ולעולם לא ``None``.

**למה הקובץ הזה קיים.** ``webapp.app.get_db`` מחזיק שני גלובלים, ``client``
ו-``db``, ומשתמש ב-``client`` כשומר של המסלול המהיר: ``if client is None``.
מי שרואה את השומר מאותחל מדלג על הנעילה ומחזיר את ``db`` כמו שהוא. הקוד
הישן הציב את השומר **לפני** הערך שהוא שומר עליו, ולכן החזיר ``None`` בשני
תרחישים — שניהם שוחזרו לפני שנכתב התיקון:

1. **מרוץ.** ``server_info()`` הוא סיבוב רשת שלם. קורא מקביל שנכנס באמצעו
   ראה ``client`` מוצב ואת ``db`` עדיין ``None``, וקיבל ``None``.
2. **הרעלה קבועה.** כשל ב-``server_info()`` השאיר את ``client`` מוצב על
   לקוח שבור. החריגה נזרקה הלאה, אבל כל קריאה עתידית כבר דילגה על האתחול
   והחזירה ``None`` — תקלת רשת חולפת אחת שיתקה את התהליך עד ריסטארט.

התסמין בפרודקשן אינו חריגה ברורה: נתיבים כמו ``search`` עוטפים את הקריאה
ב-``try/except`` ומסתעפים על ``if db is None`` (``webapp/app.py``), כלומר
המערכת מדווחת "מסד לא זמין" ומדרדרת בשקט בזמן שהמסד עצמו בריא.

**והחצי השלישי: חלון הצינון.** ההרעלה שלמעלה שימשה גם כמפסק — אחרי הכשל
הראשון כל קריאה חזרה מיד. תיקון ההרעלה לבדו גרר את הקצה הנגדי: כל קריאה
מנסה מחדש ומשלמת ``serverSelectionTimeoutMS`` שלם. נמדד מול כתובת שאינה
נפתרת, 20 קריאות: **5.0 שניות** בקוד הישן, **111.0** בלי המפסק, **5.1** עם
חלון הצינון. בסוויטה זה חצה את ``timeout = 60`` שב-``pytest.ini`` והרג עובד
xdist שלם — ``[gw5] node down: Not properly terminated``, בדיוק 60 שניות
אחרי הפלט האחרון שלו. לכן שני טסטים כאן סופרים **מופעי לקוח**, לא זמן:
זמן הוא מדד רועש ב-CI, ומספר ניסיונות ההתחברות הוא הסיבה עצמה.

הבדיקות כאן אינן דורשות מונגו אמיתי: הן מחליפות את ``MongoClient`` בדמה
שאפשר להאט או להכשיל בדיוק בנקודה הרלוונטית.
"""

from __future__ import annotations

import threading
import time

import pytest


class _FakeDatabase:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeClient:
    """דמה של ``MongoClient`` שאפשר להאט או להכשיל ב-``server_info``."""

    def __init__(self, *_a, delay: float = 0.0, fail: bool = False, **_k) -> None:
        self._delay = delay
        self._fail = fail
        self.closed = False

    def server_info(self):
        if self._delay:
            time.sleep(self._delay)
        if self._fail:
            raise RuntimeError("תקלת רשת מדומה")
        return {"version": "8.0.0-fake"}

    def __getitem__(self, name):
        return _FakeDatabase(name)

    def close(self):
        self.closed = True


@pytest.fixture(scope="module", autouse=True)
def _drain_the_background_db_pollers():
    """מנתק את תהליכוני הרקע מ-``webapp.app.get_db`` למשך הקובץ הזה.

    ``webapp/push_api.py`` מריץ ``push-sender`` — תהליכון דמון עם
    ``while True`` שקורא ל-``webapp.app.get_db()`` בכל סבב. **הוא הקורא
    המקביל האמיתי**, ובזכותו המרוץ שהבדיקות כאן מתארות אינו תיאורטי; אבל
    הוא גם מזהם, כי הוא נוגע בדיוק באותם גלובלים. נצפה בפועל: סבב שלו
    באמצע בדיקה פרסם ``client`` משלו, והבדיקה ספרה אפס ניסיונות התחברות.

    ההשתקה לבדה אינה מספיקה — סבב שכבר נכנס ל-``_send_due_once`` פתר את
    השמות לפני ההחלפה, והוא עדיין בדרכו פנימה. לכן: משתיקים את הסבבים
    הבאים, ואז **מנקזים** את זה שבתנועה. הלולאה ישנה לפחות 20 שניות בין
    סבבים, ולכן אחרי הניקוז לא נותר אף אחד.

    לא נגענו בקוד הייצור בכוונה: ``webapp/app.py`` מחזיק שומר מוכן לכך
    (``_is_webapp_runtime``, שכבר מונע את ה-backup scheduler בתהליך שאינו
    webapp), אבל הוספתו ל-``push_api`` הייתה משנה איזה תהליך שולח פוש
    בפרודקשן — החלטה שאינה חלק מהתיקון הזה.
    """
    import webapp.app as wa
    import webapp.push_api as push_api

    saved = push_api._send_due_once
    push_api._send_due_once = lambda *a, **k: None
    try:
        lock = wa.__dict__.setdefault("_DB_INIT_LOCK", threading.Lock())
        deadline = time.monotonic() + 40.0
        while time.monotonic() < deadline:
            with lock:  # ממתין לניסיון שכבר בתוך הנעילה
                pass
            before = (wa.client, wa.__dict__.get("_DB_LAST_CONNECT_FAILURE_AT"))
            # ``serverSelectionTimeoutMS`` המלא הוא 5 שניות; אם דבר לא זז
            # יותר מזה, אין סבב בתנועה.
            time.sleep(6.0)
            if (wa.client, wa.__dict__.get("_DB_LAST_CONNECT_FAILURE_AT")) == before:
                break
        yield
    finally:
        push_api._send_due_once = saved


@pytest.fixture
def app_module(monkeypatch):
    """מבודד את הגלובלים של ``webapp.app`` ומשחזר אותם בסוף.

    ``monkeypatch.setattr`` מטפל בשחזור, כך שגם בדיקה שנופלת אינה מותירה
    את המודול מחובר למסד מדומה עבור שאר החבילה.
    """
    import webapp.app as wa

    monkeypatch.setattr(wa, "client", None, raising=False)
    monkeypatch.setattr(wa, "db", None, raising=False)
    monkeypatch.setattr(wa, "MONGODB_URL", "mongodb://fake-host:27017", raising=False)
    monkeypatch.setattr(wa, "DATABASE_NAME", "cktest_get_db_publish", raising=False)
    # מצב הצינון הוא גלובל של המודול, ולכן כשל מקובץ אחר היה מדליק את
    # המפסק כאן ומחזיר None לפני שהבדיקה הספיקה לרוץ.
    monkeypatch.setattr(wa, "_DB_LAST_CONNECT_FAILURE_AT", None, raising=False)
    return wa


def _expire_the_cooldown(wa, monkeypatch) -> None:
    """מקדם את השעון מעבר לחלון הצינון, בלי לחכות בפועל.

    ``_connect_is_cooling_down`` נשען על ``time.monotonic``, ולכן מספיק
    להזיז את סימן הכשל אחורה.
    """
    if wa._DB_LAST_CONNECT_FAILURE_AT is None:
        return
    past = wa._DB_LAST_CONNECT_FAILURE_AT - (wa._connect_cooldown_seconds() + 1.0)
    monkeypatch.setattr(wa, "_DB_LAST_CONNECT_FAILURE_AT", past, raising=False)


def test_a_concurrent_caller_never_receives_none(app_module, monkeypatch):
    """הקורא השני נכנס בדיוק בזמן סיבוב הרשת של ``server_info``."""
    wa = app_module
    created: list[_FakeClient] = []

    def _factory(*a, **k):
        c = _FakeClient(*a, delay=0.5, **k)
        created.append(c)
        return c

    monkeypatch.setattr(wa, "MongoClient", _factory, raising=True)

    results: dict[str, object] = {}

    def _call(name: str, delay: float) -> None:
        time.sleep(delay)
        try:
            results[name] = wa.get_db()
        except BaseException as exc:  # noqa: BLE001 — נרשם ומדווח באסרשן
            results[name] = exc

    initializer = threading.Thread(target=_call, args=("initializer", 0.0))
    bystander = threading.Thread(target=_call, args=("bystander", 0.25))
    initializer.start()
    bystander.start()
    initializer.join(timeout=10)
    bystander.join(timeout=10)

    assert len(created) == 1, f"נוצרו {len(created)} לקוחות — הנעילה לא החזיקה"
    assert isinstance(results.get("initializer"), _FakeDatabase)
    assert isinstance(results.get("bystander"), _FakeDatabase), (
        f"קורא מקביל קיבל {results.get('bystander')!r} במקום מסד — "
        f"השומר ``client`` פורסם לפני ``db``"
    )


def test_a_failed_connection_does_not_poison_the_module(app_module, monkeypatch):
    """אחרי כשל חולף, וברגע שחלון הצינון עבר, ההתחברות מנוסה שוב ומצליחה.

    זהו הבאג המקורי: קודם ``client`` נשאר מוצב על לקוח שבור, ולכן שום
    קריאה עתידית לא ניסתה שוב — לנצח. הבדיקה מקדמת את השעון במקום לחכות,
    כדי שלא תוסיף שניות לסוויטה.
    """
    wa = app_module
    created: list[_FakeClient] = []
    state = {"fail_next": True}

    def _factory(*a, **k):
        c = _FakeClient(*a, fail=state["fail_next"], **k)
        state["fail_next"] = False
        created.append(c)
        return c

    monkeypatch.setattr(wa, "MongoClient", _factory, raising=True)

    with pytest.raises(RuntimeError):
        wa.get_db()

    assert wa.client is None, "לקוח שנכשל נשאר מוצב כשומר, וחוסם כל אתחול עתידי"
    assert created[0].closed, "הלקוח שלא פורסם לא נסגר — דליפת חיבורים בכל כשל"

    _expire_the_cooldown(wa, monkeypatch)

    assert isinstance(wa.get_db(), _FakeDatabase), (
        "הקריאה שאחרי כשל חולף לא התאוששה גם אחרי שחלון הצינון עבר"
    )
    assert len(created) == 2, "לא נוצר לקוח חדש — האתחול דולג"
    assert wa._connect_is_cooling_down() is False, (
        "חיבור מוצלח לא ניקה את סימן הכשל, והמפסק היה נדלק שוב לשווא"
    )


def test_a_call_inside_the_cooldown_does_not_dial_at_all(app_module, monkeypatch):
    """**זו הבדיקה שנופלת על הגרסה שהקפיאה את ה-CI.**

    היא סופרת מופעי ``MongoClient`` ולא זמן. בלי המפסק, הקריאה השנייה בונה
    לקוח שני ומשלמת ``serverSelectionTimeoutMS`` שלם — ובסוויטה אמיתית
    מספיק שלוש-עשרה כאלה כדי לחצות את ``timeout = 60`` ולהרוג עובד xdist.
    """
    wa = app_module
    created: list[_FakeClient] = []

    def _factory(*a, **k):
        c = _FakeClient(*a, fail=True, **k)
        created.append(c)
        return c

    monkeypatch.setattr(wa, "MongoClient", _factory, raising=True)

    with pytest.raises(RuntimeError):
        wa.get_db()
    assert len(created) == 1

    for _ in range(12):
        wa.get_db()

    assert len(created) == 1, (
        f"נוצרו {len(created)} לקוחות במקום אחד — כל קריאה בתוך חלון הצינון "
        f"משלמת timeout מלא, וזה מה שהרג את gw5 ב-CI"
    )


def test_a_call_inside_the_cooldown_returns_none_and_does_not_raise(app_module, monkeypatch):
    """נעילת חוזה מול 96 אתרי קריאה שאינם עטופים ב-``try``.

    ``None`` הוא חוזה קיים, לא בחירה חדשה: כך התנהג הקוד מאז ומתמיד בכל
    קריאה שאחרי הכשל הראשון. מה שהשתנה הוא שהוא זמני ולא נצחי.
    """
    wa = app_module
    monkeypatch.setattr(wa, "MongoClient", lambda *a, **k: _FakeClient(fail=True), raising=True)

    with pytest.raises(RuntimeError):
        wa.get_db()

    # בלי try/except במכוון — חריגה כאן היא בדיוק הכשל שהבדיקה מחפשת
    assert wa.get_db() is None


def test_the_cooldown_can_be_switched_off(app_module, monkeypatch):
    """``MONGODB_CONNECT_RETRY_COOLDOWN_SECONDS=0`` מכבה את המפסק לגמרי.

    בלי הטסט הזה, ערך שאינו נקרא היה נראה כמו מתג עובד.
    """
    wa = app_module
    monkeypatch.setenv("MONGODB_CONNECT_RETRY_COOLDOWN_SECONDS", "0")
    created: list[_FakeClient] = []

    def _factory(*a, **k):
        c = _FakeClient(*a, fail=True, **k)
        created.append(c)
        return c

    monkeypatch.setattr(wa, "MongoClient", _factory, raising=True)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            wa.get_db()

    assert len(created) == 2, "המפסק כבוי, ולכן כל קריאה אמורה לנסות מחדש"


def test_the_module_is_not_left_connected_to_a_fake(app_module):
    """נעילת היקף: הפיקסצ'ר מבודד, כדי שהדמה לא תדלוף לשאר החבילה.

    בלי זה, בדיקה שנופלת באמצע הייתה משאירה את ``webapp.app.db`` מוצב על
    ``_FakeDatabase``, וכל קובץ שרץ אחריה היה נכשל מסיבה שאינה קשורה.
    """
    assert app_module.client is None
    assert app_module.db is None

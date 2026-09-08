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
    return wa


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
    """אחרי כשל חולף, הקריאה הבאה חייבת לנסות שוב ולהצליח."""
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

    assert isinstance(wa.get_db(), _FakeDatabase), (
        "הקריאה שאחרי כשל חולף לא התאוששה"
    )
    assert len(created) == 2, "לא נוצר לקוח חדש — האתחול דולג"


def test_the_module_is_not_left_connected_to_a_fake(app_module):
    """נעילת היקף: הפיקסצ'ר מבודד, כדי שהדמה לא תדלוף לשאר החבילה.

    בלי זה, בדיקה שנופלת באמצע הייתה משאירה את ``webapp.app.db`` מוצב על
    ``_FakeDatabase``, וכל קובץ שרץ אחריה היה נכשל מסיבה שאינה קשורה.
    """
    assert app_module.client is None
    assert app_module.db is None

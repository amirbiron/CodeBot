import importlib
import sys
import types


def _make_fake_activity_reporter_module(with_create=True):
    mod = types.ModuleType('activity_reporter')

    class FakeReporter:
        def __init__(self):
            self.calls = []

        def report_activity(self, user_id):
            self.calls.append(user_id)
            return None

    if with_create:
        def create_reporter(mongodb_uri=None, service_id=None, service_name=None):
            # החתימה נשמרת, מחזירה reporter מזויף
            return FakeReporter()
        mod.create_reporter = create_reporter  # type: ignore[attr-defined]
    # אין SimpleActivityReporter בשימוש בטסטים
    return mod


def test_main_does_not_import_activity_reporter_when_disabled(monkeypatch):
    # הגדרה: לא לאפשר import תקין של activity_reporter (יחסר create_reporter)
    fake_mod = _make_fake_activity_reporter_module(with_create=False)
    sys.modules['activity_reporter'] = fake_mod

    # כבה את ה-reporter
    monkeypatch.setenv('DISABLE_ACTIVITY_REPORTER', '1')

    # רענון המודול כדי להריץ את אתחול ה-bot מחדש
    import main as m
    importlib.reload(m)

    # יצירת מופע — לא אמור לנסות לייבא create_reporter
    bot = m.CodeKeeperBot()
    # אמור ליצור Noop reporter; נוודא שלמודול יש שדה reporter עם מתודה report_activity שחוזרת None
    r = getattr(m, 'reporter', None)
    assert r is not None
    assert getattr(r, 'report_activity')(123) is None


def test_main_runtime_import_when_enabled(monkeypatch):
    # אפס את הסביבה
    monkeypatch.delenv('DISABLE_ACTIVITY_REPORTER', raising=False)

    # ספק מודול activity_reporter מזויף עם create_reporter
    sys.modules['activity_reporter'] = _make_fake_activity_reporter_module(with_create=True)

    # רענון המודול כדי שיבצע import בזמן ריצה של create_reporter בתוך CodeKeeperBot
    import main as m
    importlib.reload(m)

    bot = m.CodeKeeperBot()
    r = getattr(m, 'reporter', None)
    # צריך להיות reporter מזויף עם report_activity, לא None
    assert r is not None
    assert hasattr(r, 'report_activity')
    # קריאה לא אמורה לזרוק
    assert r.report_activity(42) is None

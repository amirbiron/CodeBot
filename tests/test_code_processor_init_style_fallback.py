import importlib


def test_code_processor_style_fallback_on_exception(monkeypatch):
    mod = importlib.import_module('code_processor')
    # החלפת get_style_by_name כך שיזרוק שגיאה - אמור ליפול ל-'default'
    monkeypatch.setattr(mod, 'get_style_by_name', lambda *_a, **_k: (_ for _ in ()).throw(Exception('boom')))

    CP = getattr(mod, 'CodeProcessor')
    cp2 = CP()
    assert getattr(cp2, 'style', None) == 'default'


import sys
import types

from utils import detect_language_from_filename


def test_detect_language_from_filename_uses_domain_first(monkeypatch):
    # ספק מודול דמה תואם import עם מחלקה LanguageDetector
    fake_mod = types.ModuleType("language_detector")
    LD = type("LD", (), {"detect_language": staticmethod(lambda code=None, filename=None: "x-test")})
    setattr(fake_mod, "LanguageDetector", LD)
    monkeypatch.setitem(sys.modules, 'src.domain.services.language_detector', fake_mod)
    assert detect_language_from_filename("ANY") == "x-test"


def test_detect_language_from_filename_fallback_mapping(monkeypatch):
    # Make domain import fail
    monkeypatch.setitem(sys.modules, 'src.domain.services.language_detector', None)
    out = detect_language_from_filename("README.md")
    assert out == "markdown"


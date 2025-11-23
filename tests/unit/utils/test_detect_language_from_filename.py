import sys
import types

from utils import detect_language_from_filename


def test_detect_language_from_filename_uses_domain_first(monkeypatch):
    fake_domain = types.SimpleNamespace(
        LanguageDetector=type("LD", (), {"detect_language": staticmethod(lambda code, fn: "x-test")})
    )
    monkeypatch.setitem(sys.modules, 'src.domain.services.language_detector', fake_domain)
    assert detect_language_from_filename("ANY") == "x-test"


def test_detect_language_from_filename_fallback_mapping(monkeypatch):
    # Make domain import fail
    monkeypatch.setitem(sys.modules, 'src.domain.services.language_detector', None)
    out = detect_language_from_filename("README.md")
    assert out == "markdown"


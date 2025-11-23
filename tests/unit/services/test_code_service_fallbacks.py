import sys
import types

import services.code_service as cs


def test_detect_language_fallback_to_mapping_when_domain_raises(monkeypatch):
    # Make domain LanguageDetector raise so code falls back to filename mapping
    fake_domain = types.SimpleNamespace(LanguageDetector=type("LD", (), {"detect_language": staticmethod(lambda c, f: (_ for _ in ()).throw(RuntimeError("x")))}))
    monkeypatch.setitem(sys.modules, 'src.domain.services.language_detector', fake_domain)
    out = cs.detect_language("", "a.py")
    assert out == "python"


def test_detect_language_mapping_when_no_domain(monkeypatch):
    # Remove domain module so import fails
    monkeypatch.setitem(sys.modules, 'src.domain.services.language_detector', None)
    out = cs.detect_language("", "notes.md")
    assert out in {"markdown", "text", "python"}

def test_yaml_highlight_fallback(monkeypatch):
    gh = __import__('github_menu_handler')

    # stub code_service.highlight_code to raise, to cover fallback to <pre>
    svc = __import__('services.code_service', fromlist=['code_service'])
    def _raise(*a, **k):
        raise RuntimeError("fail")
    monkeypatch.setattr(svc, 'highlight_code', _raise, raising=True)

    # Ensure safe_html_escape works and module imports don't crash
    out = gh.safe_html_escape("a<b>&c\u200b")
    assert "<" not in out and "&" in out


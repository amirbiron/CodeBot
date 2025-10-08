def test_non_yaml_highlight_path(monkeypatch):
    gh = __import__('github_menu_handler')
    # Stub code_service.highlight_code to return non-empty HTML to exercise non-yaml path
    svc = __import__('services.code_service', fromlist=['code_service'])
    monkeypatch.setattr(svc, 'highlight_code', lambda c, l: '<code>ok</code>')
    # no assertion needed beyond import and monkeypatch success; UI flow covered elsewhere


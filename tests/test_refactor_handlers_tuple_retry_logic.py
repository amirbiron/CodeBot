def test_refactor_call_files_api_returns_none_without_facade(monkeypatch):
    import refactor_handlers as rh

    monkeypatch.setattr(rh, "_get_files_facade_or_none", lambda: None)
    assert rh._call_files_api("get_latest_version", 1, "x") is None


def test_refactor_call_files_api_returns_facade_value(monkeypatch):
    import refactor_handlers as rh

    class _Facade:
        def get_regular_files_paginated(self, user_id, page=1, per_page=10):
            return ([], 0)

    monkeypatch.setattr(rh, "_get_files_facade_or_none", lambda: _Facade())
    assert rh._call_files_api("get_regular_files_paginated", 1, page=1, per_page=10) == ([], 0)


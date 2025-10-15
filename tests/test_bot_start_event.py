def test_bot_start_event_emitted(monkeypatch):
    import importlib
    import sys

    # Ensure a clean import of main to catch top-level emit_event
    if 'main' in sys.modules:
        sys.modules.pop('main')

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))

    # Create a shim module for observability to provide emit_event
    import types
    fake_obs = types.SimpleNamespace(
        setup_structlog_logging=lambda *_a, **_k: None,
        init_sentry=lambda: None,
        bind_request_id=lambda *_a, **_k: None,
        generate_request_id=lambda: "abcd1234",
        emit_event=_emit,
    )

    sys.modules['observability'] = fake_obs

    mod = importlib.import_module('main')

    assert any(e[0] == "bot_start" for e in captured.get("events", []))

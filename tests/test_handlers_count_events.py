import pytest


def test_handlers_count_events_emitted(monkeypatch):
    import main as mod

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    bot = mod.CodeKeeperBot()

    # Look for before/after/count events
    evts = [e[0] for e in captured.get("events", [])]
    assert "handlers_count_before" in evts
    assert "handlers_count_after" in evts
    assert "conversation_handler_added" in evts

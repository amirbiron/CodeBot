import sys
import types
import observability as obs


def test_emit_event_error_sends_to_sentry_with_request_id(monkeypatch):
    # Prepare fake sentry_sdk with push_scope and capture_message
    sentry_mod = types.ModuleType("sentry_sdk")
    captured = {"messages": [], "tags": []}

    class _Scope:
        def set_tag(self, k, v):
            captured["tags"].append((k, v))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _push_scope():
        return _Scope()

    def _capture_message(msg, level=None):
        captured["messages"].append((msg, level))

    sentry_mod.push_scope = _push_scope
    sentry_mod.capture_message = _capture_message
    sys.modules["sentry_sdk"] = sentry_mod

    # Use a dummy logger to avoid side effects
    class _Logger:
        def info(self, **fields):
            pass

        def warning(self, **fields):
            pass

        def error(self, **fields):
            pass

    monkeypatch.setattr(obs.structlog, "get_logger", lambda: _Logger())

    obs.emit_event("evt_error", severity="error", request_id="rid-123", error="boom")

    # Verify Sentry received a message and the tag was set
    assert any(t[0] == "request_id" and t[1] == "rid-123" for t in captured["tags"])  # tag exists
    assert any("boom" in (m[0] or "") for m in captured["messages"])  # message contains error text

import pytest

import observability as obs


@pytest.fixture(autouse=True)
def _clear_single_error_state(monkeypatch):
    # Reset env and internal rate-limit state between tests
    for key in [
        "ALERT_EACH_ERROR",
        "ALERT_EACH_ERROR_INCLUDE",
        "ALERT_EACH_ERROR_EXCLUDE",
        "ALERT_EACH_ERROR_COOLDOWN_SECONDS",
    ]:
        monkeypatch.delenv(key, raising=False)
    obs._SINGLE_ERROR_ALERT_LAST_TS.clear()
    yield
    obs._SINGLE_ERROR_ALERT_LAST_TS.clear()


class _Recorder:
    def __init__(self):
        self.calls = []

    def record(self, *, name: str, severity: str, summary: str, details):
        self.calls.append(
            {
                "name": name,
                "severity": severity,
                "summary": summary,
                "details": details,
            }
        )


def _patch_emit_internal_alert(monkeypatch, recorder: _Recorder):
    import internal_alerts as ia

    def _stub(name: str, severity: str = "info", summary: str = "", **details):
        recorder.record(name=name, severity=severity, summary=summary, details=details)

    monkeypatch.setattr(ia, "emit_internal_alert", _stub)


def test_single_error_alert_enabled_triggers(monkeypatch):
    rec = _Recorder()
    _patch_emit_internal_alert(monkeypatch, rec)

    monkeypatch.setenv("ALERT_EACH_ERROR", "true")
    # Stable time for deterministic cooldown behavior
    monkeypatch.setattr(obs.time, "time", lambda: 1000.0)

    obs.emit_event("db_error", severity="error", error_code="DB-1", operation="save")

    assert len(rec.calls) == 1
    assert rec.calls[0]["name"] == "db_error"
    assert rec.calls[0]["severity"] in ("error", "critical", "warn", "info")
    # Summary contains sanitized hints
    assert "DB-1" in rec.calls[0]["summary"]
    assert "save" in rec.calls[0]["summary"]


def test_single_error_alert_cooldown_applies(monkeypatch):
    rec = _Recorder()
    _patch_emit_internal_alert(monkeypatch, rec)

    monkeypatch.setenv("ALERT_EACH_ERROR", "true")
    # Default cooldown = 120s
    t0 = 2000.0
    monkeypatch.setattr(obs.time, "time", lambda: t0)
    obs.emit_event("db_error", severity="error", error_code="DB-2", operation="save")

    # Within cooldown window -> no second alert
    monkeypatch.setattr(obs.time, "time", lambda: t0 + 1.0)
    obs.emit_event("db_error", severity="error", error_code="DB-2", operation="save")

    # After cooldown window -> second alert
    monkeypatch.setattr(obs.time, "time", lambda: t0 + 121.0)
    obs.emit_event("db_error", severity="error", error_code="DB-2", operation="save")

    assert len(rec.calls) == 2


def test_single_error_alert_include_filters(monkeypatch):
    rec = _Recorder()
    _patch_emit_internal_alert(monkeypatch, rec)

    monkeypatch.setenv("ALERT_EACH_ERROR", "true")
    monkeypatch.setattr(obs.time, "time", lambda: 3000.0)

    # Does not match include -> suppressed
    monkeypatch.setenv("ALERT_EACH_ERROR_INCLUDE", "api_*,run_*")
    obs.emit_event("db_error", severity="error", error_code="DB-3", operation="save_doc")
    assert len(rec.calls) == 0

    # Matches include by event name -> allowed
    obs._SINGLE_ERROR_ALERT_LAST_TS.clear()
    monkeypatch.setenv("ALERT_EACH_ERROR_INCLUDE", "db_*")
    obs.emit_event("db_error", severity="error", error_code="DB-3", operation="save_doc")
    assert len(rec.calls) == 1


def test_single_error_alert_exclude_takes_precedence(monkeypatch):
    rec = _Recorder()
    _patch_emit_internal_alert(monkeypatch, rec)

    monkeypatch.setenv("ALERT_EACH_ERROR", "true")
    monkeypatch.setenv("ALERT_EACH_ERROR_INCLUDE", "db_*")
    monkeypatch.setenv("ALERT_EACH_ERROR_EXCLUDE", "db_*")
    monkeypatch.setattr(obs.time, "time", lambda: 4000.0)

    obs.emit_event("db_error", severity="error", error_code="DB-4", operation="save")
    assert len(rec.calls) == 0


def test_single_error_alert_works_for_critical(monkeypatch):
    rec = _Recorder()
    _patch_emit_internal_alert(monkeypatch, rec)

    monkeypatch.setenv("ALERT_EACH_ERROR", "true")
    monkeypatch.setattr(obs.time, "time", lambda: 5000.0)

    obs.emit_event("hard_fail", severity="critical", error_code="X-1", operation="run")
    assert len(rec.calls) == 1
    assert rec.calls[0]["name"] == "hard_fail"
    assert rec.calls[0]["severity"] in ("error", "critical")

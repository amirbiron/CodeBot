import types
import os
import pytest

import observability as obs


@pytest.fixture(autouse=True)
def _reset_aggregator_singleton(monkeypatch):
    # Ensure clean aggregator singleton per test
    monkeypatch.setattr(obs, "_LOG_AGG_SINGLETON", None, raising=False)
    monkeypatch.setenv("LOG_AGGREGATOR_ENABLED", "")
    monkeypatch.delenv("LOG_AGGREGATOR_SHADOW", raising=False)
    yield
    monkeypatch.setattr(obs, "_LOG_AGG_SINGLETON", None, raising=False)


def _write_es(tmp_path, text: str):
    p = tmp_path / "es.yml"
    p.write_text(text, encoding="utf-8")
    return p


def _write_alerts(tmp_path, *, window_minutes=5, min_count=3, cooldown_minutes=10, immediate=("critical",)):
    p = tmp_path / "alerts.yml"
    p.write_text(
        (
            "{"  # JSON is subset of YAML
            f"\"window_minutes\": {window_minutes}, "
            f"\"min_count_default\": {min_count}, "
            f"\"cooldown_minutes\": {cooldown_minutes}, "
            f"\"immediate_categories\": {list(immediate)}"
            "}"
        ),
        encoding="utf-8",
    )
    return p


def _patch_emit_internal_alert(monkeypatch):
    calls = []
    import internal_alerts as ia

    def _stub(name: str, severity: str = "info", summary: str = "", **details):
        calls.append({"name": name, "severity": severity, "summary": summary, **details})

    monkeypatch.setattr(ia, "emit_internal_alert", _stub)
    return calls


def test_processor_integration_grouping_and_critical(monkeypatch, tmp_path):
    # Configure custom signatures and grouping thresholds
    es = _write_es(
        tmp_path,
        '{"critical": ["OOMKilled"], "network_db": ["socket hang up"], "noise_allowlist": ["Broken pipe|499|context canceled"]}',
    )
    alerts = _write_alerts(tmp_path, window_minutes=5, min_count=3, cooldown_minutes=10)

    # Enable in-process aggregator
    monkeypatch.setenv("LOG_AGGREGATOR_ENABLED", "1")
    monkeypatch.setenv("ERROR_SIGNATURES_PATH", str(es))
    monkeypatch.setenv("ALERTS_GROUPING_CONFIG", str(alerts))

    # Patch sinks and time
    calls = _patch_emit_internal_alert(monkeypatch)
    base = 1_800_000_000.0
    import monitoring.log_analyzer as la

    monkeypatch.setattr(la.time, "time", lambda: base + 0)

    # Ensure structlog is configured with our processor
    obs.setup_structlog_logging("INFO")

    # 1) Immediate critical on OOM
    obs.emit_event("runtime_error", severity="error", error="OOMKilled by kernel")
    assert any(c["severity"] == "critical" for c in calls)

    # 2) Grouping: 3 occurrences within window -> one anomaly alert
    calls.clear()
    monkeypatch.setattr(la.time, "time", lambda: base + 1)
    obs.emit_event("db_call_failed", severity="error", error="socket hang up during query")
    monkeypatch.setattr(la.time, "time", lambda: base + 30)
    obs.emit_event("db_call_failed", severity="error", error="socket hang up during query")
    monkeypatch.setattr(la.time, "time", lambda: base + 50)
    obs.emit_event("db_call_failed", severity="error", error="socket hang up during query")

    assert len(calls) == 1
    assert calls[0]["severity"] == "anomaly"

    # 3) Allowlist noise should not emit
    calls.clear()
    obs.emit_event("client_disconnect", severity="error", error="Broken pipe writing to client")
    assert len(calls) == 0


def test_processor_shadow_mode_no_emission(monkeypatch, tmp_path):
    # Configure minimal signatures to match a known pattern
    es = _write_es(tmp_path, '{"network_db": ["socket hang up"], "noise_allowlist": []}')
    alerts = _write_alerts(tmp_path, window_minutes=5, min_count=1, cooldown_minutes=10)

    monkeypatch.setenv("LOG_AGGREGATOR_ENABLED", "1")
    monkeypatch.setenv("LOG_AGGREGATOR_SHADOW", "1")
    monkeypatch.setenv("ERROR_SIGNATURES_PATH", str(es))
    monkeypatch.setenv("ALERTS_GROUPING_CONFIG", str(alerts))

    calls = _patch_emit_internal_alert(monkeypatch)

    # Configure structlog
    obs.setup_structlog_logging("INFO")

    # Emit a single matching line; in shadow mode, no sink emission should occur
    obs.emit_event("db_error", severity="error", error="socket hang up")
    assert len(calls) == 0

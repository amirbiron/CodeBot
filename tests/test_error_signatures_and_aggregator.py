import types

import pytest

from monitoring.error_signatures import ErrorSignatures
from monitoring.log_analyzer import LogEventAggregator


@pytest.mark.asyncio
async def test_error_signatures_classify_and_noise(tmp_path):
    cfg = tmp_path / "es.yml"
    cfg.write_text(
        '{"critical": ["OOMKilled"], "network_db": ["ECONNRESET"], "noise_allowlist": ["Broken pipe|499|context canceled"]}',
        encoding="utf-8",
    )
    es = ErrorSignatures(str(cfg))
    assert es.classify("Container OOMKilled yesterday") == "critical"
    assert es.classify("random info line") is None
    assert es.is_noise("client disconnected Broken pipe") is True
    assert es.is_noise("context canceled by user") is True


def _make_alerts_cfg(tmp_path, *, window_minutes=5, min_count=3, cooldown_minutes=10, immediate=("critical",)):
    cfg = tmp_path / "alerts.yml"
    data = (
        '{"window_minutes": %d, "min_count_default": %d, "cooldown_minutes": %d, "immediate_categories": %s}'
        % (window_minutes, min_count, cooldown_minutes, str(list(immediate)))
    )
    cfg.write_text(data, encoding="utf-8")
    return cfg


def test_aggregator_grouping_and_cooldown(monkeypatch, tmp_path):
    # Prepare configs
    es_path = tmp_path / "es.yml"
    es_path.write_text(
        '{"critical": ["OOMKilled"], "network_db": ["ECONNRESET|socket hang up"], "noise_allowlist": ["Broken pipe|499|context canceled"]}',
        encoding="utf-8",
    )
    alerts_path = _make_alerts_cfg(tmp_path, window_minutes=5, min_count=3, cooldown_minutes=10)

    # Capture emitted alerts via monkeypatch
    calls = []

    def _emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):
        calls.append({"name": name, "severity": severity, "summary": summary, **details})

    import internal_alerts as ia

    monkeypatch.setattr(ia, "emit_internal_alert", _emit_internal_alert)

    # Use controlled time sequence
    base = 1_700_000_000.0
    agg = LogEventAggregator(signatures_path=str(es_path), alerts_config_path=str(alerts_path))

    # Three similar lines within window -> one anomaly alert
    assert agg.analyze_line("socket hang up while calling DB", now_ts=base + 1) is None
    assert agg.analyze_line("socket hang up while calling DB", now_ts=base + 30) is None
    out = agg.analyze_line("socket hang up while calling DB", now_ts=base + 50)
    assert out is not None  # emitted

    assert len(calls) == 1
    assert calls[0]["severity"] == "anomaly"
    assert "Fingerprint:" in calls[0]["summary"]

    # Same fingerprint within cooldown should NOT emit again
    agg.analyze_line("socket hang up while calling DB", now_ts=base + 55)
    assert len(calls) == 1

    # After cooldown passes (>=600s after the first alert at base+50), another series should emit again
    agg.analyze_line("socket hang up while calling DB", now_ts=base + 650)
    agg.analyze_line("socket hang up while calling DB", now_ts=base + 651)
    agg.analyze_line("socket hang up while calling DB", now_ts=base + 652)
    assert len(calls) == 2


def test_aggregator_immediate_critical(monkeypatch, tmp_path):
    # Prepare configs with default immediate_categories=["critical"]
    es_path = tmp_path / "es.yml"
    es_path.write_text('{"critical": ["OOMKilled"], "noise_allowlist": []}', encoding="utf-8")
    alerts_path = _make_alerts_cfg(tmp_path, window_minutes=5, min_count=3, cooldown_minutes=10, immediate=("critical",))

    calls = []

    def _emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):
        calls.append({"name": name, "severity": severity, "summary": summary, **details})

    import internal_alerts as ia

    monkeypatch.setattr(ia, "emit_internal_alert", _emit_internal_alert)

    base = 1_700_000_000.0
    agg = LogEventAggregator(signatures_path=str(es_path), alerts_config_path=str(alerts_path))

    # Single OOM line should immediately emit a critical alert
    out = agg.analyze_line("Process OOMKilled by kernel", now_ts=base + 5)
    assert out is not None
    assert len(calls) == 1
    assert calls[0]["severity"] == "critical"

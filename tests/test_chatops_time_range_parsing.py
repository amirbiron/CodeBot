import types
from datetime import datetime, timedelta, timezone

import pytest


def _fixed_now() -> datetime:
    return datetime(2025, 12, 16, 10, 15, 0, tzinfo=timezone.utc)


def test_parse_time_range_since_keeps_remaining_args(monkeypatch):
    from chatops import time_range as tr

    monkeypatch.setattr(tr, "_utcnow", _fixed_now, raising=True)

    rng, remaining = tr.parse_time_range(["--since", "15m", "--endpoint", "/api/x"])
    assert rng.end == _fixed_now()
    assert rng.start == _fixed_now() - timedelta(minutes=15)
    assert remaining == ["--endpoint", "/api/x"]


def test_parse_time_range_from_to_naive_assumes_utc(monkeypatch):
    from chatops import time_range as tr

    monkeypatch.setattr(tr, "_utcnow", _fixed_now, raising=True)

    rng, remaining = tr.parse_time_range(
        ["--from", "2025-12-16T10:00", "--to", "2025-12-16T10:15"]
    )
    assert remaining == []
    assert rng.start.tzinfo is not None and rng.end.tzinfo is not None
    assert rng.start == datetime(2025, 12, 16, 10, 0, tzinfo=timezone.utc)
    assert rng.end == datetime(2025, 12, 16, 10, 15, tzinfo=timezone.utc)


def test_parse_time_range_rejects_window_over_max(monkeypatch):
    from chatops import time_range as tr

    monkeypatch.setattr(tr, "_utcnow", _fixed_now, raising=True)

    with pytest.raises(tr.TimeRangeParseError):
        tr.parse_time_range(["--since", "25h"], max_window=timedelta(hours=24))


def test_parse_time_range_rejects_mixing_since_and_from_to(monkeypatch):
    from chatops import time_range as tr

    monkeypatch.setattr(tr, "_utcnow", _fixed_now, raising=True)

    with pytest.raises(tr.TimeRangeParseError):
        tr.parse_time_range(
            [
                "--since",
                "15m",
                "--from",
                "2025-12-16T10:00",
                "--to",
                "2025-12-16T10:15",
            ]
        )


@pytest.mark.asyncio
async def test_status_command_calls_metrics_storage_with_range(monkeypatch):
    import os
    from bot_handlers import AdvancedBotHandlers

    # Admin
    os.environ["ADMIN_USER_IDS"] = "1"

    # Fix now used by time parser
    from chatops import time_range as tr

    monkeypatch.setattr(tr, "_utcnow", _fixed_now, raising=True)

    # Stub DB checker to avoid real connections
    import bot_handlers as bh

    async def _ok():
        return True

    monkeypatch.setattr(bh, "check_db_connection", _ok, raising=False)

    # Capture metrics_storage calls
    from monitoring import metrics_storage as ms

    captured = {}

    def _cap(name):
        def _fn(**kwargs):
            captured[name] = kwargs
            if name == "aggregate_error_ratio":
                return {"total": 10, "errors": 2}
            if name == "aggregate_latency_percentiles":
                return {"p50": 0.1, "p95": 0.5, "p99": 0.9}
            if name == "aggregate_top_endpoints":
                return [{"endpoint": "/api/x", "method": "GET", "count": 3, "avg_duration": 0.2, "max_duration": 1.0}]
            return {}

        return _fn

    monkeypatch.setattr(ms, "aggregate_error_ratio", _cap("aggregate_error_ratio"), raising=False)
    monkeypatch.setattr(ms, "aggregate_latency_percentiles", _cap("aggregate_latency_percentiles"), raising=False)
    monkeypatch.setattr(ms, "aggregate_top_endpoints", _cap("aggregate_top_endpoints"), raising=False)

    # Minimal app/update/context stubs
    class _Msg:
        def __init__(self):
            self.texts = []

        async def reply_text(self, text, *a, **k):
            self.texts.append(text)

    class _Update:
        def __init__(self):
            self.message = _Msg()
            self.effective_user = types.SimpleNamespace(id=1)

    class _Context:
        def __init__(self, args=None):
            self.args = args or []
            self.user_data = {}
            self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_once=lambda *a, **k: None))

    class _App:
        def add_handler(self, *a, **k):
            return None

    adv = AdvancedBotHandlers(_App())
    upd = _Update()
    ctx = _Context(args=["--since", "15m"])

    await adv.status_command(upd, ctx)

    assert "aggregate_error_ratio" in captured
    assert captured["aggregate_error_ratio"]["start_dt"] == _fixed_now() - timedelta(minutes=15)
    assert captured["aggregate_error_ratio"]["end_dt"] == _fixed_now()
    out = "\n".join(upd.message.texts)
    assert "Report for:" in out


@pytest.mark.asyncio
async def test_errors_command_explicit_time_range_filters(monkeypatch):
    import os
    from bot_handlers import AdvancedBotHandlers

    os.environ["ADMIN_USER_IDS"] = "1"

    from chatops import time_range as tr

    monkeypatch.setattr(tr, "_utcnow", _fixed_now, raising=True)

    # Seed recent errors (some in-range, some out-of-range)
    import observability as obs

    def _fake_recent(limit=200):
        return [
            {
                "ts": "2025-12-16T10:05:00+00:00",
                "severity": "error",
                "endpoint": "/api/x",
                "service": "web",
                "error_signature": "SIG1",
                "error_category": "db",
                "error": "boom",
                "error_code": "E1",
                "request_id": "req-1",
            },
            {
                "ts": "2025-12-16T10:06:00+00:00",
                "severity": "warning",
                "endpoint": "/api/x",
                "service": "web",
                "error_signature": "SIG2",
                "error_category": "net",
                "error": "warn",
                "error_code": "W1",
                "request_id": "req-2",
            },
            {
                "ts": "2025-12-16T09:00:00+00:00",
                "severity": "error",
                "endpoint": "/api/x",
                "service": "web",
                "error_signature": "OLD",
                "error_category": "db",
                "error": "old",
                "error_code": "E0",
                "request_id": "req-old",
            },
        ]

    monkeypatch.setattr(obs, "get_recent_errors", _fake_recent, raising=False)

    class _Msg:
        def __init__(self):
            self.texts = []

        async def reply_text(self, text, *a, **k):
            self.texts.append(text)

    class _Update:
        def __init__(self):
            self.message = _Msg()
            self.effective_user = types.SimpleNamespace(id=1)

    class _Context:
        def __init__(self, args=None):
            self.args = args or []
            self.user_data = {}
            self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_once=lambda *a, **k: None))

    class _App:
        def add_handler(self, *a, **k):
            return None

    adv = AdvancedBotHandlers(_App())
    upd = _Update()
    ctx = _Context(
        args=[
            "--from",
            "2025-12-16T10:00",
            "--to",
            "2025-12-16T10:15",
            "--endpoint",
            "/api/x",
            "--min_severity",
            "ERROR",
        ]
    )

    await adv.errors_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Report for:" in out
    assert "SIG1" in out
    assert "SIG2" not in out  # warning filtered out by min_severity=ERROR
    assert "OLD" not in out  # outside time range


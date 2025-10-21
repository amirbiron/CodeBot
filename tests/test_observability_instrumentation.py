import types
import sys
import pytest


def _install_otel_stubs(call_log):
    # Top-level module
    otel = types.ModuleType("opentelemetry")

    # trace submodule
    trace_mod = types.ModuleType("opentelemetry.trace")

    class _SpanToken:
        def __init__(self, name):
            self.name = name
            self.attrs = {}
            self.exceptions = []

        def set_attributes(self, attrs):
            self.attrs.update(attrs or {})

        def record_exception(self, exc):
            self.exceptions.append(type(exc).__name__)

    class _SpanCM:
        def __init__(self, name):
            self.name = name
            self.token = _SpanToken(name)

        def __enter__(self):
            call_log.append(("span_enter", self.name))
            return self.token

        def __exit__(self, exc_type, exc, tb):
            call_log.append(("span_exit", self.name))
            return False

    class _Tracer:
        def start_as_current_span(self, name):
            call_log.append(("start_span", name))
            return _SpanCM(name)

    def get_tracer(_name):
        return _Tracer()

    trace_mod.get_tracer = get_tracer

    # metrics submodule
    metrics_mod = types.ModuleType("opentelemetry.metrics")

    class _Hist:
        def __init__(self):
            self.records = []
        def record(self, value, attrs=None):
            self.records.append((float(value), dict(attrs or {})))
            call_log.append(("hist_record", value, dict(attrs or {})))

    class _Ctr:
        def __init__(self):
            self.adds = []
        def add(self, value, attrs=None):
            self.adds.append((int(value), dict(attrs or {})))
            call_log.append(("ctr_add", value, dict(attrs or {})))

    class _UpDown:
        def __init__(self):
            self.adds = []
        def add(self, value):
            self.adds.append(int(value))
            call_log.append(("updown_add", value))

    class _Meter:
        def create_histogram(self, *_a, **_k):
            return _Hist()
        def create_counter(self, *_a, **_k):
            return _Ctr()
        def create_up_down_counter(self, *_a, **_k):
            return _UpDown()

    def get_meter(_name):
        return _Meter()

    metrics_mod.get_meter = get_meter

    otel.trace = trace_mod
    otel.metrics = metrics_mod

    sys.modules["opentelemetry"] = otel
    sys.modules["opentelemetry.trace"] = trace_mod
    sys.modules["opentelemetry.metrics"] = metrics_mod


def test_traced_sync_success(monkeypatch):
    calls = []
    _install_otel_stubs(calls)
    import importlib
    mod = importlib.import_module("observability_instrumentation")

    @mod.traced(span_name="sync_ok", attributes={"k": "v"})
    def f(x):
        return x + 1

    assert f(2) == 3
    # Expect span started/ended and metrics recorded
    assert any(c[0] == "start_span" and c[1] == "sync_ok" for c in calls)
    assert any(c[0] == "hist_record" for c in calls)
    assert any(c[0] == "updown_add" and c[1] == 1 for c in calls)
    assert any(c[0] == "updown_add" and c[1] == -1 for c in calls)


def test_traced_sync_error(monkeypatch):
    calls = []
    _install_otel_stubs(calls)
    import importlib
    mod = importlib.import_module("observability_instrumentation")

    @mod.traced(span_name="sync_err")
    def boom():
        raise ValueError("x")

    with pytest.raises(ValueError):
        boom()

    # Expect error counter increment and histogram record with error attr
    assert any(c[0] == "ctr_add" for c in calls)
    error_hist = [c for c in calls if c[0] == "hist_record" and c[2].get("error")]
    assert error_hist, "expected duration histogram with error attr"


@pytest.mark.asyncio
async def test_traced_async_success(monkeypatch):
    calls = []
    _install_otel_stubs(calls)
    import importlib
    mod = importlib.import_module("observability_instrumentation")

    @mod.traced(span_name="async_ok")
    async def af(x):
        return x * 2

    assert await af(4) == 8
    assert any(c[0] == "start_span" and c[1] == "async_ok" for c in calls)
    assert any(c[0] == "hist_record" for c in calls)


def test_traced_no_otel_is_noop(monkeypatch):
    # Remove otel modules if exist
    for name in list(sys.modules.keys()):
        if name.startswith("opentelemetry"):
            sys.modules.pop(name, None)
    import importlib
    mod = importlib.import_module("observability_instrumentation")

    @mod.traced(span_name="noop")
    def f(x):
        return x

    assert f(1) == 1

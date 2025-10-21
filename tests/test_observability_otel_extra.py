import types
import sys
import importlib


def install_core_stubs():
    # opentelemetry
    otel = types.ModuleType("opentelemetry")
    # trace
    trace_mod = types.ModuleType("opentelemetry.trace")
    def _set_tracer_provider(_p):
        pass
    trace_mod.set_tracer_provider = _set_tracer_provider
    class _TracerProvider:
        def __init__(self, *a, **k): pass
        def add_span_processor(self, *a, **k): pass
    sys.modules["opentelemetry.sdk.trace"] = types.SimpleNamespace(TracerProvider=_TracerProvider)
    # export
    class _BSP:
        def __init__(self, *a, **k): pass
    sys.modules["opentelemetry.sdk.trace.export"] = types.SimpleNamespace(BatchSpanProcessor=_BSP)
    # resources
    class _Res:
        @staticmethod
        def create(attrs):
            return object()
    sys.modules["opentelemetry.sdk.resources"] = types.SimpleNamespace(Resource=_Res)
    # exporter: trace
    class _SpanExporter:
        def __init__(self, *a, **k): pass
    sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = types.SimpleNamespace(OTLPSpanExporter=_SpanExporter)

    # metrics core (optional)
    metrics_mod = types.ModuleType("opentelemetry.metrics")
    def _set_meter_provider(_p):
        pass
    metrics_mod.set_meter_provider = _set_meter_provider
    otel.metrics = metrics_mod

    otel.trace = trace_mod
    sys.modules["opentelemetry"] = otel
    sys.modules["opentelemetry.trace"] = trace_mod
    sys.modules["opentelemetry.metrics"] = metrics_mod


def test_setup_telemetry_flask_requests_pymongo(monkeypatch):
    install_core_stubs()

    # Instrumentors
    calls = {"flask": 0, "requests": 0, "pymongo": 0}

    class _FlaskInstr:
        def instrument_app(self, app):
            calls["flask"] += 1
    sys.modules["opentelemetry.instrumentation.flask"] = types.SimpleNamespace(FlaskInstrumentor=_FlaskInstr)

    class _ReqInstr:
        def instrument(self):
            calls["requests"] += 1
    sys.modules["opentelemetry.instrumentation.requests"] = types.SimpleNamespace(RequestsInstrumentor=lambda: _ReqInstr())

    class _PyMongoInstr:
        def instrument(self):
            calls["pymongo"] += 1
    sys.modules["opentelemetry.instrumentation.pymongo"] = types.SimpleNamespace(PymongoInstrumentor=lambda: _PyMongoInstr())

    # Metrics exporter optional path
    class _MetricExporter:
        def __init__(self, *a, **k):
            raise RuntimeError("no metrics endpoint")
    sys.modules["opentelemetry.exporter.otlp.proto.grpc.metric_exporter"] = types.SimpleNamespace(OTLPMetricExporter=_MetricExporter)

    class _MeterProvider:
        def __init__(self, *a, **k): pass
    class _Reader:
        def __init__(self, *a, **k): pass
    sys.modules["opentelemetry.sdk.metrics"] = types.SimpleNamespace(MeterProvider=_MeterProvider)
    sys.modules["opentelemetry.sdk.metrics.export"] = types.SimpleNamespace(PeriodicExportingMetricReader=_Reader)

    mod = importlib.import_module("observability_otel")
    # reset idempotent guard if already set
    if getattr(mod, "_OTEL_INITIALIZED", False):
        mod._OTEL_INITIALIZED = False

    class _FlaskApp: pass
    app = _FlaskApp()
    mod.setup_telemetry(service_name="svc", service_version="1", environment="test", flask_app=app)

    # All instrumentors should have been invoked (best-effort stubs)
    assert calls["requests"] == 1
    assert calls["pymongo"] == 1
    assert calls["flask"] == 1


def test_setup_telemetry_idempotent(monkeypatch):
    install_core_stubs()

    # Lightweight instrumentor stubs with counters
    cnt = {"requests": 0}
    class _ReqInstr:
        def instrument(self):
            cnt["requests"] += 1
    sys.modules["opentelemetry.instrumentation.requests"] = types.SimpleNamespace(RequestsInstrumentor=lambda: _ReqInstr())

    mod = importlib.import_module("observability_otel")
    # Reset guard
    mod._OTEL_INITIALIZED = False
    mod.setup_telemetry(service_name="svc")
    # Second call should no-op
    mod.setup_telemetry(service_name="svc")
    assert cnt["requests"] == 1


def test_str2bool_variants():
    mod = importlib.import_module("observability_otel")
    assert mod._str2bool("true") is True
    assert mod._str2bool("1") is True
    assert mod._str2bool("yes") is True
    assert mod._str2bool("on") is True
    assert mod._str2bool("false") is False
    assert mod._str2bool(None) is False


def test_tracing_skips_when_no_endpoint(monkeypatch):
    install_core_stubs()
    import importlib as _importlib

    calls = {"span_exporter": 0, "set_tp": 0}

    # Override exporter to count instantiations
    class _SpanExporter:
        def __init__(self, *a, **k):
            calls["span_exporter"] += 1

    # Override set_tracer_provider to count calls
    def _set_tp(_p):
        calls["set_tp"] += 1

    sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = types.SimpleNamespace(
        OTLPSpanExporter=_SpanExporter
    )
    sys.modules["opentelemetry.trace"].set_tracer_provider = _set_tp  # type: ignore[attr-defined]

    # Ensure no endpoint defined
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_INSECURE", raising=False)

    mod = _importlib.import_module("observability_otel")
    mod._OTEL_INITIALIZED = False
    mod.setup_telemetry(service_name="svc-no-endpoint")

    assert calls["span_exporter"] == 0
    assert calls["set_tp"] == 0


def test_tracing_enabled_with_endpoint_and_insecure(monkeypatch):
    install_core_stubs()
    import importlib as _importlib

    calls = {"span_exporter": 0, "set_tp": 0}
    insecure_args: list[bool | None] = []

    class _SpanExporter:
        def __init__(self, *a, **k):
            calls["span_exporter"] += 1
            insecure_args.append(k.get("insecure"))

    def _set_tp(_p):
        calls["set_tp"] += 1

    sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = types.SimpleNamespace(
        OTLPSpanExporter=_SpanExporter
    )
    sys.modules["opentelemetry.trace"].set_tracer_provider = _set_tp  # type: ignore[attr-defined]

    # Define endpoint and insecure=true
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otlp:4317")
    monkeypatch.setenv("OTEL_EXPORTER_INSECURE", "true")

    mod = _importlib.import_module("observability_otel")
    mod._OTEL_INITIALIZED = False
    mod.setup_telemetry(service_name="svc-with-endpoint")

    assert calls["span_exporter"] == 1
    assert calls["set_tp"] == 1
    # Ensure we passed insecure=True from env
    assert insecure_args == [True]

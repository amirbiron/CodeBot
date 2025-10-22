import sys
import types
import importlib


def install_stubs_with_metrics(calls):
    """Install minimal OpenTelemetry stubs including metrics exporter path."""
    # Root package
    otel = types.ModuleType("opentelemetry")

    # trace
    trace_mod = types.ModuleType("opentelemetry.trace")

    def _set_tracer_provider(_p):
        calls["set_tp"] = calls.get("set_tp", 0) + 1

    trace_mod.set_tracer_provider = _set_tracer_provider
    otel.trace = trace_mod
    sys.modules["opentelemetry.trace"] = trace_mod

    # metrics (module with set_meter_provider)
    metrics_mod = types.ModuleType("opentelemetry.metrics")

    def _set_meter_provider(_p):
        calls["set_meter_provider"] = calls.get("set_meter_provider", 0) + 1

    metrics_mod.set_meter_provider = _set_meter_provider
    otel.metrics = metrics_mod
    sys.modules["opentelemetry.metrics"] = metrics_mod

    sys.modules["opentelemetry"] = otel

    # sdk.trace
    class _TracerProvider:
        def __init__(self, *a, **k):
            pass

        def add_span_processor(self, *a, **k):
            pass

    sys.modules["opentelemetry.sdk.trace"] = types.SimpleNamespace(TracerProvider=_TracerProvider)

    # sdk.trace.export
    class _BSP:
        def __init__(self, *a, **k):
            pass

    sys.modules["opentelemetry.sdk.trace.export"] = types.SimpleNamespace(BatchSpanProcessor=_BSP)

    # sdk.resources
    class _Resource:
        @staticmethod
        def create(attrs):
            return object()

    sys.modules["opentelemetry.sdk.resources"] = types.SimpleNamespace(Resource=_Resource)

    # exporter: trace
    class _SpanExporter:
        def __init__(self, *a, **k):
            calls["span_exporter"] = calls.get("span_exporter", 0) + 1

    sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = types.SimpleNamespace(
        OTLPSpanExporter=_SpanExporter
    )

    # sdk.metrics
    class _MeterProvider:
        def __init__(self, *a, **k):
            calls["meter_provider"] = calls.get("meter_provider", 0) + 1

    sys.modules["opentelemetry.sdk.metrics"] = types.SimpleNamespace(MeterProvider=_MeterProvider)

    # sdk.metrics.export
    class _Reader:
        def __init__(self, *a, **k):
            calls["metric_reader"] = calls.get("metric_reader", 0) + 1

    sys.modules["opentelemetry.sdk.metrics.export"] = types.SimpleNamespace(PeriodicExportingMetricReader=_Reader)

    # exporter: metrics
    class _MetricExporter:
        def __init__(self, *a, **k):
            calls["metric_exporter"] = calls.get("metric_exporter", 0) + 1
            (calls.setdefault("metric_exporter_kwargs", [])).append(k)

    sys.modules["opentelemetry.exporter.otlp.proto.grpc.metric_exporter"] = types.SimpleNamespace(
        OTLPMetricExporter=_MetricExporter
    )

    # Instrumentations (no-op)
    class _ReqInstr:
        def instrument(self):
            calls["requests_instr"] = calls.get("requests_instr", 0) + 1

    sys.modules["opentelemetry.instrumentation.requests"] = types.SimpleNamespace(
        RequestsInstrumentor=lambda: _ReqInstr()
    )

    class _FlaskInstr:
        def instrument_app(self, app):
            calls["flask_instr"] = calls.get("flask_instr", 0) + 1

    sys.modules["opentelemetry.instrumentation.flask"] = types.SimpleNamespace(FlaskInstrumentor=_FlaskInstr)

    class _PyMongoInstr:
        def instrument(self):
            calls["pymongo_instr"] = calls.get("pymongo_instr", 0) + 1

    sys.modules["opentelemetry.instrumentation.pymongo"] = types.SimpleNamespace(
        PymongoInstrumentor=lambda: _PyMongoInstr()
    )


def _reload_module():
    if "observability_otel" in sys.modules:
        del sys.modules["observability_otel"]
    return importlib.import_module("observability_otel")


def test_metrics_skip_without_flag_even_with_endpoint(monkeypatch):
    calls = {}
    install_stubs_with_metrics(calls)

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otlp:4317")
    monkeypatch.setenv("ENABLE_METRICS", "false")

    mod = _reload_module()
    mod._OTEL_INITIALIZED = False
    mod.setup_telemetry(service_name="svc")

    assert calls.get("metric_exporter", 0) == 0
    assert calls.get("set_meter_provider", 0) == 0


def test_metrics_init_with_flag_and_endpoint_defaults_to_insecure_false(monkeypatch):
    calls = {}
    install_stubs_with_metrics(calls)

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otlp:4317")
    monkeypatch.setenv("ENABLE_METRICS", "true")
    monkeypatch.delenv("OTEL_EXPORTER_INSECURE", raising=False)

    mod = _reload_module()
    mod._OTEL_INITIALIZED = False
    mod.setup_telemetry(service_name="svc")

    assert calls.get("metric_exporter", 0) == 1
    assert calls.get("metric_reader", 0) == 1
    assert calls.get("set_meter_provider", 0) == 1
    # insecure should be False by default
    insecure_vals = [k.get("insecure") for k in calls.get("metric_exporter_kwargs", [])]
    assert insecure_vals == [False]


def test_metrics_insecure_true_propagated(monkeypatch):
    calls = {}
    install_stubs_with_metrics(calls)

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otlp:4317")
    monkeypatch.setenv("ENABLE_METRICS", "true")
    monkeypatch.setenv("OTEL_EXPORTER_INSECURE", "true")

    mod = _reload_module()
    mod._OTEL_INITIALIZED = False
    mod.setup_telemetry(service_name="svc")

    assert calls.get("metric_exporter", 0) == 1
    insecure_vals = [k.get("insecure") for k in calls.get("metric_exporter_kwargs", [])]
    assert insecure_vals == [True]

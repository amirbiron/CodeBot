import types
import sys

def test_setup_telemetry_import_safe(monkeypatch):
    # Ensure module can be imported without real OpenTelemetry installed
    # by stubbing minimal symbols.
    otel = types.ModuleType("opentelemetry")
    otel.trace = types.SimpleNamespace(set_tracer_provider=lambda *_a, **_k: None)
    otel.metrics = types.SimpleNamespace(set_meter_provider=lambda *_a, **_k: None)
    sys.modules["opentelemetry"] = otel

    # sdk.trace
    sdk_trace = types.ModuleType("opentelemetry.sdk.trace")
    class _TP:
        def __init__(self, *a, **k): pass
        def add_span_processor(self, *_a, **_k): pass
    sdk_trace.TracerProvider = _TP
    sys.modules["opentelemetry.sdk.trace"] = sdk_trace

    # sdk.trace.export
    sdk_trace_export = types.ModuleType("opentelemetry.sdk.trace.export")
    class _BSP:
        def __init__(self, *a, **k): pass
    sdk_trace_export.BatchSpanProcessor = _BSP
    sys.modules["opentelemetry.sdk.trace.export"] = sdk_trace_export

    # sdk.resources
    sdk_resources = types.ModuleType("opentelemetry.sdk.resources")
    class _Res:
        @staticmethod
        def create(*_a, **_k):
            return object()
    sdk_resources.Resource = _Res
    sys.modules["opentelemetry.sdk.resources"] = sdk_resources

    # exporter.otlp.proto.grpc.trace_exporter
    otlp_trace = types.ModuleType("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
    class _SpanExporter:
        def __init__(self, *a, **k): pass
    otlp_trace.OTLPSpanExporter = _SpanExporter
    sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = otlp_trace

    # instrumentation submodules (optional)
    sys.modules.setdefault("opentelemetry.instrumentation.requests", types.ModuleType("opentelemetry.instrumentation.requests"))
    sys.modules.setdefault("opentelemetry.instrumentation.flask", types.ModuleType("opentelemetry.instrumentation.flask"))
    sys.modules.setdefault("opentelemetry.instrumentation.pymongo", types.ModuleType("opentelemetry.instrumentation.pymongo"))

    import importlib
    mod = importlib.import_module("observability_otel")
    # Should not raise on setup without real exporters backends
    mod.setup_telemetry(service_name="test", flask_app=None)

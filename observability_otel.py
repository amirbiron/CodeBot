"""
OpenTelemetry setup (safe, optional, idempotent).

This module configures tracing (OTLP exporter) and auto-instrumentation for:

- Flask (when a Flask app instance is provided)
- requests (HTTP client)
- PyMongo

Design goals:

- Fail-open: if OpenTelemetry packages are not installed or misconfigured,
  setup_telemetry silently returns without raising.
- Idempotent: multiple calls are safe; only the first successful init takes effect.
- Non-invasive: avoid changing existing structlog configuration; we rely on
  observability._add_otel_ids to inject trace_id/span_id when tracing is active.
"""
from __future__ import annotations

from typing import Any
import os

_OTEL_INITIALIZED: bool = False


def _str2bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def setup_telemetry(
    *,
    service_name: str = "codebot-service",
    service_version: str | None = None,
    environment: str | None = None,
    flask_app: Any | None = None,
) -> None:
    """Initialize OpenTelemetry tracing and basic instrumentation.

    Parameters
    ----------
    service_name: str
        Logical service name for resource attributes.
    service_version: Optional[str]
        Version string reported with resource.
    environment: Optional[str]
        Environment hint (e.g., production/staging/development).
    flask_app: Optional[Flask]
        Flask app instance for explicit instrumentation; if None, Flask
        instrumentation is skipped.
    """
    global _OTEL_INITIALIZED
    if _OTEL_INITIALIZED:
        return

    # Import inside the function to keep the dependency optional
    try:
        from opentelemetry import trace, metrics  # type: ignore
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
        from opentelemetry.sdk.resources import Resource  # type: ignore
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore
            OTLPSpanExporter,
        )
        # Metrics are optional; configure provider if exporter is available
        try:
            from opentelemetry.sdk.metrics import MeterProvider  # type: ignore
            from opentelemetry.sdk.metrics.export import (  # type: ignore
                PeriodicExportingMetricReader,
            )
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (  # type: ignore
                OTLPMetricExporter,
            )
            _METRICS_AVAILABLE = True
        except Exception:
            _METRICS_AVAILABLE = False

        # Instrumentations (all optional)
        try:
            from opentelemetry.instrumentation.requests import (  # type: ignore
                RequestsInstrumentor,
            )
        except Exception:
            RequestsInstrumentor = None  # type: ignore
        try:
            from opentelemetry.instrumentation.flask import (  # type: ignore
                FlaskInstrumentor,
            )
        except Exception:
            FlaskInstrumentor = None  # type: ignore
        try:
            from opentelemetry.instrumentation.pymongo import (  # type: ignore
                PymongoInstrumentor,
            )
        except Exception:
            PymongoInstrumentor = None  # type: ignore

        # ----- Resource -----
        resource_attrs = {
            "service.name": service_name,
        }
        if service_version:
            resource_attrs["service.version"] = service_version
        env_val = (environment or os.getenv("ENVIRONMENT") or os.getenv("ENV") or "production").strip()
        resource_attrs["deployment.environment"] = env_val
        resource_attrs["deployment.type"] = os.getenv("DEPLOYMENT_TYPE", "render")
        resource = Resource.create(resource_attrs)

        # ----- Tracing -----
        # אין להשתמש ב-localhost כברירת מחדל בעננים (Render וכד')
        # אם לא הוגדר OTEL_EXPORTER_OTLP_ENDPOINT – דלג בשקט על אתחול OTel
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or ""
        if endpoint.strip():
            insecure = _str2bool(os.getenv("OTEL_EXPORTER_INSECURE", "false"))
            span_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=insecure)
            tracer_provider = TracerProvider(resource=resource)
            tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
            trace.set_tracer_provider(tracer_provider)

        # ----- Metrics (best-effort) -----
        if _METRICS_AVAILABLE:
            try:
                metric_exporter = OTLPMetricExporter(endpoint=endpoint, insecure=insecure)
                metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60000)
                meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
                metrics.set_meter_provider(meter_provider)
            except Exception:
                # Metrics are optional – ignore exporter/transport errors
                pass

        # ----- Auto-instrumentation -----
        try:
            if RequestsInstrumentor is not None:
                RequestsInstrumentor().instrument()
        except Exception:
            pass

        try:
            if FlaskInstrumentor is not None and flask_app is not None:
                # Prefer explicit instrumentation of the passed app instance
                FlaskInstrumentor().instrument_app(flask_app)
        except Exception:
            pass

        try:
            if PymongoInstrumentor is not None:
                PymongoInstrumentor().instrument()
        except Exception:
            pass

        _OTEL_INITIALIZED = True
    except Exception:
        # Entire telemetry stack is optional – fail-open
        return


__all__ = ["setup_telemetry"]

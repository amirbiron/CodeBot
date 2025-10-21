"""
Manual instrumentation helpers built on OpenTelemetry (safe no-op fallback).

- traced decorator for sync/async functions that creates a span and records
  duration and errors via OpenTelemetry metrics when available.
- All imports are done lazily to avoid hard dependency in environments where
  OpenTelemetry is not installed (e.g., docs/CI minimal).
"""
from __future__ import annotations

from typing import Any, Callable, Optional, TypeVar, Union, cast
import time
import functools

_T = TypeVar("_T")


def _get_tracer_and_meter():
    """Best-effort retrieval of tracer and meter; returns (tracer, meter) or (None, None)."""
    try:
        from opentelemetry import trace, metrics  # type: ignore
        tracer = trace.get_tracer(__name__)
        meter = metrics.get_meter(__name__)
        return tracer, meter
    except Exception:
        return None, None


def traced(span_name: Optional[str] = None, attributes: Optional[dict[str, Any]] = None):
    """Decorator to add OpenTelemetry tracing around a function.

    - Works for both sync and async functions.
    - If OpenTelemetry is not available, acts as a no-op decorator.
    """

    def decorator(func: Callable[..., _T]) -> Callable[..., _T]:
        tracer, meter = _get_tracer_and_meter()
        # Prepare optional metrics (best-effort)
        duration_hist = None
        error_counter = None
        active_updown = None
        if meter is not None:
            try:
                duration_hist = meter.create_histogram(
                    "request.duration",
                    description="Function duration in seconds",
                    unit="s",
                )
            except Exception:
                duration_hist = None
            try:
                error_counter = meter.create_counter(
                    "errors.total",
                    description="Total number of errors",
                    unit="1",
                )
            except Exception:
                error_counter = None
            try:
                active_updown = meter.create_up_down_counter(
                    "requests.active",
                    description="Number of active in-flight function calls",
                    unit="1",
                )
            except Exception:
                active_updown = None

        is_async = hasattr(func, "__code__") and getattr(func, "__code__").co_flags & 0x80

        def _start_span(name: str):
            if tracer is None:
                return None
            try:
                return tracer.start_as_current_span(name)
            except Exception:
                return None

        if not is_async:
            @functools.wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any):
                name = span_name or f"{func.__module__}.{func.__name__}"
                cm = _start_span(name)
                # context manager enter
                token = None
                if cm is not None:
                    try:
                        token = cm.__enter__()
                        if attributes and token is not None:
                            try:
                                token.set_attributes(attributes)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                    except Exception:
                        token = None
                try:
                    if active_updown is not None:
                        try:
                            active_updown.add(1)
                        except Exception:
                            pass
                    start = time.perf_counter()
                    return func(*args, **kwargs)
                except Exception as e:
                    if duration_hist is not None:
                        try:
                            duration_hist.record(max(0.0, time.perf_counter() - start), {"function": func.__name__, "error": True})  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    if error_counter is not None:
                        try:
                            error_counter.add(1, {"function": func.__name__, "error_type": type(e).__name__})  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    # record exception in span if available
                    try:
                        if token is not None:
                            token.record_exception(e)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    raise
                finally:
                    if active_updown is not None:
                        try:
                            active_updown.add(-1)
                        except Exception:
                            pass
                    if duration_hist is not None:
                        try:
                            duration_hist.record(max(0.0, time.perf_counter() - start), {"function": func.__name__})  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    if cm is not None:
                        try:
                            cm.__exit__(None, None, None)
                        except Exception:
                            pass

            return cast(Callable[..., _T], sync_wrapper)

        else:
            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any):
                name = span_name or f"{func.__module__}.{func.__name__}"
                cm = _start_span(name)
                token = None
                if cm is not None:
                    try:
                        token = cm.__enter__()
                        if attributes and token is not None:
                            try:
                                token.set_attributes(attributes)  # type: ignore[attr-defined]
                            except Exception:
                                pass
                    except Exception:
                        token = None
                try:
                    if active_updown is not None:
                        try:
                            active_updown.add(1)
                        except Exception:
                            pass
                    start = time.perf_counter()
                    return await cast(Callable[..., Any], func)(*args, **kwargs)
                except Exception as e:
                    if duration_hist is not None:
                        try:
                            duration_hist.record(max(0.0, time.perf_counter() - start), {"function": func.__name__, "error": True})  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    if error_counter is not None:
                        try:
                            error_counter.add(1, {"function": func.__name__, "error_type": type(e).__name__})  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    try:
                        if token is not None:
                            token.record_exception(e)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    raise
                finally:
                    if active_updown is not None:
                        try:
                            active_updown.add(-1)
                        except Exception:
                            pass
                    if duration_hist is not None:
                        try:
                            duration_hist.record(max(0.0, time.perf_counter() - start), {"function": func.__name__})  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    if cm is not None:
                        try:
                            cm.__exit__(None, None, None)
                        except Exception:
                            pass

            return cast(Callable[..., _T], async_wrapper)

    return decorator


__all__ = ["traced"]

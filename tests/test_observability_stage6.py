import types

import pytest

import metrics
import main
from database import repository
from telegram.ext import ApplicationHandlerStop, CommandHandler


def _clear_collector(collector):
    if collector is None:
        return
    try:
        collector._metrics.clear()  # type: ignore[attr-defined]
    except AttributeError:
        try:  # Counters expose _value when no labels were accessed yet
            collector._value.set(0)  # type: ignore[attr-defined]
        except Exception:
            pass


@pytest.fixture(autouse=True)
def reset_metrics_state():
    collectors = [
        metrics.codebot_handler_requests_total,
        metrics.codebot_handler_latency_seconds,
        metrics.codebot_command_requests_total,
        metrics.codebot_command_latency_seconds,
        metrics.codebot_db_requests_total,
        metrics.codebot_db_latency_seconds,
    ]
    for collector in collectors:
        _clear_collector(collector)
    metrics._ERR_TIMESTAMPS.clear()
    metrics._EWMA_RT = None
    yield
    for collector in collectors:
        _clear_collector(collector)
    metrics._ERR_TIMESTAMPS.clear()
    metrics._EWMA_RT = None


def _counter_value(counter, *label_values):
    sample = counter.labels(*label_values)  # type: ignore[arg-type]
    return float(sample._value.get())  # type: ignore[attr-defined]


def test_record_request_outcome_updates_handler_and_command_metrics():
    metrics.record_request_outcome(
        204,
        0.25,
        source="webapp",
        handler="search_handler",
        command="lookup_command",
        cache_hit=True,
    )

    handler_labels = ("webapp:search_handler", "2xx", "hit")
    command_labels = ("webapp:lookup_command", "2xx", "hit")

    assert handler_labels in metrics.codebot_handler_requests_total._metrics  # type: ignore[attr-defined]
    assert command_labels in metrics.codebot_command_requests_total._metrics  # type: ignore[attr-defined]


def test_record_request_outcome_respects_custom_status_and_cache_strings():
    metrics.record_request_outcome(
        512,
        1.0,
        handler="slow_path",
        cache_hit="warm",
        status_label="custom",
    )

    handler_labels = ("slow_path", "custom", "warm")
    assert handler_labels in metrics.codebot_handler_requests_total._metrics  # type: ignore[attr-defined]


def test_record_db_operation_tracks_statuses():
    metrics.record_db_operation("db.write", 0.2, status="ok")
    metrics.record_db_operation("db.write", 0.3, status="fail")

    ok_value = _counter_value(metrics.codebot_db_requests_total, "db.write", "ok")
    fail_value = _counter_value(metrics.codebot_db_requests_total, "db.write", "fail")

    assert ok_value == pytest.approx(1.0)
    assert fail_value == pytest.approx(1.0)


def test_instrument_db_decorator_covers_fail_and_error_states():
    decorator = repository._instrument_db("db.decorated")  # type: ignore[attr-defined]

    class Dummy:
        @decorator
        def act(self, outcome):
            if outcome == "boom":
                raise RuntimeError("boom")
            return outcome

    dummy = Dummy()
    dummy.act(True)
    dummy.act(False)
    with pytest.raises(RuntimeError):
        dummy.act("boom")

    assert _counter_value(metrics.codebot_db_requests_total, "db.decorated", "ok") == pytest.approx(1.0)
    assert _counter_value(metrics.codebot_db_requests_total, "db.decorated", "fail") == pytest.approx(1.0)
    assert _counter_value(metrics.codebot_db_requests_total, "db.decorated", "error") == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_wrap_command_callback_success_records_metrics():
    async def sample(update, context):
        return "done"

    wrapped = main._wrap_command_callback(sample, "/echo")
    await wrapped(object(), object())

    key = ("telegram:/echo", "2xx", "unknown")
    assert key in metrics.codebot_command_requests_total._metrics  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_wrap_command_callback_error_records_error_status():
    async def boom(update, context):
        raise ValueError("boom")

    wrapped = main._wrap_command_callback(boom, "/boom")
    with pytest.raises(ValueError):
        await wrapped(object(), object())

    key = ("telegram:/boom", "error", "unknown")
    assert key in metrics.codebot_command_requests_total._metrics  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_wrap_handler_callback_handles_cancelled_updates():
    async def cancel(update, context):
        raise ApplicationHandlerStop()

    wrapped = main._wrap_handler_callback(cancel, "github:text_input")
    with pytest.raises(ApplicationHandlerStop):
        await wrapped(object(), object())

    key = ("telegram:github:text_input", "cancelled", "unknown")
    assert key in metrics.codebot_handler_requests_total._metrics  # type: ignore[attr-defined]


def test_wrap_handler_callback_sync_branch():
    def handler(update, context):
        return 123

    wrapped = main._wrap_handler_callback(handler, "manual")
    assert wrapped(object(), object()) == 123

    key = ("telegram:manual", "2xx", "unknown")
    assert key in metrics.codebot_handler_requests_total._metrics  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_instrument_command_handlers_wraps_existing_handlers():
    async def say_hi(update, context):
        return "hi"

    handler = CommandHandler("hi", say_hi)
    application = types.SimpleNamespace(handlers=[handler])

    main._instrument_command_handlers(application)

    assert handler.callback is not say_hi
    await handler.callback(object(), object())

    key = ("telegram:/hi", "2xx", "unknown")
    assert key in metrics.codebot_command_requests_total._metrics  # type: ignore[attr-defined]

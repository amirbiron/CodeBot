import sys
import types
from importlib import util
from pathlib import Path

import pytest

_ROOT_CONFTEST_PATH = Path(__file__).resolve().parents[1] / "conftest.py"
_SPEC = util.spec_from_file_location("root_conftest_http_fixture", _ROOT_CONFTEST_PATH)
_ROOT_CONFTEST = util.module_from_spec(_SPEC)  # type: ignore[arg-type]
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_ROOT_CONFTEST)  # type: ignore[union-attr]
_fixture_def = _ROOT_CONFTEST._reset_http_async_session_between_tests


def _get_fixture_impl():
    impl = getattr(_fixture_def, "__wrapped__", None)
    return impl if impl is not None else _fixture_def


@pytest.mark.asyncio
async def test_http_async_fixture_closes_session_pre_and_post(monkeypatch):
    call_log: list[str] = []

    async def _close_session():
        call_log.append("close")

    fake_http_async = types.ModuleType("http_async")
    fake_http_async.close_session = _close_session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "http_async", fake_http_async)

    impl = _get_fixture_impl()
    agen = impl()

    await agen.asend(None)
    assert call_log == ["close"]

    with pytest.raises(StopAsyncIteration):
        await agen.asend(None)

    assert call_log == ["close", "close"]


@pytest.mark.asyncio
async def test_http_async_fixture_handles_missing_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "http_async", raising=False)

    impl = _get_fixture_impl()
    agen = impl()

    await agen.asend(None)

    with pytest.raises(StopAsyncIteration):
        await agen.asend(None)

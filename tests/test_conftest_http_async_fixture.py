import asyncio
import sys
import types
from contextlib import suppress
from importlib import util
from pathlib import Path
from typing import Optional

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


class _FakeRequest:
    def __init__(self, *, async_marker: bool):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._async_marker = async_marker
        self.node = types.SimpleNamespace(
            get_closest_marker=lambda name: object() if (async_marker and name == "asyncio") else None
        )

    def getfixturevalue(self, name: str):
        if name != "event_loop":
            raise KeyError(name)
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def close(self) -> None:
        if self._loop is not None:
            with suppress(Exception):
                asyncio.set_event_loop(None)
            self._loop.close()
            self._loop = None


@pytest.mark.asyncio
async def test_http_async_fixture_closes_session_pre_and_post(monkeypatch):
    call_log: list[str] = []

    async def _close_session():
        call_log.append("close")

    fake_http_async = types.ModuleType("http_async")
    fake_http_async.close_session = _close_session  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "http_async", fake_http_async)

    impl = _get_fixture_impl()
    request = _FakeRequest(async_marker=True)
    try:
        gen = impl(request=request)
        assert gen is not None

        next(gen)
        assert call_log == ["close"]

        with pytest.raises(StopIteration):
            next(gen)

        assert call_log == ["close", "close"]
    finally:
        request.close()


@pytest.mark.asyncio
async def test_http_async_fixture_handles_missing_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "http_async", raising=False)

    impl = _get_fixture_impl()
    request = _FakeRequest(async_marker=True)
    try:
        gen = impl(request=request)

        next(gen)

        with pytest.raises(StopIteration):
            next(gen)
    finally:
        request.close()

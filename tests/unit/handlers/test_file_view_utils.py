import asyncio
import types
import pytest

import handlers.file_view as fv


class ServiceSync:
    def hello(self, name):
        return f"hi {name}"


class ServiceAsync:
    async def hello(self, name):
        await asyncio.sleep(0)
        return f"hi {name}"


@pytest.mark.asyncio
async def test_call_service_method_sync_and_async():
    out1 = await fv._call_service_method(ServiceSync(), "hello", "a")
    assert out1 == "hi a"
    out2 = await fv._call_service_method(ServiceAsync(), "hello", "b")
    assert out2 == "hi b"
    out3 = await fv._call_service_method(ServiceSync(), "missing")
    assert out3 is None


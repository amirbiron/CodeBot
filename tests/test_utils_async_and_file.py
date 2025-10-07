import asyncio
import os
import sys
import types


def _stub_telegram_if_missing():
    try:
        import telegram  # type: ignore
        import telegram.error  # type: ignore
        import telegram.constants  # type: ignore
        import telegram.ext  # type: ignore
    except Exception:
        telegram = types.ModuleType('telegram')
        sys.modules['telegram'] = telegram
        err = types.ModuleType('telegram.error')
        class _BR(Exception):
            pass
        err.BadRequest = _BR
        sys.modules['telegram.error'] = err
        consts = types.ModuleType('telegram.constants')
        consts.ChatAction = None
        consts.ParseMode = None
        sys.modules['telegram.constants'] = consts
        ext = types.ModuleType('telegram.ext')
        class _CT:
            DEFAULT_TYPE = object
        ext.ContextTypes = _CT
        sys.modules['telegram.ext'] = ext


_stub_telegram_if_missing()


def test_fileutils_create_temp_file(tmp_path, monkeypatch):
    from utils import FileUtils

    # ensure temp dir is writable in env
    monkeypatch.setenv('TMPDIR', str(tmp_path))

    path = asyncio.get_event_loop().run_until_complete(
        FileUtils.create_temp_file("hello", suffix=".txt")
    )
    assert os.path.exists(path)
    with open(path, 'rb') as f:
        assert f.read() == b"hello"


def test_asyncutils_batch_process_basic():
    from utils import AsyncUtils

    async def _worker(x):
        await asyncio.sleep(0.001)
        return x * 2

    async def _run():
        res = await AsyncUtils.batch_process([1, 2, 3, 4], _worker, batch_size=2, delay=0)
        return res

    out = asyncio.get_event_loop().run_until_complete(_run())
    assert out == [2, 4, 6, 8]


def test_performanceutils_measure_time(capfd):
    from utils import PerformanceUtils

    with PerformanceUtils.measure_time("op"):
        sum(range(1000))
    # no strict assert; just ensure code path executes without exceptions


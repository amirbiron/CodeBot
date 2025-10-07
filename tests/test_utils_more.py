import asyncio
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


def test_split_long_message_edges():
    from utils import TelegramUtils

    short = "a" * 100
    assert TelegramUtils.split_long_message(short, max_length=4096) == [short]

    # exactly boundary
    boundary = "x" * 4096
    assert TelegramUtils.split_long_message(boundary, max_length=4096) == [boundary]

    # long content made of short lines to allow safe splitting by lines
    long = "\n".join(["line" for _ in range(10000)])
    parts = TelegramUtils.split_long_message(long, max_length=4096)
    assert isinstance(parts, list) and len(parts) >= 2
    assert all(len(p) <= 4096 for p in parts)


def test_is_safe_code_python_and_bash():
    from utils import ValidationUtils

    safe, warns = ValidationUtils.is_safe_code("print('hi')", 'python')
    assert safe is True and warns == []

    unsafe_py, warns_py = ValidationUtils.is_safe_code("eval('1+1')", 'python')
    assert unsafe_py is False and any('eval' in w.lower() for w in warns_py)

    unsafe_bash, warns_bash = ValidationUtils.is_safe_code("rm -rf /", 'bash')
    assert unsafe_bash is False and any('rm' in w.lower() for w in warns_bash)


def test_performance_utils_timing_decorator_async_and_sync(capfd):
    from utils import PerformanceUtils

    @PerformanceUtils.timing_decorator
    async def a(x):
        await asyncio.sleep(0.001)
        return x + 1

    @PerformanceUtils.timing_decorator
    def b(y):
        return y * 2

    # run
    out1 = asyncio.get_event_loop().run_until_complete(a(1))
    out2 = b(3)
    assert out1 == 2 and out2 == 6
    # some log lines should be emitted
    # (we don't assert text, only that no exceptions occurred)


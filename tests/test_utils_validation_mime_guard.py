import time


def test_is_valid_filename_various():
    from utils import ValidationUtils

    # Valid cases
    assert ValidationUtils.is_valid_filename("file.txt") is True
    assert ValidationUtils.is_valid_filename("my_report-2025.csv") is True

    # Invalid chars
    for bad in ['f<.txt', 'a>.txt', 'q:".txt', 'path/seg.txt', 'pipe|.log', 'q?.md', 'star*.md', 'b\\c.txt']:
        assert ValidationUtils.is_valid_filename(bad) is False

    # Reserved names
    assert ValidationUtils.is_valid_filename("CON.txt") is False
    assert ValidationUtils.is_valid_filename("LPT1.log") is False

    # Length
    long_name = "a" * 300 + ".txt"
    assert ValidationUtils.is_valid_filename(long_name) is False


def test_file_utils_mime_and_ext():
    from utils import FileUtils

    assert FileUtils.get_file_extension("a.TXT") == ".txt"
    assert FileUtils.get_file_extension("archive.tar.gz").endswith(".gz")

    assert FileUtils.get_mime_type("a.txt") == "text/plain"
    assert FileUtils.get_mime_type("image.png") == "image/png"
    assert FileUtils.get_mime_type("noext") == "application/octet-stream"


def test_callback_query_guard_should_block_window(monkeypatch):
    from utils import CallbackQueryGuard

    class _Q:
        def __init__(self, mid, data):
            self.message = type("M", (), {"message_id": mid})()
            self.data = data

    class _U:
        def __init__(self, uid, cid, mid, data):
            self.effective_user = type("E", (), {"id": uid})()
            self.effective_chat = type("C", (), {"id": cid})()
            self.callback_query = _Q(mid, data)

    class _Ctx:
        def __init__(self):
            self.user_data = {}

    u = _U(1, 10, 100, "cb:1")
    ctx = _Ctx()
    # First call - should not block
    assert CallbackQueryGuard.should_block(u, ctx, window_seconds=0.5) is False
    # Immediate second (same fp) - should block
    assert CallbackQueryGuard.should_block(u, ctx, window_seconds=0.5) is True
    # After window - should not block
    time.sleep(0.6)
    assert CallbackQueryGuard.should_block(u, ctx, window_seconds=0.5) is False


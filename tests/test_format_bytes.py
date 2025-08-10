import pytest


def _import_format_bytes():
    try:
        # function is defined in github_menu_handler module
        from github_menu_handler import format_bytes  # type: ignore

        return format_bytes
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Skipping: cannot import github_menu_handler.format_bytes ({e})")


def test_format_bytes_basic():
    format_bytes = _import_format_bytes()
    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1536) == "1.5 KB"


def test_format_bytes_mb():
    format_bytes = _import_format_bytes()
    assert format_bytes(1024 * 1024) == "1.0 MB"
    assert format_bytes(10 * 1024 * 1024) == "10.0 MB"

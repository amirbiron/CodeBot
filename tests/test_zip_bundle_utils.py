"""טסטים לכלי בניית ה-ZIP המרוכז ב-utils (הגנת Zip-Slip + מגבלות איסוף).

חשוב אבטחתית: safe_zip_entry_name מנרמל שמות רשומה לשם בסיס בטוח (בלי נתיב מוחלט/
מקונן/"..") ו-build_zip_bytes אוכף מגבלת מספר קבצים וגודל מצטבר. נבדק ע"י פענוח ה-ZIP.
"""

import zipfile
from io import BytesIO

from utils import (
    safe_zip_entry_name,
    build_zip_bytes,
    ZIP_CREATE_MAX_FILES,
    ZIP_CREATE_MAX_TOTAL_BYTES,
)


def _names(zip_bytes):
    with zipfile.ZipFile(BytesIO(zip_bytes)) as z:
        return z.namelist()


def test_safe_zip_entry_name_strips_paths():
    # basename בלבד — שום רכיב נתיב לא שורד
    assert safe_zip_entry_name("../../etc/passwd") == "passwd"
    assert safe_zip_entry_name("/abs/path/x.py") == "x.py"
    assert safe_zip_entry_name("a\\b\\c.txt") == "c.txt"
    assert safe_zip_entry_name("plain.md") == "plain.md"
    # שמות מסוכנים "טהורים" נופלים ל-fallback
    assert safe_zip_entry_name("..", fallback="f") == "f"
    assert safe_zip_entry_name(".", fallback="f") == "f"
    assert safe_zip_entry_name("", fallback="f") == "f"
    assert safe_zip_entry_name(None, fallback="f") == "f"


def test_build_zip_sanitizes_entry_names():
    items = [
        {"filename": "../../etc/passwd", "bytes": b"x"},
        {"filename": "/abs/evil.sh", "bytes": b"y"},
        {"filename": "ok.txt", "bytes": b"z"},
    ]
    names = _names(build_zip_bytes(items))
    # אף רשומה ללא מפריד נתיב או ".."
    assert all("/" not in n and "\\" not in n and ".." not in n for n in names)
    assert not any(n.startswith("/") for n in names)
    assert set(names) == {"passwd", "evil.sh", "ok.txt"}


def test_build_zip_enforces_max_files():
    items = [{"filename": f"f{i}.txt", "bytes": b"x"} for i in range(10)]
    names = _names(build_zip_bytes(items, max_files=3))
    assert len(names) == 3


def test_build_zip_enforces_max_total_bytes():
    items = [
        {"filename": "a.bin", "bytes": b"0" * 600},
        {"filename": "b.bin", "bytes": b"1" * 600},   # 600+600=1200 > 1000 ⇒ נעצר לפני
        {"filename": "c.bin", "bytes": b"2" * 600},
    ]
    names = _names(build_zip_bytes(items, max_total_bytes=1000))
    assert names == ["a.bin"]


def test_build_zip_skips_missing_names_with_fallback():
    items = [
        {"filename": None, "bytes": b"content"},   # שם חסר ⇒ fallback file_1
        {"bytes": b"nofield"},                       # ללא מפתח filename ⇒ fallback file_2
    ]
    names = _names(build_zip_bytes(items))
    assert len(names) == 2
    assert all(n for n in names)  # אין שם ריק


def test_defaults_are_sane():
    assert ZIP_CREATE_MAX_FILES == 50
    assert ZIP_CREATE_MAX_TOTAL_BYTES == 45 * 1024 * 1024

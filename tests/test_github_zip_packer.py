"""מודול האריזה שרץ בתהליך נפרד — ``services/github_zip_packer.py``.

שני סוגי בדיקות כאן. ``pack_folder`` נבדק באותו תהליך, כדי לראות דברים שאי אפשר
לראות מבחוץ (איזה קובץ נפרס). ``main`` נבדק כמו שהבוט מריץ אותו: סקריפט עם
``python -I``, JSON ב-stdin ו-JSON ב-stdout — כך נבדק גם שהסקריפט באמת לא נשען על
שום דבר מהריפו.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from _github_zip_harness import zipball_bytes
from services import github_zip_packer as packer

SCRIPT = Path(packer.__file__)
CAPS = {"max_files": 500, "max_file_bytes": 5 * 1024 * 1024, "max_total_bytes": 50 * 1024 * 1024}


def _archive(tmp_path, files, **kwargs):
    path = tmp_path / "archive.zip"
    path.write_bytes(zipball_bytes(files, **kwargs))
    return str(path)


def test_file_cap_checked_before_reading_content(tmp_path, monkeypatch):
    """אחרי שהגענו לתקרת הקבצים לא פורסים עוד תוכן מהארכיון.

    התקרה קיימת כדי להגביל עבודה וזיכרון; פריסה של קובץ שנזרק מיד אחריה
    מבזבזת את שניהם.
    """
    archive = _archive(tmp_path, {"f/a.txt": b"a", "f/b.txt": b"b", "f/c.txt": b"c"})
    read_names = []
    original = zipfile.ZipFile

    class _TrackingZipFile(original):
        def read(self, name, pwd=None):
            read_names.append(getattr(name, "filename", name))
            return super().read(name, pwd)

    monkeypatch.setattr(packer.zipfile, "ZipFile", _TrackingZipFile)
    stats = packer.pack_folder(archive, "f", str(tmp_path / "out.zip"), **{**CAPS, "max_files": 1})

    assert stats["total_files"] == 1 and stats["skipped_limits"] == 2
    assert len(read_names) == 1, f"נפרסו קבצים אחרי התקרה: {read_names}"


def test_folder_prefix_is_a_path_boundary(tmp_path):
    """``skills/logo`` לא תופס את ``skills/logo-old`` — הקידומת נגמרת ב-``/``."""
    archive = _archive(tmp_path, {"skills/logo/a.txt": b"a", "skills/logo-old/b.txt": b"b"})
    out = tmp_path / "out.zip"
    packer.pack_folder(archive, "skills/logo", str(out), **CAPS)
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["logo/a.txt"]


def test_symlinks_are_counted_not_packed(tmp_path):
    archive = _archive(tmp_path, {"d/a.txt": b"a"}, symlinks={"d/link": "../a.txt"})
    out = tmp_path / "out.zip"
    stats = packer.pack_folder(archive, "d", str(out), **CAPS)
    assert stats["skipped_symlinks"] == 1 and stats["total_files"] == 1
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["d/a.txt"]


def test_archive_without_a_single_root_is_refused(tmp_path):
    path = tmp_path / "archive.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("a/x.txt", b"x")
        z.writestr("b/x.txt", b"y")
    with pytest.raises(packer.UnexpectedArchive):
        packer.pack_folder(str(path), "x", str(tmp_path / "out.zip"), **CAPS)


def _run_script(request: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", "-I", str(SCRIPT)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_script_packs_and_reports_counts_as_json(tmp_path):
    """הסקריפט רץ כמו שהבוט מריץ אותו, ושם תיקייה בעברית עובר בשלום."""
    archive = _archive(tmp_path, {"סקילים/לוגו/SKILL.md": b"hello", "README.md": b"r"})
    out = tmp_path / "out.zip"
    proc = _run_script({"archive_path": archive, "folder": "סקילים/לוגו", "dest_path": str(out), **CAPS})

    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["ok"] is True and result["stats"]["total_files"] == 1, result
    with zipfile.ZipFile(out) as zf:
        assert zf.read("לוגו/SKILL.md") == b"hello"


def test_script_reports_an_unexpected_archive_as_structured_output(tmp_path):
    path = tmp_path / "archive.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("a/x.txt", b"x")
        z.writestr("b/x.txt", b"y")
    proc = _run_script({"archive_path": str(path), "folder": "x", "dest_path": str(tmp_path / "o.zip"), **CAPS})

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["error"] == "unexpected_archive"


def test_script_crash_exits_non_zero(tmp_path):
    """כשל שאינו ארכיון לא צפוי (כאן: הארכיון לא קיים) יוצא עם קוד שאינו אפס ו-traceback."""
    proc = _run_script({"archive_path": str(tmp_path / "missing.zip"), "folder": "x", "dest_path": str(tmp_path / "o.zip"), **CAPS})
    assert proc.returncode != 0
    assert "Traceback" in proc.stderr

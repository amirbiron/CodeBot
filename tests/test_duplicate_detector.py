from pathlib import Path

from duplicate_detector import scan_duplicates


def test_scan_duplicates_exact_match(tmp_path: Path):
    d = tmp_path
    a = d / "a.py"
    b = d / "sub" / "b.py"
    b.parent.mkdir(parents=True, exist_ok=True)

    content = "x = 1\n\nprint(x)\n"
    a.write_text(content)
    b.write_text(content + "\n")  # trailing newline difference -> normalized

    res = scan_duplicates(str(d), includes=["**/*.py"], min_lines=1, max_files=10)
    # Expect both files grouped under same hash
    assert any(set(v) == {"a.py", str(Path("sub") / "b.py")} for v in res.values())


def test_scan_duplicates_respects_min_lines(tmp_path: Path):
    d = tmp_path
    (d / "a.py").write_text("print(1)\n")
    (d / "b.py").write_text("print(1)\n")

    # With min_lines=2 no duplicates should appear
    res = scan_duplicates(str(d), includes=["*.py"], min_lines=2, max_files=10)
    assert res == {}

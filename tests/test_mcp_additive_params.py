"""ארבעת הפרמטרים החדשים בכלי ה-MCP, והאילוץ שמעליהם: תוספתיות.

לכל פיצ'ר יש כאן שני סוגי בדיקות:

1. **התנהגות** — הפרמטר החדש עושה את מה שהוא מבטיח.
2. **תוספתיות** — קריאה **בלי** הפרמטר מחזירה בדיוק את מה שהוחזר קודם.
   זו הבדיקה ששומרת על הצרכנים הקיימים, והיא זו שתיפול אם מישהו יחליף
   טיפוס של שדה קיים במקום להוסיף אחד חדש.

שתי קבוצות של בדיקות כאן רצות מול **git אמיתי** (``tmp_path`` + ``git init``)
ולא מול דמה: הפרסור של ``git grep`` ושל ``git ls-tree`` הוא בדיוק המקום שבו
דמה מקרטון הייתה מאשרת קוד שבור, כי הפורמט האמיתי הוא מה שנשבר. שני
המסלולים האלה היו ללא כיסוי כלשהו לפני ה-PR הזה.
"""

import shutil
import subprocess

import pytest

from mcp_server import handlers, repo_handlers

pytest.importorskip("mcp")


# ---------------------------------------------------------------------------
# עזרי git אמיתי
# ---------------------------------------------------------------------------

_GIT = shutil.which("git")
requires_git = pytest.mark.skipif(_GIT is None, reason="git is not installed")


def _run(*args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True)


def _build_mirror(tmp_path, files: dict[str, str]):
    """בונה ריפו אמיתי ומשכפל אותו ל-mirror, ומחזיר ``GitMirrorService``.

    כל הכתיבה מתחת ל-``tmp_path`` בלבד, לפי כלל ה-IO של הריפו.
    """
    from services.git_mirror_service import GitMirrorService

    work = tmp_path / "work"
    work.mkdir()
    for name, body in files.items():
        (work / name).write_text(body, encoding="utf-8")
    _run(_GIT, "init", "-q", "-b", "main", ".", cwd=work)
    _run(_GIT, "add", "-A", cwd=work)
    _run(
        _GIT, "-c", "user.email=t@t", "-c", "user.name=t",
        "commit", "-qm", "init", cwd=work,
    )
    _run(_GIT, "clone", "-q", "--mirror", str(work), str(tmp_path / "repo.git"), cwd=tmp_path)
    return GitMirrorService(base_path=str(tmp_path))


_SAMPLE = "\n".join(
    ["line01", "line02", "NEEDLE first", "line04", "line05", "line06",
     "NEEDLE second", "line08", "line09", "line10"]
) + "\n"


# ===========================================================================
# 2. context_lines ב-search_repo
# ===========================================================================


@requires_git
def test_search_without_context_lines_returns_exactly_the_old_shape(tmp_path):
    """תוספתיות: בלי הפרמטר, לשורה יש בדיוק שלושת המפתחות שהיו."""
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    res = svc.search_with_git_grep(
        "repo", "NEEDLE", max_results=50, timeout=10,
        case_sensitive=True, ref="refs/heads/main",
    )

    assert [r["line"] for r in res["results"]] == [3, 7]
    for row in res["results"]:
        assert sorted(row) == ["content", "line", "path"]
        assert row["path"] == "sample.py"


@requires_git
def test_search_with_context_lines_returns_the_window(tmp_path):
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    res = svc.search_with_git_grep(
        "repo", "NEEDLE", max_results=50, timeout=10,
        case_sensitive=True, ref="refs/heads/main", context_lines=2,
    )

    first, second = res["results"]
    assert first["context_before"] == ["line01", "line02"]
    assert first["context_after"] == ["line04", "line05"]
    assert second["context_before"] == ["line05", "line06"]
    assert second["context_after"] == ["line08", "line09"]


@requires_git
def test_context_lines_does_not_mistake_a_context_line_for_a_filename(tmp_path):
    """הבדיקה המרכזית של פיצ'ר 2.

    ``git grep -C`` פולט שורות הקשר כ-``<מספר>-<תוכן>``, והפרסר הקודם זיהה
    שורת תוצאה רק לפי ``<מספר>:``. כל השאר נחשב אצלו **שם קובץ**. הורצה על
    הקוד שלפני התיקון והחזירה ``path='2-line02'`` — כלומר שורת הקשר נכנסה
    במקום שם הקובץ.
    """
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    res = svc.search_with_git_grep(
        "repo", "NEEDLE", max_results=50, timeout=10,
        case_sensitive=True, ref="refs/heads/main", context_lines=3,
    )

    assert {r["path"] for r in res["results"]} == {"sample.py"}


@requires_git
def test_context_lines_at_the_first_and_last_line_of_a_file(tmp_path):
    svc = _build_mirror(tmp_path, {
        "top.py": "NEEDLE at the top\nsecond\nthird\n",
        "bottom.py": "a\nb\nNEEDLE at the bottom\n",
    })

    top = svc.search_with_git_grep(
        "repo", "NEEDLE", max_results=50, timeout=10, file_pattern="top.py",
        case_sensitive=True, ref="refs/heads/main", context_lines=3,
    )["results"][0]
    bottom = svc.search_with_git_grep(
        "repo", "NEEDLE", max_results=50, timeout=10, file_pattern="bottom.py",
        case_sensitive=True, ref="refs/heads/main", context_lines=3,
    )["results"][0]

    assert top["context_before"] == []
    assert top["context_after"] == ["second", "third"]
    assert bottom["context_before"] == ["a", "b"]
    assert bottom["context_after"] == []


@requires_git
def test_overlapping_windows_each_keep_their_own_full_context(tmp_path):
    """שתי פגיעות שהסביבות שלהן חופפות.

    git מאחד אותן לבלוק אחד (נמדד), ולכן אין מיזוג ידני — אבל כל פגיעה
    עדיין חייבת לקבל את החלון המלא שלה, כולל השורות המשותפות.
    """
    svc = _build_mirror(tmp_path, {"sample.py": _SAMPLE})

    first, second = svc.search_with_git_grep(
        "repo", "NEEDLE", max_results=50, timeout=10,
        case_sensitive=True, ref="refs/heads/main", context_lines=3,
    )["results"]

    shared = ["line04", "line05", "line06"]
    assert first["context_after"] == shared
    assert second["context_before"] == shared


def test_search_repo_clamps_context_lines():
    class _Backend:
        def __init__(self):
            self.seen = None

        def search(self, **kwargs):
            self.seen = kwargs
            return {"ok": True}

    for asked, expected in [(0, 0), (3, 3), (999, repo_handlers.CONTEXT_LINES_MAX), (-5, 0)]:
        be = _Backend()
        repo_handlers.search_repo(be, repo="r", query="abc", context_lines=asked)
        assert be.seen["context_lines"] == expected


# ===========================================================================
# 3. include_stats ב-list_repo_tree
# ===========================================================================


@requires_git
def test_list_all_files_with_sizes_matches_list_all_files(tmp_path):
    """``-l`` מוסיף גודל אמיתי בלי לשנות את הנתיבים או את הסדר."""
    svc = _build_mirror(tmp_path, {"a.py": "x = 1\n", "b.py": "y = 22\n"})

    plain = svc.list_all_files("repo", "refs/heads/main")
    with_sizes = svc.list_all_files_with_sizes("repo", "refs/heads/main")

    assert [e["path"] for e in with_sizes] == plain
    assert {e["path"]: e["size"] for e in with_sizes} == {"a.py": 6, "b.py": 7}


@requires_git
def test_list_all_files_with_sizes_returns_none_on_a_bad_ref(tmp_path):
    """אותו חוזה כשל כמו ``list_all_files``, שעליו ``list_tree`` נשען."""
    svc = _build_mirror(tmp_path, {"a.py": "x\n"})
    assert svc.list_all_files_with_sizes("repo", "refs/heads/nope") is None


def _tree_backend(files, sizes=None, indexed=None):
    from mcp_server.repo_backend import RepoBackend

    class _Mirror:
        def list_all_files(self, repo, ref):
            return list(files)

        def list_all_files_with_sizes(self, repo, ref):
            return [{"path": f, "size": (sizes or {}).get(f, 1)} for f in files]

    class _Coll:
        def find(self, query, projection=None):
            wanted = set(query.get("path", {}).get("$in", []))
            return [d for d in (indexed or []) if d["path"] in wanted]

    class _DB:
        def __getitem__(self, name):
            return _Coll()

    backend = RepoBackend(db=_DB())
    backend._mirror = _Mirror()
    return backend


def test_list_tree_without_include_stats_has_no_entries_key():
    """תוספתיות: המפתח החדש לא קיים בכלל בקריאה רגילה."""
    res = _tree_backend(["a.py", "b.py"]).list_tree(repo="r")

    assert res["paths"] == ["a.py", "b.py"]
    assert "entries" not in res


def test_list_tree_with_include_stats_adds_entries_without_touching_paths():
    plain = _tree_backend(["a.py", "b.py"]).list_tree(repo="r")
    rich = _tree_backend(
        ["a.py", "b.py"],
        sizes={"a.py": 10, "b.py": 20},
        indexed=[{"path": "a.py", "lines": 3, "commit_sha": "abc123"}],
    ).list_tree(repo="r", include_stats=True)

    # ``paths`` זהה לחלוטין בשתי הקריאות.
    assert rich["paths"] == plain["paths"]
    assert rich["entries"] == [
        {"path": "a.py", "size": 10, "lines": 3, "lines_commit_sha": "abc123"},
        # ``b.py`` לא נמצא באינדקס — ``lines`` הוא ``None``, לא ניחוש.
        {"path": "b.py", "size": 20, "lines": None, "lines_commit_sha": None},
    ]


def test_entries_stay_aligned_with_paths_even_when_the_budget_truncates():
    """שתי הרשימות נגזרות מאותה נקודת חיתוך — נאכף, לא מובטח בהערה."""
    files = [f"file{i:03d}.py" for i in range(50)]
    res = _tree_backend(files, sizes={f: 100 for f in files}).list_tree(
        repo="r", include_stats=True, byte_budget=400
    )

    assert res["truncated"] is True
    assert 0 < len(res["paths"]) < len(files)
    assert len(res["entries"]) == len(res["paths"])
    assert [e["path"] for e in res["entries"]] == res["paths"]


# ===========================================================================
# 4. lines ב-get_file וב-get_repo_file
# ===========================================================================


@pytest.mark.parametrize(
    "value",
    [
        [5], [1, 2, 3], "1-2", None if False else 5,   # לא רשימה בת שניים
        [0, 5], [1, 0], [-3, 5],                        # אפס או שלילי
        [9, 4],                                         # start > end
        [True, 5], [1, False],                          # bool אינו מספר שורה
    ],
)
def test_normalize_line_range_rejects_bad_input(value):
    assert handlers.normalize_line_range(value) == handlers.LINE_RANGE_INVALID


def test_normalize_line_range_accepts_a_valid_pair():
    assert handlers.normalize_line_range([3, 9]) == (3, 9)


def test_apply_line_range_clips_an_end_past_the_file_and_says_so():
    out = handlers.apply_line_range("a\nb\nc\n", 2, 99)

    assert out["text"] == "b\nc"
    assert out["range"] == {"start": 2, "end": 3, "total_lines": 3, "truncated": True}


def test_apply_line_range_errors_when_start_is_past_the_file():
    """קיצוץ כאן היה מחזיר קטע ריק שנראה כמו תשובה תקינה."""
    assert handlers.apply_line_range("a\nb\n", 9, 12) == handlers.LINE_RANGE_OUT_OF_BOUNDS


def test_apply_line_range_reports_total_lines_so_the_reader_knows_what_it_missed():
    out = handlers.apply_line_range("\n".join(str(i) for i in range(1, 101)), 10, 12)

    assert out["text"] == "10\n11\n12"
    assert out["range"]["total_lines"] == 100
    assert out["range"]["truncated"] is False


def _saved_backend(doc):
    from mcp_server.backend import ProductionBackend

    class _Dbm:
        def get_latest_version_fresh(self, user_id, file_name):
            return dict(doc)

    backend = ProductionBackend.__new__(ProductionBackend)
    backend._require_dbm = lambda: _Dbm()
    return backend


def test_get_file_without_lines_returns_the_whole_file():
    """תוספתיות: אין ``range``, והתוכן שלם."""
    out = _saved_backend({"file_name": "a.py", "code": "1\n2\n3\n"}).get_file(1, file_name="a.py")

    assert out["code"] == "1\n2\n3\n"
    assert "range" not in out


def test_get_file_with_lines_returns_only_the_range_and_the_total():
    out = _saved_backend({"file_name": "a.py", "code": "1\n2\n3\n4\n5\n"}).get_file(
        1, file_name="a.py", lines=[2, 4]
    )

    assert out["code"] == "2\n3\n4"
    assert out["range"] == {"start": 2, "end": 4, "total_lines": 5, "truncated": False}


def test_get_file_range_keeps_code_and_content_identical_on_a_large_file():
    """``LargeFile`` מגיע עם ``content``, ו-``_full`` ממלא ממנו את ``code``.

    אחרי חיתוך הם חייבים להישאר שווים — אחרת אותו קובץ מוחזר בשתי גרסאות
    באותה תשובה.
    """
    out = _saved_backend({"file_name": "big.py", "content": "a\nb\nc\nd\n"}).get_file(
        1, file_name="big.py", lines=[2, 3]
    )

    assert out["code"] == "b\nc"
    assert out["content"] == out["code"]


def test_get_file_bad_range_returns_an_error_envelope_not_a_file():
    out = _saved_backend({"file_name": "a.py", "code": "1\n2\n"}).get_file(
        1, file_name="a.py", lines=[9, 4]
    )

    assert out == {"ok": False, "error": handlers.LINE_RANGE_INVALID}


def _repo_backend_for_content(text):
    from mcp_server.repo_backend import RepoBackend

    class _Mirror:
        def get_file_at_commit(self, repo, path, commit, **k):
            return {
                "success": True, "file_path": path, "resolved_commit": "c0ffee",
                "is_binary": False, "content": text, "encoding": "utf-8",
                "size": len(text), "lines": text.count("\n"),
            }

    backend = RepoBackend(db=None)
    backend._mirror = _Mirror()
    return backend


def test_get_repo_file_without_lines_returns_the_whole_file():
    res = _repo_backend_for_content("1\n2\n3\n").get_file(repo="r", path="a.py")

    assert res["content"] == "1\n2\n3\n"
    assert "range" not in res


def test_get_repo_file_and_get_file_agree_on_the_range_block():
    """הדרישה המרכזית של פיצ'ר 4: אותה סמנטיקה בשני הכלים.

    אותו קובץ, אותו טווח — אותו ``range`` בדיוק, ואותו טקסט.
    """
    text = "1\n2\n3\n4\n5\n"

    repo_res = _repo_backend_for_content(text).get_file(repo="r", path="a.py", lines=[2, 4])
    saved_res = _saved_backend({"file_name": "a.py", "code": text}).get_file(
        1, file_name="a.py", lines=[2, 4]
    )

    assert repo_res["range"] == saved_res["range"]
    assert repo_res["content"] == saved_res["code"]


def test_get_repo_file_bad_range_is_reported_the_same_way():
    res = _repo_backend_for_content("1\n2\n").get_file(repo="r", path="a.py", lines=[99, 120])

    assert res == {"ok": False, "error": handlers.LINE_RANGE_OUT_OF_BOUNDS}


def test_get_repo_file_denylist_still_runs_before_anything_else():
    """הטווח אינו דלת עוקפת: מדיניות הסודות נשארת הבדיקה הראשונה."""
    res = _repo_backend_for_content("secret\n").get_file(repo="r", path=".env", lines=[1, 1])

    assert res == {"ok": False, "error": "path_denied"}

"""מפת סימבולים ב-``codekeeper_get_repo_file``.

הרקע: ``webapp/app.py`` הוא 20,035 שורות. בלי מפה, סוכן שמחפש בו פונקציה
קורא טווח ומנחש. עם מפה הוא מקבל שורת התחלה וסיום ועובר ל-``lines=``.
"""

from __future__ import annotations

import ast
import io
import pathlib
import subprocess
import tokenize
from collections import Counter

import pytest

from mcp_server import repo_handlers
from mcp_server.outline import extract_outline

# ---------------------------------------------------------------------------
# כלל מרחב השמות
#
# מרחב שמות בפייתון הוא פונקציה או מחלקה. ``if``/``try``/``with`` אינם.
# הכלל הזה החליף שלושה מקרים פרטיים — מתודות, פונקציות מקוננות, ומחלקות
# fallback בתוך ``except ImportError`` — והוא מה שהופך את המפה לשלמה.
# ---------------------------------------------------------------------------


def _names(text, **kw):
    return [row["name"] for row in extract_outline(text, "x.py", **kw)["symbols"]]


def test_a_nested_function_is_prefixed_by_the_function_that_holds_it():
    """``build_mcp`` ב-``mcp_server/server.py`` מכילה 24 כלים מקוננים.

    בלי ירידה לעומק, אאוטליין של הקובץ הזה החזיר 9 סימבולים במקום 38,
    ו-``build_mcp`` נראתה כבלוק אטום של 513 שורות. סוכן שביקש מפה כדי
    למצוא כלי לערוך — קיבל מפה שהכלי לא נמצא בה.
    """
    assert _names("def outer():\n    def inner():\n        pass\n") == [
        "outer",
        "outer.inner",
    ]


def test_a_method_is_the_same_rule_at_depth_two():
    assert _names("class C:\n    def m(self):\n        pass\n") == ["C", "C.m"]


def test_a_control_block_is_not_a_namespace_and_adds_no_prefix():
    """זה הפער השני, ונמצא רק אחרי שהראשון תוקן.

    רקורסיה שיורדת רק לתוך גופי פונקציות ומחלקות עדיין החמיצה 62
    סימבולים ב-``webapp/app.py``, כי ``_Missing``, ``_NoCache`` ו-
    ``_NativeThread`` מוגדרות בתוך ``except ImportError`` — דפוס
    ה-fallback הרגיל. ``try`` אינו מרחב שמות, ולכן אין תחילית.
    """
    text = (
        "try:\n"
        "    from x import Thing\n"
        "except ImportError:\n"
        "    class Thing:\n"
        "        def method(self):\n"
        "            pass\n"
    )

    assert _names(text) == ["Thing", "Thing.method"]


@pytest.mark.parametrize(
    "block", ["if True:", "with open('f') as f:", "for i in []:", "while True:"]
)
def test_no_control_block_introduces_a_namespace(block):
    assert _names(f"{block}\n    def f():\n        pass\n") == ["f"]


def test_an_async_function_is_a_symbol_like_any_other():
    assert _names("async def f():\n    async def g():\n        pass\n") == [
        "f",
        "f.g",
    ]


# ---------------------------------------------------------------------------
# המונה הבלתי תלוי
#
# ``ast.walk`` הוא אותה ספרייה שהמימוש משתמש בה, ולכן השוואה מולו קרובה
# מדי להשוואת פונקציה לעצמה. ``tokenize`` הוא **לקסר**: הוא לא בונה עץ,
# הוא סופר אסימונים בזרם התווים. זה מונה שנגזר ממקור אחר לגמרי.
# ---------------------------------------------------------------------------


def _count_definitions_by_tokenize(text: str) -> int:
    return sum(
        1
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.NAME and token.string in ("def", "class")
    )


_REAL_FILES = [
    "mcp_server/server.py",
    "mcp_server/repo_backend.py",
    "database/manager.py",
    "webapp/app.py",
    "main.py",
]


@pytest.mark.parametrize("relative", _REAL_FILES)
def test_the_outline_finds_every_definition_in_a_real_file(relative):
    """הבדיקה שהייתה תופסת את שני הפערים מלכתחילה.

    היא רצה על קבצי הריפו עצמם ולא על דוגמאות, כי שני הפערים התגלו
    דווקא במבנים שקיימים כאן ולא במבנים שחשבתי עליהם.
    """
    path = pathlib.Path(relative)
    if not path.exists():  # pragma: no cover - הריפו תמיד מכיל אותם
        pytest.skip(f"{relative} לא קיים")
    text = path.read_text(encoding="utf-8")

    found = extract_outline(text, relative)

    assert found["total"] == _count_definitions_by_tokenize(text), relative


def test_the_independent_counter_can_actually_fail():
    """מונה שלא מסוגל להפיל מימוש שגוי אינו ראיה.

    הגרסה שירדה רק לתוך גופי פונקציות מוצגת כאן במפורש, ו-``tokenize``
    סופר יותר ממה שהיא מוצאת.
    """
    text = (
        "try:\n"
        "    class Stub:\n"
        "        def m(self):\n"
        "            pass\n"
        "except ImportError:\n"
        "    Stub = None\n"
    )

    shallow = [n for n in ast.parse(text).body if isinstance(n, ast.ClassDef)]

    assert shallow == []  # ``class`` יושבת בתוך ``try``, לא ב-``body``
    assert _count_definitions_by_tokenize(text) == 2
    assert extract_outline(text, "x.py")["total"] == 2


# ---------------------------------------------------------------------------
# מעטרים
# ---------------------------------------------------------------------------


def test_the_range_starts_at_the_decorator_and_not_at_the_def():
    """ב-``webapp/app.py`` 203 מתוך 408 הפונקציות ברמה העליונה מעוטרות.

    ``node.lineno`` מצביע על ה-``def``, ולכן טווח שנקרא לפי האאוטליין היה
    מתחיל שורה אחרי ``@app.route(...)`` — כלומר מחמיץ בדיוק את מה שמזהה
    את הנתיב.
    """
    text = "@app.route('/x')\n@wraps(f)\ndef view():\n    pass\n"

    symbols = extract_outline(text, "x.py")["symbols"]

    assert symbols[0]["start"] == 1
    assert symbols[0]["end"] == 4


# ---------------------------------------------------------------------------
# שמות אינם ייחודיים
# ---------------------------------------------------------------------------


def test_two_symbols_may_share_a_full_name_and_both_survive():
    """נגזרת ישירה של כלל מרחב השמות: ``if``/``else`` אינם מרחב.

    זה לא תרחיש מומצא — ב-``webapp/app.py`` וב-``main.py`` יש היום שישה
    מקרים כאלה, למשל ``login_required.decorated_function`` בשורות 3448
    ו-3465. כל שלב שיחזיק את הסימבולים ב-dict לפי שם ימחק אחד מהם בשקט.
    """
    text = (
        "import sys\n"
        "if sys.version_info >= (3, 11):\n"
        "    def parse():\n"
        "        pass\n"
        "else:\n"
        "    def parse():\n"
        "        pass\n"
    )

    symbols = extract_outline(text, "x.py")["symbols"]

    assert [row["name"] for row in symbols] == ["parse", "parse"]
    assert [row["start"] for row in symbols] == [3, 6]


def test_real_duplicate_names_in_the_repo_are_not_collapsed():
    path = pathlib.Path("webapp/app.py")
    if not path.exists():  # pragma: no cover
        pytest.skip("webapp/app.py לא קיים")

    symbols = extract_outline(path.read_text(encoding="utf-8"), "webapp/app.py")["symbols"]
    repeated = {name for name, n in Counter(r["name"] for r in symbols).items() if n > 1}

    assert "login_required.decorated_function" in repeated


# ---------------------------------------------------------------------------
# הסדר, ומה שהעימוד נשען עליו
# ---------------------------------------------------------------------------


def test_symbols_are_ordered_by_start_line():
    text = "def b():\n    pass\n\n\ndef a():\n    pass\n"

    starts = [row["start"] for row in extract_outline(text, "x.py")["symbols"]]

    assert starts == sorted(starts)


def test_the_order_is_stable_across_calls():
    """עימוד בלי סדר יציב הוא באג ממתין: סימבול יכול לדלג בין עמודים."""
    path = pathlib.Path("webapp/app.py")
    if not path.exists():  # pragma: no cover
        pytest.skip("webapp/app.py לא קיים")
    text = path.read_text(encoding="utf-8")

    first = extract_outline(text, "webapp/app.py")["symbols"]
    second = extract_outline(text, "webapp/app.py")["symbols"]

    assert first == second


# ---------------------------------------------------------------------------
# ``symbol=`` — החוזה
# ---------------------------------------------------------------------------


def test_the_filter_matches_the_full_name_so_a_namespace_returns_its_children():
    """``symbol="C"`` מחזיר גם את המחלקה וגם את מה שבתוכה.

    זו התנהגות מכוונת — "תן לי הכול תחת המרחב הזה" — ולכן היא מקובעת
    ולא נשארת תופעת לוואי של התאמת תת-מחרוזת.
    """
    text = "class Outer:\n    def inner(self):\n        pass\n\n\ndef other():\n    pass\n"

    assert _names(text, symbol="Outer") == ["Outer", "Outer.inner"]


def test_the_filter_is_case_insensitive():
    assert _names("def ApiHandler():\n    pass\n", symbol="apihandler") == ["ApiHandler"]


def test_total_counts_matches_and_not_the_whole_file():
    """העימוד נשען על ``total``. אם הוא סופר את הקובץ ולא את ההתאמות,
    הקורא יבקש עמוד שני שלא קיים."""
    text = "def alpha():\n    pass\n\n\ndef beta():\n    pass\n\n\ndef gamma():\n    pass\n"

    assert extract_outline(text, "x.py")["total"] == 3
    assert extract_outline(text, "x.py", symbol="alpha")["total"] == 1


# ---------------------------------------------------------------------------
# ערוץ הכשל
# ---------------------------------------------------------------------------


def test_a_non_python_file_says_so_instead_of_returning_nothing():
    assert extract_outline("Title\n=====\n", "docs/page.rst") == {
        "status": "no_outline",
        "reason": "unsupported_language",
    }


@pytest.mark.parametrize(
    "text",
    [
        "def f(:\n    pass\n",       # תחביר שבור
        "print 'hello'\n",           # פייתון 2
        "def f():\n    x = '\ud800'\n",  # surrogate — UnicodeEncodeError, לא SyntaxError
    ],
)
def test_unparsable_input_is_reported_and_never_raised(text):
    """``except SyntaxError`` לבדו היה מפיל את הכלי על השלישי.

    סוג החריגה תלוי-גרסה: בייט אפס הוא ``SyntaxError`` ב-3.11
    ו-``ValueError`` במקומות אחרים. מניית סוגים היא הגישה השברירית, ולכן
    ההרחבה גורפת — אבל **רק** סביב הפרסינג.
    """
    result = extract_outline(text, "x.py")

    assert result["status"] == "no_outline"
    assert result["reason"] == "parse_error"
    assert result["error_type"]


def test_the_reason_names_the_exception_class():
    """``except`` רחב בלי שם המחלקה הורג את היכולת לאבחן."""
    result = extract_outline("def f():\n    x = '\ud800'\n", "x.py")

    assert result["error_type"] == "UnicodeEncodeError"


def test_a_bug_in_the_traversal_is_not_swallowed_as_no_outline(monkeypatch):
    """ההרחבה עוטפת את הפרסינג בלבד, ובכוונה.

    אילו היא עטפה את כל הפונקציה, ``AttributeError`` על צומת לא צפוי היה
    חוזר כ-``no_outline`` וקובץ תקין היה נראה כאילו אין לו סימבולים —
    בדיוק הכישלון השקט של K11, שכבה אחת פנימה.
    """
    import mcp_server.outline as module

    def _explode(_tree):
        raise AttributeError("boom")

    monkeypatch.setattr(module, "_collect", _explode)

    with pytest.raises(AttributeError):
        module.extract_outline("def f():\n    pass\n", "x.py")


def test_deep_nesting_does_not_raise_from_our_side():
    """מחסנית מפורשת ולא רקורסיה: קינון עמוק אינו ``RecursionError`` שלנו."""
    text = "".join(f"{' ' * (4 * i)}def f{i}():\n" for i in range(60))
    text += " " * (4 * 60) + "pass\n"

    result = extract_outline(text, "x.py")

    assert result["status"] == "ok"
    assert result["total"] == 60


# ---------------------------------------------------------------------------
# הצרכן הוא לקוח MCP
#
# ``claude-md-snippets/testing.md`` כלל 1: הבדיקה עוברת דרך אותו ממשק כמו
# הצרכן. הטסטים למעלה בודקים את החילוץ; אלה בודקים את הכלי.
# ---------------------------------------------------------------------------


class _Mirror:
    def __init__(self, text):
        self._text = text

    def get_file_at_commit(self, repo, path, commit, **k):
        return {
            "success": True,
            "file_path": path,
            "resolved_commit": "abc123",
            "is_binary": False,
            "content": self._text,
            "encoding": "utf-8",
            "size": len(self._text),
            "lines": self._text.count("\n") + 1,
        }

    def get_default_branch(self, repo):
        return "main"


def _backend(text):
    from mcp_server.repo_backend import RepoBackend

    return RepoBackend(mirror=_Mirror(text))


_SAMPLE = "".join(f"def f{i}():\n    pass\n\n\n" for i in range(250))


def test_the_tool_returns_an_outline_status_and_a_page():
    out = repo_handlers.get_repo_file(
        _backend(_SAMPLE), repo="r", path="a.py", outline=True
    )

    assert out["status"] == "outline"
    assert out["total"] == 250
    assert len(out["symbols"]) == repo_handlers.OUTLINE_PER_PAGE_DEFAULT


def test_paging_walks_forward_without_gaps_or_repeats():
    backend = _backend(_SAMPLE)

    first = repo_handlers.get_repo_file(
        backend, repo="r", path="a.py", outline=True, page=1, per_page=100
    )["symbols"]
    second = repo_handlers.get_repo_file(
        backend, repo="r", path="a.py", outline=True, page=2, per_page=100
    )["symbols"]

    assert first[-1]["start"] < second[0]["start"]
    assert not ({r["name"] for r in first} & {r["name"] for r in second})


def test_per_page_is_clamped_to_the_outline_ceiling_and_not_the_tree_one():
    """``TREE_PER_PAGE_MAX`` הוא 1000, ורשומת סימבול שוקלת יותר מנתיב."""
    out = repo_handlers.get_repo_file(
        _backend(_SAMPLE), repo="r", path="a.py", outline=True, per_page=99_999
    )

    assert out["per_page"] == repo_handlers.OUTLINE_PER_PAGE_MAX


def test_reading_without_outline_is_untouched():
    """תוספתיות: בלי הפרמטר התשובה היא בדיוק זו של היום."""
    out = repo_handlers.get_repo_file(_backend("def f():\n    pass\n"), repo="r", path="a.py")

    assert out["status"] == "ok"
    assert out["content"] == "def f():\n    pass\n"
    assert "symbols" not in out
    assert "total" not in out


def test_the_outline_and_a_range_read_agree_on_where_a_symbol_lives():
    """המסלול השלם: מפה ← טווח. אם הם לא מסכימים, המפה חסרת ערך."""
    text = "def a():\n    pass\n\n\n@deco\ndef b():\n    return 1\n"
    backend = _backend(text)

    found = repo_handlers.get_repo_file(
        backend, repo="r", path="a.py", outline=True, symbol="b"
    )["symbols"][0]
    body = repo_handlers.get_repo_file(
        backend, repo="r", path="a.py", lines=[found["start"], found["end"]]
    )["content"]

    assert body == "@deco\ndef b():\n    return 1"


def test_an_unsupported_language_reaches_the_caller_as_a_status():
    out = repo_handlers.get_repo_file(
        _backend("Title\n=====\n"), repo="r", path="page.rst", outline=True
    )

    assert out == {
        "ok": True,
        "file": out["file"],
        "status": "no_outline",
        "reason": "unsupported_language",
    }


# ---------------------------------------------------------------------------
# מול git אמיתי
# ---------------------------------------------------------------------------


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_a_decorated_tool_is_findable_through_a_real_mirror(tmp_path):
    """הטסט שהיה תופס את הפער מלכתחילה, בצורתו הכללית.

    כל הכתיבה תחת ``tmp_path``; אין מחיקה ואין נגיעה בעץ העבודה.
    """
    work = tmp_path / "work"
    work.mkdir()
    (work / "srv.py").write_text(
        "def register(mcp):\n"
        "    @mcp.tool(name='x')\n"
        "    def get_repo_file(path):\n"
        "        return path\n",
        encoding="utf-8",
    )
    _git("init", "-q", "-b", "main", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=work)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init", cwd=work)

    mirrors = tmp_path / "mirrors"
    mirrors.mkdir()
    subprocess.run(
        ["git", "clone", "--quiet", "--mirror", str(work), str(mirrors / "demo.git")],
        check=True,
        capture_output=True,
    )

    from mcp_server.repo_backend import RepoBackend
    from services.git_mirror_service import GitMirrorService

    backend = RepoBackend(mirror=GitMirrorService(base_path=str(mirrors)))
    out = backend.get_file(repo="demo", path="srv.py", outline=True)

    names = {row["name"] for row in out["symbols"]}
    assert "register.get_repo_file" in names
    found = next(r for r in out["symbols"] if r["name"] == "register.get_repo_file")
    assert found["start"] == 2  # שורת ה-``@mcp.tool``, לא ה-``def``

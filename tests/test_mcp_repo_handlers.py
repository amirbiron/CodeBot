"""Unit tests for the repo-browser handlers (clamps + validation, pure)."""

from mcp_server import repo_handlers as rh


class _RecordingRepoBackend:
    def __init__(self):
        self.calls = []

    def list_repos(self, *, limit):
        self.calls.append(("repos", limit))
        return {"ok": True}

    # הפרמטרים החדשים נוספים **בסוף** החתימה ובסוף ה-tuple: הטסטים הקיימים
    # משווים לפי אינדקס מיקומי, אז הוספה בסוף בטוחה והוספה באמצע שוברת.
    def list_tree(self, *, repo, path, ref, page, per_page, byte_budget, include_stats=False):
        self.calls.append(
            ("tree", repo, path, ref, page, per_page, byte_budget, include_stats)
        )
        return {"ok": True}

    # כמו ב-``list_tree`` למעלה: הפרמטרים החדשים נוספים **בסוף** החתימה
    # ובסוף ה-tuple, כי הטסטים הקיימים משווים לפי אינדקס מיקומי.
    def get_file(
        self, *, repo, path, ref, lines=None,
        outline=False, symbol=None, page=1, per_page=100,
    ):
        self.calls.append(
            ("get", repo, path, ref, lines, outline, symbol, page, per_page)
        )
        return {"ok": True}

    def search(
        self, *, repo, query, file_pattern, max_results, byte_budget,
        context_lines=0, regex=False, case_sensitive=False, include_vendored=False,
    ):
        self.calls.append(
            ("search", repo, query, file_pattern, max_results, byte_budget,
             context_lines, regex)
        )
        # שני הדגלים החדשים נשמרים בנפרד ולא בסוף הטאפל, כדי שאינדקסים
        # שטסטים קיימים משווים אליהם לא יזוזו בכל תוספת.
        self.case_sensitive = case_sensitive
        self.include_vendored = include_vendored
        return {"ok": True}


def test_list_repos_clamps_limit():
    be = _RecordingRepoBackend()
    rh.list_repos(be, limit=10_000)
    assert be.calls[0] == ("repos", rh.REPOS_LIMIT_MAX)
    rh.list_repos(be, limit="junk")
    assert be.calls[1] == ("repos", rh.REPOS_LIMIT_DEFAULT)  # invalid -> default


def test_tree_requires_repo_and_clamps():
    be = _RecordingRepoBackend()
    assert rh.list_repo_tree(be, repo="  ") == {"ok": False, "error": "missing_repo"}
    assert be.calls == []
    rh.list_repo_tree(be, repo="r", page=0, per_page=99_999)
    call = be.calls[0]
    assert call[0] == "tree" and call[4] == 1  # page floored
    assert call[5] == rh.TREE_PER_PAGE_MAX  # per_page capped
    assert call[6] == rh.OUTPUT_BYTE_BUDGET  # budget always passed


def test_tree_defaults():
    be = _RecordingRepoBackend()
    rh.list_repo_tree(be, repo="r")
    assert be.calls[0][5] == rh.TREE_PER_PAGE_DEFAULT


def test_get_file_requires_repo_and_path():
    be = _RecordingRepoBackend()
    assert rh.get_repo_file(be, repo="", path="a.py") == {"ok": False, "error": "missing_repo"}
    assert rh.get_repo_file(be, repo="r", path=" ") == {"ok": False, "error": "missing_path"}
    assert be.calls == []
    rh.get_repo_file(be, repo="r", path=" a.py ", ref="  ")
    # trimmed; blank ref -> None. ברירות המחדל של האאוטליין בסוף ה-tuple,
    # והן חייבות להיות "כבוי" — קריאה רגילה לא מבקשת מפה.
    assert be.calls[0] == (
        "get", "r", "a.py", None, None, False, None, 1, rh.OUTLINE_PER_PAGE_DEFAULT
    )


def test_search_validates_query_and_clamps():
    be = _RecordingRepoBackend()
    assert rh.search_repo(be, repo="r", query="x") == {"ok": False, "error": "query_too_short"}
    assert be.calls == []
    rh.search_repo(be, repo="r", query="xy", max_results=5_000)
    call = be.calls[0]
    assert call[4] == rh.SEARCH_RESULTS_MAX  # capped
    assert call[5] == rh.OUTPUT_BYTE_BUDGET


def test_search_passes_the_query_through_without_trimming_it():
    """השאילתה עוברת כמו שהיא; ה-``strip`` מכריע ריקנות בלבד.

    **מוטציה שמפילה:** להחזיר את ``q = (query or "").strip()``.
    """
    be = _RecordingRepoBackend()

    rh.search_repo(be, repo="r", query="    return")

    assert be.calls[0][2] == "    return"


def test_search_rejects_only_what_is_empty_or_shorter_than_two_characters():
    """רווחים בלבד נדחים, אבל ``" a"`` הוא שתי תווים תקפים.

    האורך נמדד על המחרוזת המקורית ולא על המקוצצת, אחרת חיפוש של רווח
    ואות היה נדחה כ"קצר מדי" בזמן שהוא באורך הנדרש.

    **מוטציה שמפילה:** להחליף את התנאי ל-``len(q.strip()) < 2``.
    """
    be = _RecordingRepoBackend()

    assert rh.search_repo(be, repo="r", query="   ") == {
        "ok": False, "error": "query_too_short"
    }
    assert be.calls == []

    rh.search_repo(be, repo="r", query=" a")
    assert be.calls[0][2] == " a"


def test_search_defaults_to_literal_and_forwards_the_regex_flag():
    """המצב מגיע מהקורא, ובהיעדרו הוא מילולי.

    **מוטציה שמפילה:** להשמיט את ``regex=bool(regex)`` מהקריאה ל-backend.
    """
    be = _RecordingRepoBackend()

    rh.search_repo(be, repo="r", query="xy")
    rh.search_repo(be, repo="r", query="xy", regex=True)

    assert be.calls[0][7] is False
    assert be.calls[1][7] is True


def test_search_forwards_the_two_boolean_flags_instead_of_dropping_them():
    """שני דגלים שהשכבה הזו יכולה לבלוע בשקט.

    ‏``case_sensitive`` נבלע כאן בפועל עד ספטמבר 2026: הוא פשוט לא הועבר
    הלאה, ולכן ``git grep`` רץ תמיד עם ``-i`` ולא הייתה דרך לבקש התאמה
    מדויקת. פרמטר שמתקבל ונזרק הוא אותה שתיקה שהשרת הזה דוחה בכל מקום
    אחר, ולכן ההעברה עצמה נבדקת ולא רק התוצאה.

    **מוטציה שמפילה:** להסיר אחת משתי ההעברות מהקריאה ל-backend.
    """
    be = _RecordingRepoBackend()

    rh.search_repo(be, repo="r", query="xy")
    assert be.case_sensitive is False and be.include_vendored is False

    rh.search_repo(be, repo="r", query="xy", case_sensitive=True)
    assert be.case_sensitive is True

    rh.search_repo(be, repo="r", query="xy", include_vendored=True)
    assert be.include_vendored is True
    # ‏``include_vendored`` אינו גורר את השני איתו.
    assert be.case_sensitive is False

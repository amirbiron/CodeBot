"""Unit tests for the repo-browser handlers (clamps + validation, pure)."""

from mcp_server import repo_handlers as rh


class _RecordingRepoBackend:
    def __init__(self):
        self.calls = []

    def list_repos(self, *, limit):
        self.calls.append(("repos", limit))
        return {"ok": True}

    def list_tree(self, *, repo, path, ref, page, per_page, byte_budget):
        self.calls.append(("tree", repo, path, ref, page, per_page, byte_budget))
        return {"ok": True}

    def get_file(self, *, repo, path, ref):
        self.calls.append(("get", repo, path, ref))
        return {"ok": True}

    def search(self, *, repo, query, file_pattern, max_results, byte_budget):
        self.calls.append(("search", repo, query, file_pattern, max_results, byte_budget))
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
    assert be.calls[0] == ("get", "r", "a.py", None)  # trimmed; blank ref -> None


def test_search_validates_query_and_clamps():
    be = _RecordingRepoBackend()
    assert rh.search_repo(be, repo="r", query="x") == {"ok": False, "error": "query_too_short"}
    assert be.calls == []
    rh.search_repo(be, repo="r", query="xy", max_results=5_000)
    call = be.calls[0]
    assert call[4] == rh.SEARCH_RESULTS_MAX  # capped
    assert call[5] == rh.OUTPUT_BYTE_BUDGET

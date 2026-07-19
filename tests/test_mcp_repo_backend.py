"""Unit tests for RepoBackend (fake mirror/search/db — repo convention)."""

from mcp_server.repo_backend import SYNC_RETRY_AFTER_SECONDS, RepoBackend


class _Cursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction):
        self._docs.sort(key=lambda d: d.get(key), reverse=direction < 0)
        return self

    def limit(self, n):
        self._docs = self._docs[: int(n)]
        return self

    def __iter__(self):
        return iter(self._docs)


class _Coll:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.indexes = []

    def create_index(self, *a, **k):
        self.indexes.append((a, k))
        return "i"

    def find(self, q, projection=None):
        out = []
        for d in self.docs:
            if projection:
                keep = {k for k, v in projection.items() if v}
                out.append({k: v for k, v in d.items() if k in keep})
            else:
                out.append(dict(d))
        return _Cursor(out)

    def find_one(self, q):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None


class _DB:
    def __init__(self, repos=None, jobs=None):
        self.c = {
            "repo_metadata": _Coll(repos),
            "sync_jobs": _Coll(jobs),
        }

    def __getitem__(self, name):
        return self.c.setdefault(name, _Coll())


class _Mirror:
    def __init__(self, files=None, file_result=None):
        self.files = files
        self.file_result = file_result or {}
        self.calls = []

    def list_all_files(self, repo, ref):
        self.calls.append(("list", repo, ref))
        return self.files

    def get_file_at_commit(self, repo, path, commit, **k):
        self.calls.append(("get", repo, path, commit))
        return dict(self.file_result)


class _Search:
    def __init__(self, result=None):
        self.result = result or {"results": [], "total": 0}
        self.calls = []

    def search(self, repo, query, **kwargs):
        self.calls.append((repo, query, kwargs))
        return dict(self.result)


def _repos_db():
    return _DB(
        repos=[
            {"repo_name": "beta", "default_branch": "main", "sync_status": "ok", "_id": "x"},
            {"repo_name": "alpha", "default_branch": "master", "sync_status": "ok", "_id": "y"},
        ]
    )


def test_init_ensures_repo_metadata_index():
    db = _repos_db()
    RepoBackend(db=db, mirror=_Mirror(), search_service=_Search())
    assert db["repo_metadata"].indexes  # gap #6: created as part of this phase
    args, kwargs = db["repo_metadata"].indexes[0]
    assert args[0] == "repo_name" and kwargs.get("unique") is True


def test_list_repos_sorted_projected_limited():
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(), search_service=_Search())
    out = be.list_repos(limit=1)
    assert out["ok"] is True and out["count"] == 1
    assert out["repos"][0]["repo_name"] == "alpha"  # sorted by name
    assert "_id" not in out["repos"][0]  # projection


def test_list_tree_filters_paginates_and_omits_denied():
    files = ["README.md", "src/a.py", "src/b.py", "src/.env", "docs/x.md"]
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(files=files), search_service=_Search())
    out = be.list_tree(repo="alpha", path="src", page=1, per_page=1)
    assert out["ok"] is True
    assert out["total"] == 2  # a.py + b.py; .env omitted by policy
    assert out["paths"] == ["src/a.py"]
    assert out["ref"] == "refs/heads/master"  # default branch resolved from DB
    page2 = be.list_tree(repo="alpha", path="src", page=2, per_page=1)
    assert page2["paths"] == ["src/b.py"]


def test_list_tree_byte_budget_truncates():
    files = [f"dir/file_{i}.py" for i in range(50)]
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(files=files), search_service=_Search())
    out = be.list_tree(repo="alpha", page=1, per_page=50, byte_budget=100)
    assert out["truncated"] is True
    assert 0 < len(out["paths"]) < 50


def test_list_tree_sync_in_progress_during_local_autosync(monkeypatch):
    # A failed read while THIS service is cloning/fetching locally must also
    # report sync_in_progress (not just the webapp's job queue).
    from mcp_server import repo_autosync

    monkeypatch.setattr(repo_autosync, "is_refreshing", lambda name: name == "alpha")
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(files=None), search_service=_Search())
    out = be.list_tree(repo="alpha")
    assert out["error"] == "sync_in_progress" and out["retry_after"] == SYNC_RETRY_AFTER_SECONDS


def test_list_tree_sync_in_progress_when_read_fails_during_sync():
    db = _DB(
        repos=[{"repo_name": "alpha", "default_branch": "main"}],
        jobs=[{"repo_name": "alpha", "status": "running"}],
    )
    be = RepoBackend(db=db, mirror=_Mirror(files=None), search_service=_Search())
    out = be.list_tree(repo="alpha")
    assert out["ok"] is False and out["error"] == "sync_in_progress"
    assert out["retry_after"] == SYNC_RETRY_AFTER_SECONDS


def test_list_tree_not_found_when_no_sync_running():
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(files=None), search_service=_Search())
    out = be.list_tree(repo="alpha")
    assert out == {"ok": False, "error": "repo_or_ref_not_found"}


def test_get_file_ok_envelope():
    res = {
        "success": True,
        "is_binary": False,
        "content": "print(1)",
        "encoding": "utf-8",
        "size": 8,
        "lines": 1,
        "file_path": "src/a.py",
        "resolved_commit": "abc123",
    }
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(file_result=res), search_service=_Search())
    out = be.get_file(repo="alpha", path="src/a.py")
    assert out["ok"] is True and out["status"] == "ok"
    assert out["content"] == "print(1)"
    assert out["file"]["resolved_commit"] == "abc123" and out["file"]["lines"] == 1


def test_get_file_binary_envelope_has_no_content():
    res = {"success": True, "is_binary": True, "content": None, "size": 10, "file_path": "a.png"}
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(file_result=res), search_service=_Search())
    out = be.get_file(repo="alpha", path="a.png")
    assert out["ok"] is True and out["status"] == "binary"
    assert "content" not in out


def test_get_file_too_large_envelope():
    res = {"error": "file_too_large", "size": 900_000, "max_size": 512_000}
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(file_result=res), search_service=_Search())
    out = be.get_file(repo="alpha", path="big.txt")
    assert out["ok"] is True and out["status"] == "too_large"
    assert out["max"] == 512_000 and "content" not in out


def test_get_file_not_found_and_denied():
    res = {"error": "file_not_in_commit"}
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(file_result=res), search_service=_Search())
    assert be.get_file(repo="alpha", path="nope.py") == {"ok": False, "error": "not_found"}
    # policy blocks BEFORE touching the mirror
    mirror = _Mirror(file_result={"success": True})
    be2 = RepoBackend(db=_repos_db(), mirror=mirror, search_service=_Search())
    assert be2.get_file(repo="alpha", path=".env") == {"ok": False, "error": "path_denied"}
    assert mirror.calls == []


def test_get_file_sync_in_progress_instead_of_not_found():
    db = _DB(
        repos=[{"repo_name": "alpha", "default_branch": "main"}],
        jobs=[{"repo_name": "alpha", "status": "running"}],
    )
    res = {"error": "invalid_commit"}  # ref unresolvable mid-fetch
    be = RepoBackend(db=db, mirror=_Mirror(file_result=res), search_service=_Search())
    out = be.get_file(repo="alpha", path="a.py")
    assert out["error"] == "sync_in_progress" and out["retry_after"] > 0


def test_search_caps_filters_and_snippets():
    rows = [{"path": f"f{i}.py", "line": i, "content": "x" * 600} for i in range(10)]
    rows.append({"path": ".env", "line": 1, "content": "SECRET=1"})
    be = RepoBackend(
        db=_repos_db(),
        mirror=_Mirror(),
        search_service=_Search({"results": rows, "total": 11}),
    )
    out = be.search(repo="alpha", query="x", max_results=5)
    assert out["ok"] is True and out["count"] == 5  # capped to max_results
    assert out["total"] == 10  # policy-filtered availability (11 minus .env), NOT engine total
    assert out["truncated"] is True  # allowed matches exist beyond the cap
    assert all(len(r["snippet"]) <= 500 for r in out["results"])  # snippet cap
    assert all(r["path"] != ".env" for r in out["results"])  # policy skip


def test_search_not_truncated_when_under_cap():
    rows = [{"path": "a.py", "line": 1, "content": "x"}]
    be = RepoBackend(
        db=_repos_db(), mirror=_Mirror(), search_service=_Search({"results": rows, "total": 1})
    )
    out = be.search(repo="alpha", query="x", max_results=5)
    assert out["total"] == 1 and out["count"] == 1 and out["truncated"] is False


def test_list_tree_normalizes_bad_page_inputs():
    files = ["a.py", "b.py", "c.py"]
    be = RepoBackend(db=_repos_db(), mirror=_Mirror(files=files), search_service=_Search())
    # Non-numeric / negative inputs must not crash or slice negatively.
    out = be.list_tree(repo="alpha", page="junk", per_page=-7)
    assert out["ok"] is True
    assert out["page"] == 1 and out["per_page"] == 1  # normalized values echoed back
    assert out["paths"] == ["a.py"]
    out2 = be.list_tree(repo="alpha", page=-3, per_page="junk")
    assert out2["page"] == 1 and out2["per_page"] == 200
    assert out2["paths"] == files


def test_search_error_maps_to_transient_check():
    db = _DB(
        repos=[{"repo_name": "alpha", "default_branch": "main"}],
        jobs=[{"repo_name": "alpha", "status": "running"}],
    )
    be = RepoBackend(
        db=db, mirror=_Mirror(), search_service=_Search({"error": "boom", "results": []})
    )
    out = be.search(repo="alpha", query="xy")
    assert out["error"] == "sync_in_progress" and out["retry_after"] > 0

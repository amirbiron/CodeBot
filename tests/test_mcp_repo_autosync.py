"""Unit tests for the MCP repo autosync worker (refresh_once — pure, no threads)."""

from mcp_server import repo_autosync
from mcp_server.repo_autosync import autosync_enabled, is_refreshing, refresh_once, start_autosync


class _Coll:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, q, projection=None):
        return [dict(d) for d in self.docs]


class _DB:
    def __init__(self, repos):
        self._repos = _Coll(repos)

    def __getitem__(self, name):
        assert name == "repo_metadata"
        return self._repos


class _Mirror:
    def __init__(self, exists=True, local_sha="abc", fail_fetch=False):
        self._exists = exists
        self._local_sha = local_sha
        self._fail_fetch = fail_fetch
        self.calls = []

    def mirror_exists(self, name):
        self.calls.append(("exists", name))
        return self._exists

    def init_mirror(self, url, name):
        self.calls.append(("clone", url, name))
        return {"success": True}

    def get_current_sha(self, name, branch):
        self.calls.append(("sha", name, branch))
        return self._local_sha

    def fetch_updates(self, name):
        self.calls.append(("fetch", name))
        if self._fail_fetch:
            return {"success": False, "message": "boom"}
        return {"success": True}


def _meta(name="alpha", url="https://github.com/o/alpha", sha="abc", branch="main"):
    return {"repo_name": name, "repo_url": url, "default_branch": branch, "last_synced_sha": sha}


def test_missing_mirror_is_cloned_from_repo_url():
    mirror = _Mirror(exists=False)
    stats = refresh_once(_DB([_meta()]), mirror)
    assert stats["cloned"] == 1 and stats["errors"] == 0
    assert ("clone", "https://github.com/o/alpha", "alpha") in mirror.calls


def test_missing_mirror_without_url_is_skipped():
    mirror = _Mirror(exists=False)
    stats = refresh_once(_DB([_meta(url="")]), mirror)
    assert stats["skipped"] == 1
    assert all(c[0] != "clone" for c in mirror.calls)


def test_equal_shas_skip_fetch():
    mirror = _Mirror(exists=True, local_sha="abc")
    stats = refresh_once(_DB([_meta(sha="abc")]), mirror)
    assert stats["skipped"] == 1 and stats["fetched"] == 0
    assert all(c[0] != "fetch" for c in mirror.calls)


def test_sha_drift_triggers_fetch():
    mirror = _Mirror(exists=True, local_sha="old")
    stats = refresh_once(_DB([_meta(sha="new")]), mirror)
    assert stats["fetched"] == 1
    assert ("fetch", "alpha") in mirror.calls


def test_unknown_sha_triggers_fetch():
    # If either side's SHA is unknown we can't prove freshness — fetch.
    mirror = _Mirror(exists=True, local_sha=None)
    stats = refresh_once(_DB([_meta(sha="new")]), mirror)
    assert stats["fetched"] == 1


def test_errors_are_contained_and_flag_cleared():
    class _Boom(_Mirror):
        def mirror_exists(self, name):
            raise RuntimeError("disk gone")

    stats = refresh_once(_DB([_meta(), _meta(name="beta")]), _Boom())
    assert stats["errors"] == 2  # both failed, loop survived both
    assert is_refreshing("alpha") is False and is_refreshing("beta") is False


def test_is_refreshing_true_during_fetch():
    seen = {}

    class _Probe(_Mirror):
        def fetch_updates(self, name):
            seen["during"] = is_refreshing(name)
            return {"success": True}

    refresh_once(_DB([_meta(sha="new")]), _Probe(exists=True, local_sha="old"))
    assert seen["during"] is True
    assert is_refreshing("alpha") is False  # cleared afterwards


def test_redact_strips_url_credentials_and_tokens():
    from mcp_server.repo_autosync import _redact

    # userinfo credentials inside a git URL
    msg = "Clone failed: fatal: unable to access 'https://x-access-token:ghp_abc123@github.com/o/r'"
    out = _redact(msg)
    assert "ghp_abc123" not in out and "x-access-token" not in out
    assert "https://***@github.com/o/r" in out
    # bare GitHub token shapes, outside a URL
    assert "***" == _redact("ghp_" + "A" * 36)
    assert "github_pat" not in _redact("github_pat_" + "B" * 30)
    # safe diagnostics survive
    assert _redact("Could not resolve host: github.com") == "Could not resolve host: github.com"
    assert _redact(None) == ""


def test_clone_failure_log_is_redacted(caplog):
    import logging

    class _LeakyMirror(_Mirror):
        def init_mirror(self, url, name):
            return {
                "success": False,
                "message": "fatal: 'https://x-access-token:ghp_" + "S" * 36 + "@github.com/o/r'",
            }

    with caplog.at_level(logging.WARNING, logger="mcp_server.repo_autosync"):
        stats = refresh_once(_DB([_meta()]), _LeakyMirror(exists=False))
    assert stats["errors"] == 1
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "ghp_" not in joined and "x-access-token" not in joined
    assert "***" in joined  # redaction marker present, diagnostics preserved


def test_kill_switch_disables_start(monkeypatch):
    monkeypatch.setenv("MCP_REPO_AUTOSYNC", "0")
    assert autosync_enabled() is False
    assert start_autosync(_DB([])) is False
    monkeypatch.setenv("MCP_REPO_AUTOSYNC", "1")
    assert autosync_enabled() is True


def test_interval_env_floor(monkeypatch):
    monkeypatch.setenv("MCP_REPO_AUTOSYNC_INTERVAL", "5")
    assert repo_autosync._interval_seconds() == 30  # floored to the minimum
    monkeypatch.setenv("MCP_REPO_AUTOSYNC_INTERVAL", "junk")
    assert repo_autosync._interval_seconds() == 300

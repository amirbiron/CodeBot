"""Unit tests for the MCP repo autosync worker (refresh_once — no threads).

The refresh loop is tested against duck-typed stubs. Pruning — deleting a local
mirror whose repo has no ``repo_metadata`` record — is tested against real bare
mirrors in ``tmp_path`` and a real ``GitMirrorService``, so the deletion goes
through the real ``delete_mirror``/``_safe_rmtree`` and the assertions read the
disk itself.
"""

import logging
import os
import subprocess

import pytest

from mcp_server import repo_autosync
from mcp_server.repo_autosync import autosync_enabled, is_refreshing, refresh_once, start_autosync
from services.git_mirror_service import GitMirrorService


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

    def list_mirror_names(self):
        # This stub has no disk, so the pruning step finds nothing to compare.
        # Pruning is tested against real mirrors, further down.
        return []


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


# ---------------------------------------------------------------------------
# Pruning: a mirror on this service's disk without a repo_metadata record goes.
# ---------------------------------------------------------------------------


class _Disk:
    """A real mirror directory: bare mirrors made by ``git clone --mirror`` of a local repo."""

    def __init__(self, tmp_path):
        self.base = tmp_path / "mirrors"
        self.svc = GitMirrorService(base_path=str(self.base))
        self._src = tmp_path / "src"
        self._git("init", "-q", "-b", "main", str(self._src))
        (self._src / "app.py").write_text("print('v1')\n", encoding="utf-8")
        self._git("add", ".", cwd=self._src)
        self._git("commit", "-q", "-m", "v1", cwd=self._src)

    @staticmethod
    def _git(*args, cwd=None):
        done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
        return done.stdout.strip()

    def make(self, name):
        """Mirror ``name`` and return the SHA of its ``main``.

        A record that carries this SHA makes ``refresh_once`` skip the fetch, so
        these tests never reach the network.
        """
        target = self.base / f"{name}.git"
        self._git("clone", "-q", "--mirror", "--", str(self._src), str(target))
        return self._git("rev-parse", "refs/heads/main", cwd=target)

    def has(self, name):
        return (self.base / f"{name}.git").is_dir()


@pytest.fixture
def disk(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("GIT_CONFIG"):
            monkeypatch.delenv(key, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    for key, value in {
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
    }.items():
        monkeypatch.setenv(key, value)
    return _Disk(tmp_path)


def test_mirror_without_a_record_is_pruned_and_the_others_stay(disk, caplog):
    alpha = disk.make("alpha")
    beta = disk.make("beta")
    disk.make("codekeeper-plugin")

    with caplog.at_level(logging.INFO, logger="mcp_server.repo_autosync"):
        stats = refresh_once(_DB([_meta("alpha", sha=alpha), _meta("beta", sha=beta)]), disk.svc)

    assert not (disk.base / "codekeeper-plugin.git").exists()
    assert disk.has("alpha") and disk.has("beta")
    assert stats["pruned"] == 1 and stats["errors"] == 0 and stats["skipped"] == 2
    assert "pruned the local mirror of codekeeper-plugin" in caplog.text
    # The summary line is printed even when pruning is all the pass did.
    assert "repo autosync pass:" in caplog.text and "'pruned': 1" in caplog.text


@pytest.mark.parametrize(
    "records",
    [[], [{"repo_name": ""}, {"repo_name": None}, {"repo_url": "https://github.com/o/x"}]],
    ids=["no-records", "records-without-a-name"],
)
def test_no_repo_names_prunes_nothing_and_warns(disk, caplog, records):
    """An empty answer points at the wrong database, not at every repo being removed.

    Records without a name are the same answer: none of them protects a mirror,
    so pruning on them would delete every mirror on the disk.
    """
    disk.make("alpha")
    disk.make("beta")

    with caplog.at_level(logging.WARNING, logger="mcp_server.repo_autosync"):
        stats = refresh_once(_DB(records), disk.svc)

    assert disk.has("alpha") and disk.has("beta")
    assert stats["pruned"] == 0
    assert "not pruning 2 local mirror(s)" in caplog.text


class _BrokenDB:
    def __getitem__(self, name):
        assert name == "repo_metadata"
        return self

    def find(self, *args, **kwargs):
        raise RuntimeError("mongo is down")


def test_failed_query_prunes_nothing(disk):
    disk.make("alpha")

    stats = refresh_once(_BrokenDB(), disk.svc)

    assert disk.has("alpha")
    assert stats["pruned"] == 0


def test_repo_being_refreshed_is_not_pruned(disk):
    alpha = disk.make("alpha")
    disk.make("busy")
    repo_autosync._mark("busy", True)  # what the loop does around a clone or fetch
    try:
        stats = refresh_once(_DB([_meta("alpha", sha=alpha)]), disk.svc)
    finally:
        repo_autosync._mark("busy", False)

    assert disk.has("busy")
    assert stats["pruned"] == 0 and stats["errors"] == 0


@pytest.mark.parametrize("how", ["reports", "raises"])
def test_failed_delete_counts_as_an_error_and_the_pass_moves_on(disk, caplog, how):
    alpha = disk.make("alpha")
    disk.make("a-stuck")  # listed before b-gone, so the failure is mid-pass
    disk.make("b-gone")

    class _StuckDelete(GitMirrorService):
        def delete_mirror(self, repo_name):
            if repo_name != "a-stuck":
                return super().delete_mirror(repo_name)
            if how == "raises":
                raise OSError(16, "Device or resource busy")
            return {"success": False, "existed": True, "path": None, "message": "Failed to delete mirror directory"}

    with caplog.at_level(logging.WARNING, logger="mcp_server.repo_autosync"):
        stats = refresh_once(_DB([_meta("alpha", sha=alpha)]), _StuckDelete(base_path=str(disk.base)))

    assert disk.has("a-stuck") and not disk.has("b-gone") and disk.has("alpha")
    assert stats["errors"] == 1 and stats["pruned"] == 1
    assert "a-stuck" in caplog.text


def test_a_record_whose_refresh_fails_keeps_its_mirror(disk):
    disk.make("alpha")

    class _FetchFails(GitMirrorService):
        def fetch_updates(self, repo_name, timeout=120):
            return {"success": False, "message": "Could not resolve host: github.com"}

    # A different SHA sends the pass to fetch, and the fetch fails.
    stats = refresh_once(_DB([_meta("alpha", sha="0" * 40)]), _FetchFails(base_path=str(disk.base)))

    assert disk.has("alpha")
    assert stats["errors"] == 1 and stats["pruned"] == 0


def test_pruning_leaves_alone_what_this_service_did_not_create(disk):
    alpha = disk.make("alpha")
    (disk.base / "alias.git").symlink_to(disk.base / "alpha.git", target_is_directory=True)
    (disk.base / "not.a.repo.git").mkdir()  # a name init_mirror would refuse
    (disk.base / "lost+found").mkdir()
    (disk.base / "notes.git").write_text("a file, not a directory\n", encoding="utf-8")

    stats = refresh_once(_DB([_meta("alpha", sha=alpha)]), disk.svc)

    # Neither the link nor the mirror it points to: delete_mirror("alias") would
    # resolve the link and delete alpha.git.
    assert (disk.base / "alias.git").is_symlink() and disk.has("alpha")
    assert (disk.base / "not.a.repo.git").is_dir()
    assert (disk.base / "lost+found").is_dir() and (disk.base / "notes.git").is_file()
    assert stats["pruned"] == 0 and stats["errors"] == 0


def test_a_delete_that_leaves_the_directory_is_not_counted_as_pruned(disk, caplog):
    alpha = disk.make("alpha")
    disk.make("orphan")

    class _ReportsWithoutDeleting(GitMirrorService):
        def delete_mirror(self, repo_name):
            path = str(self._get_repo_path(repo_name))
            return {"success": True, "existed": True, "path": path, "message": "Mirror deleted"}

    with caplog.at_level(logging.WARNING, logger="mcp_server.repo_autosync"):
        stats = refresh_once(_DB([_meta("alpha", sha=alpha)]), _ReportsWithoutDeleting(base_path=str(disk.base)))

    assert disk.has("orphan")
    assert stats["pruned"] == 0 and stats["errors"] == 1
    assert "still on disk" in caplog.text


def test_an_unlistable_mirror_directory_prunes_nothing(disk, caplog):
    alpha = disk.make("alpha")
    disk.make("orphan")

    class _Unlistable(GitMirrorService):
        def list_mirror_names(self):
            raise OSError(5, "Input/output error")

    with caplog.at_level(logging.WARNING, logger="mcp_server.repo_autosync"):
        stats = refresh_once(_DB([_meta("alpha", sha=alpha)]), _Unlistable(base_path=str(disk.base)))

    assert disk.has("orphan")
    assert stats["pruned"] == 0
    assert "could not list the local mirrors" in caplog.text

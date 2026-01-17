import pytest

from services.git_mirror_service import GitMirrorService


@pytest.fixture
def service(tmp_path):
    return GitMirrorService(base_path=str(tmp_path))


def test_init_mirror(service, monkeypatch):
    class _Res:
        def __init__(self):
            self.returncode = 0
            self.stdout = ""
            self.stderr = ""

    def _fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        # Basic sanity that we run the expected command shape
        assert cmd[0:3] == ["git", "clone", "--mirror"]
        return _Res()

    monkeypatch.setattr("services.git_mirror_service.subprocess.run", _fake_run)

    result = service.init_mirror("https://github.com/octocat/Hello-World.git", "test-repo")
    assert result["success"] is True


def test_should_classify_errors(service):
    assert service._classify_git_error("Could not resolve host") == "network_error"
    assert service._classify_git_error("Authentication failed") == "auth_error"


def test_is_regex(service):
    assert service._is_regex(".*test") is True
    assert service._is_regex("simple") is False


def test_init_mirror_existing_invalid_mirror_is_cleaned_and_recloned(service, tmp_path, monkeypatch):
    # Create a "corrupt" mirror directory (exists but not a real git repo)
    repo_dir = tmp_path / "test-repo.git"
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "junk.txt").write_text("not a git repo", encoding="utf-8")

    calls = {"rev_parse": 0, "clone": 0}

    class _Res:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        if cmd[:3] == ["git", "rev-parse", "--is-bare-repository"]:
            calls["rev_parse"] += 1
            return _Res(returncode=1, stdout="", stderr="fatal: not a git repository")
        if cmd[:3] == ["git", "clone", "--mirror"]:
            calls["clone"] += 1
            return _Res(returncode=0, stdout="", stderr="")
        raise AssertionError(f"Unexpected git command: {cmd}")

    monkeypatch.setattr("services.git_mirror_service.subprocess.run", _fake_run)

    result = service.init_mirror("https://github.com/octocat/Hello-World.git", "test-repo")
    assert result["success"] is True
    assert result.get("already_existed") is False
    assert calls["rev_parse"] >= 1
    assert calls["clone"] == 1


def test_sanitize_output_masks_https_credentials(service):
    raw = "fatal: unable to access 'https://oauth2:SECRET_TOKEN@github.com/org/repo.git/': 403\n"
    sanitized = service._sanitize_output(raw)
    assert "SECRET_TOKEN" not in sanitized
    assert "https://oauth2:***@github.com/org/repo.git" in sanitized


def test_get_file_content_strips_ref_and_path(service, monkeypatch):
    class _Res:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    seen = {"cmd": None}

    def _fake_run(cmd, cwd=None, capture_output=None, text=None, timeout=None):
        seen["cmd"] = cmd
        return _Res(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("services.git_mirror_service.subprocess.run", _fake_run)

    out = service.get_file_content("test-repo", " src/file.py ", ref=" origin/main ")
    assert out == "ok"
    assert seen["cmd"] == ["git", "show", "origin/main:src/file.py"]


def test_parse_grep_output_strips_sha_prefix(service):
    output = "abc123def456:src/app.py\n10:hello\n"
    results = service._parse_grep_output(output, max_results=10)
    assert results == [{"path": "src/app.py", "line": 10, "content": "hello"}]


def test_get_mirror_info_ignores_deleted_files_during_size_calc(service, monkeypatch):
    class _St:
        def __init__(self, size: int):
            self.st_size = size

    class _FakeFile:
        def __init__(self, *, size: int | None):
            self._size = size

        def is_file(self) -> bool:
            return True

        def stat(self):
            if self._size is None:
                raise FileNotFoundError("deleted during traversal")
            return _St(self._size)

    class _FakeRepoPath:
        def exists(self) -> bool:
            return True

        def rglob(self, pattern: str):
            assert pattern == "*"
            return [_FakeFile(size=10), _FakeFile(size=None), _FakeFile(size=5)]

        def __str__(self) -> str:
            return "/tmp/fake-repo.git"

    monkeypatch.setattr(service, "_get_repo_path", lambda repo_name: _FakeRepoPath())
    monkeypatch.setattr(service, "get_current_sha", lambda repo_name: "deadbeef")

    info = service.get_mirror_info("test-repo")
    assert info is not None
    assert info["size_bytes"] == 15


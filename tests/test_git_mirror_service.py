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


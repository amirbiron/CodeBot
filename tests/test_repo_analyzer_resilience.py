import base64
import types
import pytest

import repo_analyzer as ra


class _Perf:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeRepo:
    name = "repo"
    html_url = "https://github.com/owner/repo"
    description = "desc"
    stargazers_count = 0
    forks_count = 0
    language = "Python"
    created_at = None
    updated_at = None
    open_issues_count = 0

    def get_license(self):
        return types.SimpleNamespace(license=types.SimpleNamespace(name="MIT"))

    def get_contents(self, path: str = ""):
        # Root listing: include a .github dir, a subdir, and files that trigger decode errors
        if path == "":
            bad_bytes = base64.b64encode(b"\xff\xfe").decode()
            return [
                types.SimpleNamespace(type="dir", name=".github", path=".github"),
                types.SimpleNamespace(type="dir", name="dir1", path="dir1"),
                types.SimpleNamespace(type="file", name="README.md", path="README.md", size=len(bad_bytes), content=bad_bytes),
                types.SimpleNamespace(type="file", name="pyproject.toml", path="pyproject.toml", size=len(bad_bytes), content=bad_bytes),
            ]
        if path == ".github/workflows":
            # Simulate workflows dir not accessible
            raise ra.GithubException("no workflows")
        if path == "dir1":
            # Simulate subdir listing error
            raise ra.GithubException("cannot list subdir")
        return []


class _FakeGithub:
    def __init__(self, token):  # noqa: ARG002 - signature compatibility
        self.token = token

    def get_repo(self, full: str):
        assert "/" in full
        return _FakeRepo()


@pytest.mark.asyncio
async def test_fetch_and_analyze_handles_github_and_decode_exceptions(monkeypatch):
    # Safe no-op event/metrics
    monkeypatch.setattr(ra, "emit_event", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ra, "track_performance", lambda *a, **k: _Perf(), raising=False)
    # Use fakes for Github + exceptions
    monkeypatch.setattr(ra, "Github", _FakeGithub, raising=False)
    monkeypatch.setattr(ra, "GithubException", type("GithubException", (Exception,), {}), raising=False)

    analyzer = ra.RepoAnalyzer(github_token="tkn")
    data = await analyzer.fetch_and_analyze_repo("https://github.com/owner/repo")

    assert isinstance(data, dict)
    # Since workflows access raised, CI/CD should not be marked true by this path
    assert not data.get("has_ci_cd", False)
    # Dependencies parsing of broken pyproject should not crash
    assert isinstance(data.get("dependencies", []), list)


def test_generate_suggestions_updated_at_recency_and_invalid():
    analyzer = ra.RepoAnalyzer()

    # Older than a year -> should include update_project suggestion
    suggestions = analyzer.generate_improvement_suggestions({"updated_at": "2020-01-01T00:00:00Z"})
    assert any(s.get("id") == "update_project" for s in suggestions)

    # Invalid type triggers guarded exception path and should not raise
    suggestions2 = analyzer.generate_improvement_suggestions({"updated_at": 123})
    assert all(s.get("id") != "update_project" for s in suggestions2)

import base64
import types
import pytest

import repo_analyzer as ra


class _Perf:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _LicenseObj:
    def __init__(self, name: str = "MIT"):
        self.license = types.SimpleNamespace(name=name)


class _FakeRepo:
    name = "repo"
    html_url = "https://github.com/owner/repo"
    description = "desc"
    stargazers_count = 1
    forks_count = 2
    language = "Python"
    created_at = None
    updated_at = None
    open_issues_count = 0

    def get_license(self):
        return _LicenseObj()

    def get_contents(self, path: str = ""):
        if path == "":
            content = base64.b64encode(b"installation usage example").decode()
            return [types.SimpleNamespace(type="file", name="README.md", path="README.md", size=len(content), content=content)]
        if path == ".github/workflows":
            return []
        return []


class _FakeGithub:
    def __init__(self, token):
        self.token = token

    def get_repo(self, full: str):
        assert "/" in full
        return _FakeRepo()


@pytest.mark.asyncio
async def test_repo_analyzer_emits_events(monkeypatch):
    captured = {"evts": []}

    def _emit(event: str, severity: str = "info", **fields):
        captured["evts"].append((event, severity, fields))

    monkeypatch.setattr(ra, "emit_event", _emit, raising=False)
    monkeypatch.setattr(ra, "track_performance", lambda *a, **k: _Perf(), raising=False)
    monkeypatch.setattr(ra, "Github", _FakeGithub, raising=False)

    analyzer = ra.RepoAnalyzer(github_token="tkn")
    data = await analyzer.fetch_and_analyze_repo("https://github.com/owner/repo")

    assert data["repo_name"] == _FakeRepo().name
    events = [e[0] for e in captured["evts"]]
    assert "repo_analysis_start" in events
    assert "repo_analysis_parsed" in events
    assert "repo_analysis_done" in events


def test_parse_url_error_emits_event(monkeypatch):
    captured = {"evts": []}

    def _emit(event: str, severity: str = "info", **fields):
        captured["evts"].append((event, severity, fields))

    monkeypatch.setattr(ra, "emit_event", _emit, raising=False)

    with pytest.raises(ValueError):
        ra.RepoAnalyzer().parse_github_url("not-a-url")

    assert any(e[0] == "repo_parse_url_error" for e in captured["evts"]) 

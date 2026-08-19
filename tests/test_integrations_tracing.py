import pytest

from integrations import CodeSharingService


@pytest.mark.asyncio
async def test_share_code_records_service_attributes(monkeypatch):
    recorded: list[dict[str, object]] = []

    def _record(attrs: dict[str, object]) -> None:
        recorded.append(dict(attrs))

    class _FakeGist:
        def __init__(self):
            self.calls = []

        def is_available(self) -> bool:
            return False

    class _FakePaste:
        def is_available(self) -> bool:
            return False

    monkeypatch.setattr("integrations.set_current_span_attributes", _record, raising=False)
    monkeypatch.setattr("integrations.GitHubGistIntegration", _FakeGist, raising=False)
    monkeypatch.setattr("integrations.PastebinIntegration", _FakePaste, raising=False)

    service = CodeSharingService()

    result = await service.share_code("internal", "demo.py", "print()", "python")
    assert result is not None

    assert any(attrs.get("service") == "internal" for attrs in recorded)


@pytest.mark.asyncio
async def test_share_code_marks_unavailable_services(monkeypatch):
    recorded: list[dict[str, object]] = []

    def _record(attrs: dict[str, object]) -> None:
        recorded.append(dict(attrs))

    class _FakePaste:
        def is_available(self) -> bool:
            return False

    monkeypatch.setattr("integrations.set_current_span_attributes", _record, raising=False)
    monkeypatch.setattr("integrations.PastebinIntegration", _FakePaste, raising=False)

    service = CodeSharingService()

    # השירות המשולב לא מחזיק טוקן של משתמש, ולכן הוא מסרב ליצור Gist במקום
    # ליצור אותו תחת חשבון המערכת.
    result = await service.share_code("gist", "demo.py", "print()", "python")

    assert result is None
    assert any(attrs.get("service") == "gist" for attrs in recorded)
    assert any(attrs.get("reason") == "gist_requires_user_token" for attrs in recorded)
    assert not hasattr(service, "gist"), "השירות המשולב לא אמור להחזיק אינטגרציית Gist גלובלית"

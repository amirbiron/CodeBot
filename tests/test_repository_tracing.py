from database import repository


class _DummyCollection:
    def aggregate(self, pipeline, allowDiskUse=True):
        # simulate pipeline returning items for data query and count query
        if pipeline and pipeline[-1].get("$limit"):
            return [{"file_name": "demo.py"}]
        if pipeline and pipeline[-1].get("$count"):
            return [{"count": 1}]
        return [{"file_name": "demo.py"}]


class _DummyManager:
    def __init__(self) -> None:
        self.collection = _DummyCollection()


def test_repository_get_user_files_traced(monkeypatch):
    recorded: list[dict[str, object]] = []

    def _record(attrs: dict[str, object]) -> None:
        recorded.append(dict(attrs))

    monkeypatch.setattr(repository, "set_current_span_attributes", _record, raising=False)

    repo = repository.Repository.__new__(repository.Repository)
    repo.manager = _DummyManager()

    rows = repo.get_user_files(user_id=7, limit=1)

    assert rows == [{"file_name": "demo.py"}]
    assert any(attrs.get("results_count") == 1 for attrs in recorded)

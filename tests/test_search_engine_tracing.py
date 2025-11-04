import search_engine


def test_search_engine_traced_records_results(monkeypatch):
    recorded: list[dict[str, object]] = []

    def _record(attrs: dict[str, object]) -> None:
        recorded.append(dict(attrs))

    monkeypatch.setattr(search_engine, "set_current_span_attributes", _record, raising=False)

    engine = search_engine.AdvancedSearchEngine()

    result = search_engine.SearchResult(
        file_name="demo.py",
        content="print('hi')",
        programming_language="python",
        tags=[],
        created_at=search_engine.datetime.now(search_engine.timezone.utc),
        updated_at=search_engine.datetime.now(search_engine.timezone.utc),
        version=1,
        relevance_score=1.0,
    )

    monkeypatch.setattr(engine, "get_index", lambda user_id: object())
    monkeypatch.setattr(engine, "_text_search", lambda query, index, user_id: [result])

    outputs = engine.search(user_id=123, query="print")
    assert outputs == [result]

    assert any(attrs.get("results_count") == 1 for attrs in recorded)
    assert any(attrs.get("user_id_hash") for attrs in recorded)

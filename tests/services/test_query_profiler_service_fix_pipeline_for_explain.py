from services.query_profiler_service import QueryProfilerService


class _DummyDBManager:
    pass


def test_fix_pipeline_for_explain_fixes_sort_empty_string() -> None:
    svc = QueryProfilerService(_DummyDBManager())
    pipeline = [{"$sort": {"file_name": ""}}]

    fixed = svc._fix_pipeline_for_explain(pipeline)

    assert fixed == [{"$sort": {"file_name": 1}}]


def test_fix_pipeline_for_explain_fixes_nested_sort_empty_string() -> None:
    svc = QueryProfilerService(_DummyDBManager())
    pipeline = [{"$facet": {"by_name": [{"$sort": {"file_name": ""}}]}}]

    fixed = svc._fix_pipeline_for_explain(pipeline)

    assert fixed == [{"$facet": {"by_name": [{"$sort": {"file_name": 1}}]}}]


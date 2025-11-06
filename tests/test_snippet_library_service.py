from services.snippet_library_service import submit_snippet, list_public_snippets


def test_submit_validation_errors():
    bad = submit_snippet(title="ab", description="d", code="", language="", user_id=1)
    assert bad['ok'] is False
    bad2 = submit_snippet(title="abc", description="desc", code="", language="py", user_id=1)
    assert bad2['ok'] is False


def test_list_public_returns_tuple_no_db():
    items, total = list_public_snippets()
    assert isinstance(items, list)
    assert isinstance(total, int)

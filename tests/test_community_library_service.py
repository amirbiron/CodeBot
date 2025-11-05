from services.community_library_service import submit_item, list_public

def test_submit_validation_errors():
    bad = submit_item(title="ab", description="d", url="bad", user_id=1)
    assert bad['ok'] is False
    bad2 = submit_item(title="abc", description="", url="bad", user_id=1)
    assert bad2['ok'] is False


def test_list_public_returns_tuple_no_db():
    items, total = list_public()
    assert isinstance(items, list)
    assert isinstance(total, int)

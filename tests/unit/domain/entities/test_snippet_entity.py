from src.domain.entities.snippet import Snippet


def test_snippet_defaults():
    s = Snippet(user_id=1, filename='a.py', code='x', language='python')
    assert s.version == 1
    assert s.is_favorite is False
    assert isinstance(s.created_at, type(s.updated_at))
    assert isinstance(s.tags, list) and s.tags == []

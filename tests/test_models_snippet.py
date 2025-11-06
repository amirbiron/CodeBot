from database.models import Snippet


def test_snippet_defaults():
    s = Snippet(title='t', description='d', code='x', language='py', user_id=1)
    assert s.submitted_at is not None
    assert s.status == 'pending'

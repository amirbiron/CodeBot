import importlib
import pytest


def _import_service():
    return importlib.import_module('services.snippet_library_service')


@pytest.mark.asyncio
async def test_builtins_do_not_reappear_on_page2_when_dup_on_page1(monkeypatch):
    svc = _import_service()

    # Built-ins contain a duplicate title and another unique one
    builtins = [
        {'title': 'Dup', 'description': 'b1', 'code': 'x', 'language': 'python', 'approved_at': None, 'username': 'CodeBot'},
        {'title': 'Other', 'description': 'b2', 'code': 'y', 'language': 'python', 'approved_at': None, 'username': 'CodeBot'},
    ]
    monkeypatch.setattr(svc, 'BUILTIN_SNIPPETS', builtins, raising=False)

    class _Repo:
        def list_public_snippets(self, **kw):
            page = int(kw.get('page') or 1)
            per_page = int(kw.get('per_page') or 1)
            # DB has exactly one item titled 'Dup' on page 1; no items on page 2
            if page == 1:
                return ([{'title': 'Dup', 'description': 'db', 'code': 'z', 'language': 'python', 'approved_at': None, 'username': 'user'}][:per_page], 1)
            return ([], 1)

    # Patch DB repo
    monkeypatch.setattr(svc, '_db', type('_DB', (), {'_get_repo': lambda self=None: _Repo()})(), raising=False)

    # Page 2 should NOT return the built-in 'Dup' again; it should return 'Other'
    items, total = svc.list_public_snippets(page=2, per_page=1)
    titles = [it.get('title') for it in items]
    assert 'Dup' not in titles
    assert 'Other' in titles
    assert total >= 1

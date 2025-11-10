import importlib
import pytest


def _import_service():
    return importlib.import_module('services.snippet_library_service')


def _builtin_titles(svc):
    return [it.get('title') for it in getattr(svc, 'BUILTIN_SNIPPETS', [])]


def test_builtins_returned_when_db_empty(monkeypatch):
    svc = _import_service()

    class _Repo:
        def list_public_snippets(self, **kw):
            return [], 0

    # Monkeypatch the DB repo
    monkeypatch.setattr(svc, '_db', type('_DB', (), {'_get_repo': lambda self=None: _Repo()})(), raising=False)

    items, total = svc.list_public_snippets(page=1, per_page=30)
    assert items, 'expected built-in snippets on page 1'
    assert total >= len(items)


def test_builtins_dedup_by_title(monkeypatch):
    svc = _import_service()
    titles = _builtin_titles(svc)
    assert titles, 'expected at least one built-in'
    dup_title = titles[0]

    db_row = {
        'title': dup_title,
        'description': 'DB item',
        'code': 'print(1)\n',
        'language': 'python',
        'approved_at': None,
        'username': 'user1',
    }

    class _Repo:
        def list_public_snippets(self, **kw):
            return [db_row], 1

    monkeypatch.setattr(svc, '_db', type('_DB', (), {'_get_repo': lambda self=None: _Repo()})(), raising=False)

    items, total = svc.list_public_snippets(page=1, per_page=100)
    # לא אמורות להיות כפילויות לפי כותרת
    seen = set()
    for it in items:
        t = (it.get('title') or '').strip().lower()
        assert t not in seen
        seen.add(t)
    # total כולל built-ins+DB ללא כפילות
    assert total >= len(items)


def test_page2_no_builtins_but_total_counts(monkeypatch):
    svc = _import_service()

    db_items = [{
        'title': 'From DB',
        'description': 'X',
        'code': 'print(2)\n',
        'language': 'python',
        'approved_at': None,
        'username': 'user2',
    }]

    class _Repo:
        def list_public_snippets(self, **kw):
            return db_items, 1

    monkeypatch.setattr(svc, '_db', type('_DB', (), {'_get_repo': lambda self=None: _Repo()})(), raising=False)

    items, total = svc.list_public_snippets(page=2, per_page=30)
    # בעמוד >1 מוחזר DB בלבד
    assert items == db_items
    # אבל הספירה כוללת גם את ה-built-ins
    assert total >= 1


def test_builtins_paginate_before_db(monkeypatch):
    svc = _import_service()

    builtin_fixtures = [{
        'title': f'Builtin #{i}',
        'description': f'B{i}',
        'code': f'print({i})\n',
        'language': 'python',
        'approved_at': None,
        'username': 'CodeBot',
    } for i in range(40)]

    class _Repo:
        def list_public_snippets(self, **kw):
            return [], 0

    monkeypatch.setattr(svc, 'BUILTIN_SNIPPETS', builtin_fixtures, raising=False)
    monkeypatch.setattr(svc, '_db', type('_DB', (), {'_get_repo': lambda self=None: _Repo()})(), raising=False)

    items_page1, total = svc.list_public_snippets(page=1, per_page=30)
    items_page2, _ = svc.list_public_snippets(page=2, per_page=30)

    assert len(items_page1) == 30
    assert [item['title'] for item in items_page2] == [f'Builtin #{i}' for i in range(30, 40)]
    assert total == len(builtin_fixtures)

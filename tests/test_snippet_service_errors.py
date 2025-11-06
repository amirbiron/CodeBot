import types
import pytest

import services.snippet_library_service as svc


class _DBBad:
    def _get_repo(self):
        raise RuntimeError("boom")


def test_service_handles_repo_exceptions(monkeypatch):
    monkeypatch.setattr(svc, '_db', _DBBad(), raising=False)
    assert svc.approve_snippet('x', 1) is False
    assert svc.reject_snippet('x', 1, 'r') is False
    items, total = svc.list_public_snippets()
    assert items == [] and total == 0
    pend = svc.list_pending_snippets()
    assert pend == []

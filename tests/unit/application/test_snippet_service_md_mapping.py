from unittest.mock import MagicMock


def test_snippet_service_detect_language_md_variants():
    from src.application.services.snippet_service import SnippetService

    # Create service with minimal dummies
    repo = MagicMock()
    norm = MagicMock()
    svc = SnippetService(snippet_repository=repo, code_normalizer=norm)

    assert svc._detect_language('x', 'doc.md') == 'markdown'
    assert svc._detect_language('x', 'notes.markdown') == 'markdown'
    assert svc._detect_language('x', 'longread.mdown') == 'markdown'
    assert svc._detect_language('x', 'draft.mkd') == 'markdown'
    assert svc._detect_language('x', 'spec.mkdn') == 'markdown'

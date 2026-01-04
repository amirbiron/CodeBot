from unittest.mock import patch

import pytest


def test_content_search_uses_semantic_when_enabled():
    # Arrange: force semantic enabled.
    # חשוב: בסוויטה גדולה ייתכן ש-modules ייטענו מול stubbed config,
    # לכן נעדיף לפאץ' את האובייקט שכבר מיובא בתוך search_engine.
    import search_engine as se

    with patch.object(se.config, "SEMANTIC_SEARCH_ENABLED", True, create=True):
        from search_engine import SearchType, search_engine

        # We don't want to hit DB/HTTP; just ensure routing happens.
        with patch.object(search_engine, "_semantic_search", return_value=[]) as sem:
            with patch.object(search_engine, "_content_search", return_value=[]) as cont:
                # Act
                _ = search_engine.search(user_id=1, query="validate email", search_type=SearchType.CONTENT, limit=5)

                # Assert
                assert sem.called is True
                assert cont.called is False


def test_content_search_falls_back_to_content_when_disabled():
    import search_engine as se

    with patch.object(se.config, "SEMANTIC_SEARCH_ENABLED", False, create=True):
        from search_engine import SearchType, search_engine

        with patch.object(search_engine, "_semantic_search", return_value=[]) as sem:
            with patch.object(search_engine, "_content_search", return_value=[]) as cont:
                _ = search_engine.search(user_id=1, query="validate email", search_type=SearchType.CONTENT, limit=5)

                assert sem.called is False
                assert cont.called is True


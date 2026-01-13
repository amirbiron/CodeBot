import pytest


def test_refactor_should_retry_does_not_retry_on_empty_tuple_result():
    import refactor_handlers as rh

    assert rh._should_retry_with_legacy("get_user_large_files", ([], 0)) is False
    assert rh._should_retry_with_legacy("get_regular_files_paginated", ([], 0)) is False
    assert rh._should_retry_with_legacy("some_other_tuple", ([], 0)) is False


def test_refactor_should_retry_retries_on_tuple_all_none():
    import refactor_handlers as rh

    assert rh._should_retry_with_legacy("x", (None, None)) is True


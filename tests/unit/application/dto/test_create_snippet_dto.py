import pytest

from src.application.dto.create_snippet_dto import CreateSnippetDTO


def test_create_snippet_dto_valid():
    dto = CreateSnippetDTO(user_id=123, filename="a.py", code="print(1)")
    assert dto.user_id == 123
    assert dto.filename == "a.py"
    assert dto.code == "print(1)"


def test_create_snippet_dto_invalid_user():
    with pytest.raises(ValueError):
        CreateSnippetDTO(user_id=0, filename="a.py", code="x")


def test_create_snippet_dto_missing_filename():
    with pytest.raises(ValueError):
        CreateSnippetDTO(user_id=1, filename="", code="x")


def test_create_snippet_dto_missing_code():
    with pytest.raises(ValueError):
        CreateSnippetDTO(user_id=1, filename="a.py", code="")

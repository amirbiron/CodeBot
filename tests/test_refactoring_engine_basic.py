import pytest

from refactoring_engine import RefactoringEngine, RefactorType, CodeAnalyzer


@pytest.fixture
def sample_code():
    return """
def user_login(username, password):
    return True

def user_logout(user_id):
    return True

def data_fetch(query):
    return []

def data_save(data):
    return True
"""


def test_code_analyzer_basic(sample_code):
    analyzer = CodeAnalyzer(sample_code, "test.py")
    assert analyzer.analyze() is True
    assert len(analyzer.functions) == 4


def test_split_functions(sample_code):
    engine = RefactoringEngine()
    result = engine.propose_refactoring(
        code=sample_code,
        filename="test.py",
        refactor_type=RefactorType.SPLIT_FUNCTIONS,
    )
    assert result.success is True
    assert result.proposal is not None
    assert len(result.proposal.new_files) >= 2


def test_convert_to_classes(sample_code):
    engine = RefactoringEngine()
    result = engine.propose_refactoring(
        code=sample_code,
        filename="test.py",
        refactor_type=RefactorType.CONVERT_TO_CLASSES,
    )
    assert result.success is True
    assert result.proposal is not None
    assert len(result.proposal.new_files) >= 1
    # לפחות קובץ אחד כולל class
    assert any('class ' in content for content in result.proposal.new_files.values())


def test_invalid_syntax_returns_error():
    invalid_code = "def broken( syntax error"
    engine = RefactoringEngine()
    result = engine.propose_refactoring(
        code=invalid_code,
        filename="bad.py",
        refactor_type=RefactorType.SPLIT_FUNCTIONS,
    )
    assert result.success is False
    assert result.error


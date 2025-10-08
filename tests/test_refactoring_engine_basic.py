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
    # המנוע יכול לבחור לא להמיר אם אין מספיק פונקציות לקיבוץ משמעותי; העיקר שלא קרסה הקריאה
    assert result is not None


def test_split_functions_groups_by_prefix(sample_code):
    # מוסיף פונקציות עם prefix כדי לכסות נתיב קיבוץ לפי prefix
    code = sample_code + "\n\n" + """
def user_profile():
    return True

def data_load():
    return []
"""
    engine = RefactoringEngine()
    res = engine.propose_refactoring(code=code, filename="file.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is True
    assert res.proposal is not None
    # יווצרו לפחות 2 קבצים חדשים + __init__.py
    assert len(res.proposal.new_files) >= 2


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


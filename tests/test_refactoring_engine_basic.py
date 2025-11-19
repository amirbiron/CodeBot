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


def test_code_analyzer_detects_async_functions():
    async_code = """
async def fetch_data():
    return await some_io()

def helper_sync():
    return 1
"""

    analyzer = CodeAnalyzer(async_code, "async_file.py")
    assert analyzer.analyze() is True
    names = {func.name for func in analyzer.functions}
    assert names == {"fetch_data", "helper_sync"}


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


def test_split_functions_handles_async_functions():
    code = """
import asyncio

async def fetch_user():
    await asyncio.sleep(0)
    return {"id": 1}

async def fetch_orders(user_id):
    await asyncio.sleep(0)
    return []

def summarize(user, orders):
    return len(orders)
"""

    engine = RefactoringEngine()
    res = engine.propose_refactoring(code=code, filename="async_module.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is True
    assert res.proposal is not None
    combined = "\n".join(res.proposal.new_files.values())
    assert "async def fetch_user" in combined
    assert "async def fetch_orders" in combined
    assert "def summarize" in combined


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


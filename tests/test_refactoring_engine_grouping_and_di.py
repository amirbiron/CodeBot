import pytest

from refactoring_engine import RefactoringEngine, RefactorType


def test_group_by_dependencies_path():
    code = """
def a():
    b()

def b():
    return 1

def c():
    return 2
"""
    engine = RefactoringEngine()
    res = engine.propose_refactoring(code=code, filename="dep.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is True
    assert res.proposal is not None


def test_convert_to_classes_too_few_functions():
    engine = RefactoringEngine()
    code = "def only_one():\n    return 1\n"
    with pytest.raises(ValueError):
        engine.propose_refactoring(code=code, filename="one.py", refactor_type=RefactorType.CONVERT_TO_CLASSES)


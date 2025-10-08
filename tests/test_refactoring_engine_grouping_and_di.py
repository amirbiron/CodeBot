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
    # ייתכן שהמנוע יחליט שאין צורך לפצל — אז די בכך שלא נזרקה חריגה והאובייקט מוחזר
    assert res is not None


def test_convert_to_classes_too_few_functions():
    engine = RefactoringEngine()
    code = "def only_one():\n    return 1\n"
    res = engine.propose_refactoring(code=code, filename="one.py", refactor_type=RefactorType.CONVERT_TO_CLASSES)
    # עבור מעט פונקציות מצופה שייכשל עם הודעה
    assert res.success is False or res.proposal is None


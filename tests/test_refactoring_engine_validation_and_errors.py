import pytest

from refactoring_engine import RefactoringEngine, RefactorType


def test_engine_invalid_syntax_error():
    engine = RefactoringEngine()
    res = engine.propose_refactoring(code="def broken( syntax", filename="bad.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is False
    assert res.error


def test_engine_validate_proposal_syntax_ok():
    engine = RefactoringEngine()
    code = "def t():\n    return 1\n"
    res = engine.propose_refactoring(code=code, filename="ok.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    # אם אין פיצול קבוצות, עלול לזרוק ValueError — נתפוס ונבדוק _validate בנפרד
    # לכן נבדוק פונקציה פנימית ישירות עם הצעה קטנה
    from refactoring_engine import RefactorProposal, RefactorType as RT
    proposal = RefactorProposal(refactor_type=RT.SPLIT_FUNCTIONS, original_file="x.py", new_files={"a.py": code}, description="d", changes_summary=[])
    assert engine._validate_proposal(proposal) is True


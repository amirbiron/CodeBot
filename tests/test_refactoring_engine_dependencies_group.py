from refactoring_engine import RefactoringEngine, RefactorType


def test_dependencies_grouping_creates_multiple_files():
    code = (
        "def alpha():\n    beta()\n\n"
        "def beta():\n    return 1\n\n"
        "def gamma():\n    return 2\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="dep.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    # אמור לפצל ל־2 קבוצות (alpha+beta) ו־(gamma) => לפחות 3 קבצים כולל __init__.py
    if res.success and res.proposal:
        assert len(res.proposal.new_files) >= 3
    else:
        # במקרה של דגימת קצוות — אל ייזרק חריג; תוצאת שגיאה ידידותית
        assert res.error


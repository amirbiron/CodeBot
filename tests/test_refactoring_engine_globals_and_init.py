from refactoring_engine import RefactoringEngine, RefactorType


def test_split_warnings_for_globals_and_imports_needed():
    code = (
        "import sys\n"
        "x = 1\n\n"
        "def user_a():\n    return x\n\n"
        "def data_b():\n    return 2\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="g.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is True
    prop = res.proposal
    # יש אזהרת גלובלים
    assert any('גלובל' in w or '⚠️' in w for w in (prop.warnings or []))
    # __init__.py קיים ומייצא
    init = prop.new_files.get("__init__.py", "")
    assert "from ." in init
    # imports_needed כוללים את import sys עבור קבצים שנוצרו
    assert any("import sys" in imp for lst in prop.imports_needed.values() for imp in lst)


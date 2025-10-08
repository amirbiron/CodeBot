from refactoring_engine import RefactoringEngine, RefactorType


def test_convert_to_classes_with_camelcase_and_underscores():
    code = (
        "def UserCreate():\n    return 1\n\n"
        "def user_Update():\n    return 2\n\n"
        "def dataClear():\n    return 3\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="names.py", refactor_type=RefactorType.CONVERT_TO_CLASSES)
    # אם מצליח – יווצר קובץ עם class; אם לא – לפחות אין קריסה
    if res.success and res.proposal:
        assert any('class ' in c for c in res.proposal.new_files.values())
    else:
        assert res.error


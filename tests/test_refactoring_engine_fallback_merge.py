from refactoring_engine import RefactoringEngine, RefactorType


def test_fallback_prefix_merge_does_not_drop_functions_split():
    # ארבע פונקציות עם prefixes שונים שכולם תחת אותו דומיין
    code = (
        "def alpha_do():\n    return 1\n\n"
        "def beta_run():\n    return 2\n\n"
        "def gamma_work():\n    return 3\n\n"
        "def delta_exec():\n    return 4\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="mix.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is True and res.proposal is not None
    combined = "\n".join(res.proposal.new_files.values())
    # ודא שאף פונקציה לא אבדה
    assert "def alpha_do" in combined
    assert "def beta_run" in combined
    assert "def gamma_work" in combined
    assert "def delta_exec" in combined


def test_fallback_prefix_merge_does_not_drop_functions_oop():
    code = (
        "def alpha_do():\n    return 1\n\n"
        "def beta_run():\n    return 2\n\n"
        "def gamma_work():\n    return 3\n\n"
        "def delta_exec():\n    return 4\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="mix.py", refactor_type=RefactorType.CONVERT_TO_CLASSES)
    assert res.success is True and res.proposal is not None
    combined = "\n".join(res.proposal.new_files.values())
    assert "def alpha_do" in combined
    assert "def beta_run" in combined
    assert "def gamma_work" in combined
    assert "def delta_exec" in combined

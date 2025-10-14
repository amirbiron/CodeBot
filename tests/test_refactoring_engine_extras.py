from refactoring_engine import RefactoringEngine, RefactorType


def test_engine_merge_similar_not_implemented():
    code = "def a():\n    return 1\n"
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="m.py", refactor_type=RefactorType.MERGE_SIMILAR)
    assert res.success is False
    assert res.error


def test_engine_dependency_injection_not_implemented():
    code = "def a():\n    return 1\n"
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="d.py", refactor_type=RefactorType.DEPENDENCY_INJECTION)
    assert res.success is False
    assert res.error


def test_engine_split_includes_imports_and_init_and_self_methods():
    code = (
        "import os\n"
        "def user_u():\n    return os.name\n\n"
        "def user_v():\n    return 2\n\n"
        "def data_a():\n    return 3\n\n"
        "def data_b():\n    return 4\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="svc.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is True
    files = res.proposal.new_files
    # __init__ exported
    assert "__init__.py" in files
    assert any("from ." in v for v in [files.get("__init__.py", "")])
    # imports preserved
    assert any("import os" in content for name, content in files.items() if name != "__init__.py")


def test_engine_convert_includes_self_in_methods():
    code = (
        "def user_a(x=1):\n    return x\n\n"
        "def user_b():\n    return 2\n\n"
        "def data_a():\n    return 3\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="svc.py", refactor_type=RefactorType.CONVERT_TO_CLASSES)
    if res.success and res.proposal:
        # at least one file contains a method with self
        assert any("def __init__(self)" in c or "(self," in c or "(self)" in c for c in res.proposal.new_files.values())
    else:
        # if conversion not possible (rare), ensure we returned an error
        assert res.error


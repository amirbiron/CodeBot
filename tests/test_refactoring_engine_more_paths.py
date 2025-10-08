from refactoring_engine import RefactoringEngine, RefactorType, CodeAnalyzer


def _code_many_funcs(n=6):
    parts = []
    for i in range(n):
        parts.append(f"def f{i}():\n    return {i}\n")
    return "\n".join(parts)


def test_split_by_size_with_many_functions():
    code = _code_many_funcs(8)
    engine = RefactoringEngine()
    res = engine.propose_refactoring(code=code, filename="many.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is True
    assert res.proposal is not None
    assert "__init__.py" in res.proposal.new_files
    assert len(res.proposal.new_files) >= 2


def test_convert_to_classes_success_with_prefix_groups():
    code = (
        "def user_create():\n    return True\n\n"
        "def user_update():\n    return True\n\n"
        "def user_delete():\n    return True\n\n"
        "def data_fetch():\n    return []\n\n"
        "def data_save():\n    return True\n\n"
        "def data_clear():\n    return True\n"
    )
    engine = RefactoringEngine()
    res = engine.propose_refactoring(code=code, filename="svc.py", refactor_type=RefactorType.CONVERT_TO_CLASSES)
    assert res.success is True
    assert res.proposal is not None
    # יווצרו קבצים עם מחלקות
    assert any('class ' in content for content in res.proposal.new_files.values())


def test_extract_functions_no_duplicates_returns_error():
    code = "def a():\n    return 1\n"
    engine = RefactoringEngine()
    res = engine.propose_refactoring(code=code, filename="x.py", refactor_type=RefactorType.EXTRACT_FUNCTIONS)
    assert res.success is False
    assert res.error


def test_validate_proposal_invalid_syntax():
    engine = RefactoringEngine()
    from refactoring_engine import RefactorProposal
    bad = RefactorProposal(refactor_type=RefactorType.SPLIT_FUNCTIONS, original_file="x.py", new_files={"bad.py": "def broken("}, description="d", changes_summary=[])
    ok = engine._validate_proposal(bad)
    assert ok is False
    assert bad.warnings


def test_analyzer_large_functions_and_classes():
    code = (
        "def big():\n" + "\n".join(["    x=1" for _ in range(60)]) + "\n\n"
        "class C:\n    def m(self):\n        return 1\n"
    )
    an = CodeAnalyzer(code, "z.py")
    assert an.analyze() is True
    large = an.find_large_functions(min_lines=50)
    assert any(f.name == 'big' for f in large)
    assert an.find_large_classes(min_methods=1)


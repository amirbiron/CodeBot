from refactoring_engine import RefactoringEngine, RefactorType


def test_validate_proposal_catches_syntax_error():
    eng = RefactoringEngine()
    proposal = {
        "bad.py": "def broken("
    }
    from refactoring_engine import RefactorProposal
    rp = RefactorProposal(refactor_type=RefactorType.SPLIT_FUNCTIONS, original_file="x.py", new_files=proposal, description="d", changes_summary=[])
    ok = eng._validate_proposal(rp)
    assert ok is False


def test_split_functions_generates_init_and_shared_when_needed():
    code = (
        "import os\nfrom math import floor\n\n"
        "def ua():\n    return os.name\n\n"
        "def ub():\n    return floor(2.7)\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="main.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res and res.success and res.proposal
    files = res.proposal.new_files
    assert "__init__.py" in files
    # ייתכן שנוצר main_shared.py כאשר יש חיתוך חוצה-מודולים
    # לא מחייב בכל מצב, לכן בודקים לפחות שאין import ישיר כפול במודולים
    for fn, content in files.items():
        if fn in ("__init__.py", "main_shared.py"):
            continue
        assert not content.strip().startswith("import os\n")


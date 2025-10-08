from refactoring_engine import RefactoringEngine, CodeAnalyzer, RefactorType


def test_filter_preserves_star_import():
    eng = RefactoringEngine()
    code = "def a():\n    return 1\n"
    imports = ["from .x_shared import *"]
    out = eng._filter_imports_for_code(imports, code)
    assert "from .x_shared import *" in out


def test_inject_shared_when_no_imports_block_present():
    # מוודא שנזרק shared גם אם אחרי הדוקסטרינג אין בלוק imports (סונן הכל)
    code = (
        "import os\n"
        "def ua():\n    return os.name\n\n"
        "def ub():\n    return os.name\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="m.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res and res.success and res.proposal
    files = res.proposal.new_files
    assert 'm_shared.py' in files
    for fn, content in files.items():
        if fn in ("__init__.py", "m_shared.py"):
            continue
        assert ("from .m_shared import *" in content) or ("from .m_shared import os" in content)


def test_post_cleanup_handles_syntax_error_gracefully():
    eng = RefactoringEngine()
    files = {"bad.py": '"""\nbad\n"""\n\nimport os\n\ndef oops(:\n    pass\n'}
    out = eng.post_refactor_cleanup(files)
    # במקרה של שגיאת תחביר, התוכן נשאר כמו שהוא
    assert out["bad.py"].startswith('"""')


from refactoring_engine import RefactoringEngine


def test_centralize_no_common_imports_noop():
    eng = RefactoringEngine()
    files = {
        "m_a.py": '"""\nA\n"""\n\nfrom math import sqrt\n\ndef a():\n    return sqrt(4)\n',
        "m_b.py": '"""\nB\n"""\n\nimport os\n\ndef b():\n    return os.name\n',
        "__init__.py": ''
    }
    per = {
        "m_a.py": ["from math import sqrt"],
        "m_b.py": ["import os"],
    }
    out = eng._centralize_common_imports(files.copy(), per, "m")
    # לא נוצר shared כי אין חיתוך משותף
    assert 'm_shared.py' not in out
    # לא הוזרק shared
    assert 'from .m_shared import' not in out['m_a.py']
    assert 'from .m_shared import' not in out['m_b.py']


def test_filter_imports_unparsable_line_kept():
    eng = RefactoringEngine()
    code = "def a():\n    return 1\n"
    imports = ["import $$$not_valid!!!"]
    out = eng._filter_imports_for_code(imports, code)
    # שורה שלא ניתנת לניתוח נשמרת ליתר בטחון
    assert imports[0] in out


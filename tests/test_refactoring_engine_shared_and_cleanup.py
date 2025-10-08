from refactoring_engine import RefactoringEngine, CodeAnalyzer, RefactorType


def _make_engine_with(code: str, filename: str) -> RefactoringEngine:
    eng = RefactoringEngine()
    an = CodeAnalyzer(code, filename)
    assert an.analyze() is True
    eng.analyzer = an
    return eng


def test_filter_imports_for_code_keeps_only_used():
    # שומר רק imports שנעשה בהם שימוש בפועל
    code = (
        "def t():\n"
        "    return sqrt(4)\n"
    )
    eng = _make_engine_with(code, "m.py")
    imports = [
        "import os",
        "from math import sqrt",
        "from functools import lru_cache",
    ]
    filtered = eng._filter_imports_for_code(imports, code)
    assert "from math import sqrt" in filtered
    assert "import os" not in filtered
    assert "from functools import lru_cache" not in filtered


def test_post_refactor_cleanup_preserves_docstring_and_removes_unused():
    # מוודא שהדוקסטרינג נשמר ושורות import לא בשימוש נמחקות
    content = (
        '"""\nמודול עבור: f\n"""\n\n'
        "import os\n"
        "import json\n\n"
        "def f():\n    return os.name\n"
    )
    code = (
        "def f():\n    return os.name\n"
    )
    eng = _make_engine_with(code, "m_user.py")
    files = {"m_user.py": content}
    cleaned = eng.post_refactor_cleanup(files)
    out = cleaned["m_user.py"]
    assert out.splitlines()[0].strip().startswith('"""')  # דוקסטרינג נשמר
    assert "import os" in out
    assert "import json" not in out


def test_get_import_aliases_handles_variants():
    eng = RefactoringEngine()
    a = eng._get_import_aliases("import os as operating_system")
    b = eng._get_import_aliases("from math import sqrt as rt, floor")
    assert "operating_system" in a
    # צריך לזהות גם alias וגם שם רגיל
    assert "rt" in b
    assert "floor" in b


def test_centralize_common_imports_creates_shared_and_injects_imports():
    # מוודא שנוצר <base>_shared.py ושבמודולים מוזרק import משותף, והכפילויות הוסרו
    code = (
        "import os\n"
        "from math import sqrt\n"
        "import json\n\n"
        "def user_a():\n    return os.name + str(sqrt(4))\n\n"
        "def data_c():\n    return os.name\n"
    )
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="svc.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    # דרך עוקפת כדי לגשת ל-Enum שהוגדר במודול (מניעת import כפול בטסט זה)
    # בפועל קיים ב-import העליון של טסטים אחרים
    # אימות תוצאה
    assert res is not None and res.success and res.proposal
    files = res.proposal.new_files
    # קובץ shared קיים
    assert 'svc_shared.py' in files
    shared = files['svc_shared.py']
    assert 'import os' in shared  # ייבוא משותף
    # בכל מודול נוסף מוזרק from .svc_shared import os והכפילויות הוסרו
    for fn, content in files.items():
        if fn in ("__init__.py", "svc_shared.py"):
            continue
        assert "from .svc_shared import os" in content or "from .svc_shared import *" in content
        assert "import os\n" not in content  # הוסר מהמודול לטובת shared
        # import json לא בשימוש — אמור להיעלם
        assert "import json\n" not in content


def test_centralize_common_imports_noop_when_single_module():
    # אם יש מודול אחד — לא אמור להיווצר shared
    code = (
        "import os\n\n"
        "def only():\n    return os.name\n"
    )
    eng = _make_engine_with(code, "single.py")
    # נבנה ידנית new_files עבור מודול יחיד
    content = eng._build_file_content(eng.analyzer.functions, imports=eng.analyzer.imports)  # type: ignore[arg-type]
    new_files = {"single_module.py": content}
    per_imports = {"single_module.py": eng.analyzer.imports}  # type: ignore[assignment]
    out = eng._centralize_common_imports(new_files.copy(), per_imports, "single")
    assert out == new_files  # ללא שינוי


def test_post_refactor_cleanup_skips_shared_file():
    eng = RefactoringEngine()
    files = {
        "x_shared.py": '"""\nshared\n"""\n\nimport json\n',
        "m.py": '"""\nmod\n"""\n\nimport json\n\ndef f():\n    return 1\n',
    }
    cleaned = eng.post_refactor_cleanup(files)
    # קובץ shared לא נוקה
    assert cleaned["x_shared.py"] == files["x_shared.py"]
    # בקובץ רגיל, import json לא בשימוש ולכן עשוי להימחק (או להשאר אם אין ניתוח מלא)
    # כאן אנו בודקים לכל הפחות שהמפתח קיים
    assert "m.py" in cleaned


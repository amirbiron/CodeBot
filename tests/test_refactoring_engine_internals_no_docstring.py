from refactoring_engine import RefactoringEngine


def test_centralize_injects_shared_without_docstring_and_removes_common_imports():
    eng = RefactoringEngine()
    base = "svc"
    new_files = {
        # ללא דוקסטרינג
        f"{base}_user.py": (
            "import os\n"
            "from math import sqrt\n\n"
            "def user_a():\n    return os.name + str(sqrt(4))\n"
        ),
        f"{base}_data.py": (
            "import os\n\n"
            "def data_b():\n    return os.name\n"
        ),
        "__init__.py": ""
    }
    per_file_imports = {
        f"{base}_user.py": ["import os", "from math import sqrt"],
        f"{base}_data.py": ["import os"],
    }
    out = eng._centralize_common_imports(new_files, per_file_imports, base)
    # נוצר shared
    assert f"{base}_shared.py" in out
    # בוצעה הסרה של import os מן המודולים והוזרק star-import בתחילתם
    for fn, content in out.items():
        if fn in ("__init__.py", f"{base}_shared.py"):
            continue
        # שורת import os הוסרה
        assert "\nimport os\n" not in content and not content.strip().startswith("import os\n")
        # הוזרק from .svc_shared import *
        assert content.strip().startswith(f"from .{base}_shared import ")


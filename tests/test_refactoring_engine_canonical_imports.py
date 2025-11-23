import os
from contextlib import contextmanager
from refactoring_engine import RefactoringEngine, RefactorType


def _module_files(files_map):
    return [
        fn
        for fn in files_map
        if fn.endswith(".py") and fn != "__init__.py" and not fn.endswith("_shared.py")
    ]


@contextmanager
def _env(var, value):
    old = os.environ.get(var)
    try:
        os.environ[var] = value
        yield
    finally:
        if old is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = old


def test_class_import_injection_to_canonical_users():
    code = """
# 1) USERS
class User:
    def __init__(self, name: str):
        self.name = name

\n# 2) FINANCE
class SubscriptionManager:
    def subscribe(self, user: User) -> bool:
        return True
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="mono.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    finance_fn = next(fn for fn in files if fn.endswith("finance.py"))
    # וידוא הזרקת יבוא למחלקה מקובץ users.py הקנוני
    assert "from .users import User" in files[finance_fn]


def test_function_import_injection_from_canonical_users():
    code = """
# 1) USERS
def user_util(name: str) -> str:
    return name.strip().lower()

\n# 2) WORKFLOWS
def run_workflow(name: str) -> str:
    return user_util(name)
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="core.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    # מצא את המודול שמגדיר את user_util
    def_mod = None
    for fn, content in files.items():
        if fn.endswith(".py") and fn != "__init__.py" and "def user_util(" in content:
            def_mod = fn.rsplit(".", 1)[0].split("/")[-1]
            break
    assert def_mod is not None, "Did not find module defining user_util"
    # ודא שמודול אחר מייבא ממנו את user_util
    imported = any(
        fn.endswith(".py")
        and fn != "__init__.py"
        and not fn.endswith("_shared.py")
        and f"from .{def_mod} import user_util" in content
        for fn, content in files.items()
    )
    assert imported, f"No module imported user_util from .{def_mod}; files: {list(files.keys())}"


def test_layered_mode_models_imports_for_classes():
    code = """
# 1) USERS
class User:
    def __init__(self, name: str):
        self.name = name
def user_name(u: User) -> str:
    return u.name

\n# 2) FINANCE
class SubscriptionManager:
    def bill(self, user: User) -> bool:
        return True
def bill(u: User) -> bool:
    return True

\n# 3) WORKFLOWS
def run(u: User) -> bool:
    sm = SubscriptionManager()
    return bill(u)
"""
    with _env("REFACTOR_LAYERED_MODE", "1"):
        eng = RefactoringEngine()
        res = eng.propose_refactoring(code=code, filename="domainful.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    # קיים models.py במצב שכבות
    assert "models.py" in files
    workflows_fn = next(fn for fn in files if fn.endswith("workflows.py"))
    content = files[workflows_fn]
    # מודול עובד מול מחלקות דרך models.py (לא משנה סדר)
    lines = [ln.strip() for ln in content.splitlines()]
    assert any(ln.startswith("from .models import") and "User" in ln and "SubscriptionManager" in ln for ln in lines)
    # וידוא הזרקת פונקציה בין-מודולית (bill) מה-finance
    assert "from .finance import bill" in content


def test_cycle_merges_into_canonical_users():
    code = """
# 1) USERS
class User:
    def __init__(self, name: str):
        self.name = name
    def stats(self):
        # קריאה לפונקציה באנליטיקה ליצירת תלות הדדית
        return aggregate_user_stats(self)

\n# 2) ANALYTICS
def aggregate_user_stats(u: User):
    # שימוש ב-User כדי להשאיר Reference דו-צדדי
    return {"name": u.name, "score": 1}
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="core.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    # אחרי פירוק מעגל, אמור להישאר קובץ דומייני יחיד: users.py
    module_files = [fn for fn in files if fn.endswith(".py") and fn != "__init__.py" and not fn.endswith("_shared.py")]
    assert len(module_files) == 1
    merged_fn = module_files[0]
    assert merged_fn.endswith("users.py"), f"Expected merge target users.py, got: {merged_fn}"
    merged_content = files[merged_fn]
    # אין self-import ל-users
    assert "from .users import " not in merged_content
    # יש סימון של קוד שמוזג מקובץ האנליטיקה הלא-קנוני
    assert "# ---- merged from core_analytics.py" in merged_content

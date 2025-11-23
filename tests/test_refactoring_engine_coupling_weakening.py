from refactoring_engine import RefactoringEngine, RefactorType


def _module_files(files_map):
    return [
        fn
        for fn in files_map
        if fn.endswith(".py") and fn != "__init__.py" and not fn.endswith("_shared.py")
    ]


def _module_stems(files_map):
    return [
        fn.rsplit(".", 1)[0].split("/")[-1]
        for fn in _module_files(files_map)
    ]


def test_inventory_not_collocated_without_mutual_mentions():
    code = """
# 1) USERS
class User:
    def __init__(self, name: str):
        self.name = name

class UserManager:
    def add(self, user: User) -> bool:
        return True

\n# 2) INVENTORY
class Product:
    def __init__(self, sku: str):
        self.sku = sku

class Inventory:
    def count(self) -> int:
        return 0

\n# 3) BILLING
class SubscriptionManager:
    def activate(self, user: User) -> bool:
        return True
    def cancel(self, user: User) -> bool:
        return True
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="core_monolith.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    stems = set(_module_stems(files))
    # דומיינים נפרדים נשמרים – אין איחוד אגרסיבי ל-core
    assert "users" in stems
    assert "inventory" in stems
    assert "finance" in stems  # billing → finance.py
    # ודא ש-User ו-UserManager נשארו יחד ב-users.py
    users_fn = next(fn for fn in files if fn.endswith("users.py"))
    assert "class User" in files[users_fn]
    assert "class UserManager" in files[users_fn]
    # אין צורך בייבוא מ-inventory בתוך users (אין שימוש)
    assert "from .inventory import " not in files[users_fn]


def test_cycle_resolution_prefers_merging_non_canonical_module():
    code = """
# 1) USERS
def user_util(x: int) -> int:
    return x + 1
def bounce(y: int) -> int:
    # יוצר תלות ל-workflows
    return run(y)

\n# 2) WORKFLOWS
def run(z: int) -> int:
    return helper(z)

\n# (ללא סעיף) פונקציית עזר שלא תחת סעיף מוכר כדי להיווצר כ-helpers דומייני
def helper(v: int) -> int:
    # תלות חזרה ל-users ליצירת מחזור בן 3 מודולים
    return user_util(v)
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="cycle_case.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    # לאחר פירוק המחזור, אנו מצפים שמודולים קנוניים "users" ו-"workflows" ישרדו,
    # והמיזוג יעדיף את המודול הלא-קנוני (helpers) לתוך אחד מהם.
    module_files = [fn for fn in _module_files(files)]
    assert any(fn.endswith("users.py") for fn in module_files), f"Expected users.py to remain; got: {module_files}"
    assert any(fn.endswith("workflows.py") for fn in module_files), f"Expected workflows.py to remain; got: {module_files}"

from refactoring_engine import RefactoringEngine, RefactorType
import re


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


def test_smart_clustering_domain_files_and_independents():
    code = """
# 1) USERS
class User:
    def __init__(self, name: str):
        self.name = name

class UserManager:
    def add(self, user: User) -> bool:
        return True
    def ban(self, user: User) -> bool:
        return True

\n# 2) FINANCE
class SubscriptionManager:
    def subscribe(self, user: User) -> bool:
        return True
    def cancel(self, sub_id: str) -> bool:
        return True

\n# 3) INVENTORY
class Inventory:
    def count(self) -> int:
        return 0

\n# 4) API CLIENTS
class ApiClient:
    def get(self, url: str) -> str:
        return "ok"

\n# 5) WORKFLOWS
def run_workflow(u: User, api: ApiClient) -> bool:
    sm = SubscriptionManager()
    return sm.subscribe(u)
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="core_monolith.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    stems = set(_module_stems(files))
    # קבצים דומייניים נפרדים
    assert "users" in stems
    assert "finance" in stems
    assert "inventory" in stems
    assert "network" in stems  # api_clients → network.py
    assert "workflows" in stems
    # UserManager אמור להיות צמוד ל-User באותו מודול users.py
    users_fn = next(fn for fn in files if fn.endswith("users.py"))
    assert "class User" in files[users_fn]
    assert "class UserManager" in files[users_fn]
    # SubscriptionManager נשאר ב-finance.py (תלות חד-כיוונית ב-User)
    finance_fn = next(fn for fn in files if fn.endswith("finance.py"))
    assert "class SubscriptionManager" in files[finance_fn]
    # אין ייבוא הדדי users ↔ finance
    pat = re.compile(r"^\s*from\s+\.(\w+)\s+import\s+", re.M)
    edges = {}
    for fn in _module_files(files):
        stem = fn.rsplit(".", 1)[0].split("/")[-1]
        deps = set(m.group(1) for m in pat.finditer(files[fn]))
        edges[stem] = deps
    assert not ("users" in edges.get("finance", set()) and "finance" in edges.get("users", set()))

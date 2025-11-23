from refactoring_engine import RefactoringEngine, RefactorType


def _collect_model_modules(files_map):
    return sorted(
        fn
        for fn in files_map
        if fn.startswith("models/") and fn.endswith(".py")
    )


def test_models_safe_decomposition_domains_and_imports():
    code = """
class User:
    def __init__(self, name: str):
        self.name = name

class UserManager:
    def add(self, user: User) -> bool:
        return True

class PermissionSystem:
    def has(self, user: User) -> bool:
        return True

class EmailService:
    def send(self, user: User) -> None:
        pass

class Product:
    def __init__(self, sku: str):
        self.sku = sku

class Inventory:
    def count(self) -> int:
        return 0

class PaymentGateway:
    def charge(self, user: User) -> bool:
        return True

class SubscriptionManager:
    def activate(self, user: User) -> bool:
        return True
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="models.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    modules = _collect_model_modules(files)
    # קבצי דומיין בחבילת models/
    assert "models/core.py" in modules
    assert "models/inventory.py" in modules
    assert "models/billing.py" in modules
    assert "models/__init__.py" in files
    # billing מייבא מחלקות מליבה
    billing = files["models/billing.py"]
    assert "from .core import User" in billing
    # חשיפה ב-__init__ של models/
    init_content = files["models/__init__.py"]
    assert "from .core import *" in init_content
    assert "from .billing import *" in init_content
    assert "from .inventory import *" in init_content

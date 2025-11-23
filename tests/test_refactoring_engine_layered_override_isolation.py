from refactoring_engine import RefactoringEngine, RefactorType


def _module_files(files_map):
    return [
        fn
        for fn in files_map
        if fn.endswith(".py") and fn != "__init__.py" and not fn.endswith("_shared.py")
    ]


def test_layered_override_is_isolated_and_does_not_persist():
    code = """
# 1) USERS
class User:
    def __init__(self, name: str):
        self.name = name
def normalize(u: User) -> str:
    return u.name.strip().lower()

\n# 2) FINANCE
class SubscriptionManager:
    def bill(self, user: User) -> bool:
        return True
def bill(u: User) -> bool:
    return True
"""
    eng = RefactoringEngine()
    # קריאה ראשונה: שכבות מופעלות לפי-בקשה
    res1 = eng.propose_refactoring(code=code, filename="domainful.py", refactor_type=RefactorType.SPLIT_FUNCTIONS, layered_mode=True)
    assert res1.success and res1.proposal
    files1 = res1.proposal.new_files
    assert "models.py" in files1, "Expected models.py when layered_mode=True"
    # קריאה שנייה: ללא שכבות – לא אמור להישאר זכר ל-override הקודם
    res2 = eng.propose_refactoring(code=code, filename="domainful.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res2.success and res2.proposal
    files2 = res2.proposal.new_files
    module_files2 = [fn for fn in _module_files(files2)]
    assert "models.py" not in files2, f"layered override leaked into next call; got files: {module_files2}"

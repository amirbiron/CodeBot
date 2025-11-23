import re

from refactoring_engine import RefactoringEngine, RefactorType


def test_split_functions_avoids_circular_imports_by_merging():
    code = """
# 1) USERS
class User:
    def __init__(self, name: str):
        self.name = name
    def stats(self):
        # נקרא לפונקציית אנליטיקה המוגדרת בסקשן אחר
        return aggregate_user_stats(self)

\n# 2) ANALYTICS
def aggregate_user_stats(u: User):
    return {"name": u.name, "score": 1}
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="split_test_big_file.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is True
    assert res.proposal is not None
    files = res.proposal.new_files
    # קבצים שנוצרו (ללא __init__ ו-*_shared.py)
    module_files = [fn for fn in files if fn.endswith(".py") and fn != "__init__.py" and not fn.endswith("_shared.py")]
    # לא אמורות להיות שתי תלויות הדדיות בין שני קבצים שונים; אם הייתה – המיזוג אמור לבטל אחת מהן
    # בדיקה פשוטה: לא יופיעו בו־זמנית שני קבצים עם import הדדי
    edges = {}
    pat = re.compile(r"^\s*from\s+\.(\w+)\s+import\s+", re.M)
    stems = {fn.rsplit('.', 1)[0].split('/')[-1]: fn for fn in module_files}
    for stem, fn in stems.items():
        content = files[fn]
        deps = set(m.group(1) for m in pat.finditer(content))
        edges[stem] = deps
    # חפש זוגות הדדיים
    mutual_pairs = []
    for a in edges:
        for b in edges:
            if a == b:
                continue
            if b in edges[a] and a in edges[b]:
                mutual_pairs.append((a, b))
    # אין מעגלים הדדיים
    assert not mutual_pairs

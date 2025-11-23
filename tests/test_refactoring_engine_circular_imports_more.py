import re

from refactoring_engine import RefactoringEngine, RefactorType


def _module_stems(files_map):
    return [
        fn.rsplit(".", 1)[0].split("/")[-1]
        for fn in files_map
        if fn.endswith(".py") and fn != "__init__.py" and not fn.endswith("_shared.py")
    ]


def test_cycle_merge_cleans_self_import_and_updates_init_and_warning_and_marker():
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
    res = eng.propose_refactoring(
        code=code, filename="split_test_big_file.py", refactor_type=RefactorType.SPLIT_FUNCTIONS
    )
    assert res.success and res.proposal
    files = res.proposal.new_files
    # אחרי מיזוג מעגלי אמור להישאר מודול אחד (בנוסף ל-__init__ ואולי *_shared.py)
    module_files = [
        fn for fn in files if fn.endswith(".py") and fn != "__init__.py" and not fn.endswith("_shared.py")
    ]
    assert len(module_files) == 1
    merged_fn = module_files[0]
    merged_stem = merged_fn.rsplit(".", 1)[0].split("/")[-1]
    merged_content = files[merged_fn]
    # אין self-import: from .<merged_stem> import ...
    assert re.search(rf"^\s*from\s+\.{re.escape(merged_stem)}\s+import\s+", merged_content, re.M) is None
    # יש סימון של קוד שמוזג מקובץ אחר
    assert "# ---- merged from split_test_big_file_" in merged_content
    # __init__.py מעודכן רק למודולים הקיימים
    init = files.get("__init__.py", "")
    assert f"from .{merged_stem} import *" in init
    assert "users" in merged_content or "analytics" in merged_content
    # אזהרת פירוק מעגליות קיימת
    assert any("פורקה תלות מעגלית" in w for w in (res.proposal.warnings or []))


def test_no_cycle_keeps_modules_and_no_warning():
    code = """
# 1) USERS
class User:
    def __init__(self, name: str):
        self.name = name
    def id(self):
        return self.name

\n# 2) ANALYTICS
def aggregate_user_stats(name: str):
    return {"name": name, "score": 1}
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(
        code=code, filename="split_nocycle.py", refactor_type=RefactorType.SPLIT_FUNCTIONS
    )
    assert res.success and res.proposal
    files = res.proposal.new_files
    module_stems = _module_stems(files)
    # אין תלות הדדית ולכן שני המודולים נשמרים (או יותר, אבל לא אחד בודד בגלל merge מחזורי)
    assert len(module_stems) >= 2
    # אין אזהרת מעגליות
    assert not any("פורקה תלות מעגלית" in w for w in (res.proposal.warnings or []))

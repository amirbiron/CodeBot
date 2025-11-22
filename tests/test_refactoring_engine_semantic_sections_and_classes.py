from refactoring_engine import RefactoringEngine, RefactorType


def test_section_based_grouping_splits_similar_names():
    code = """
#############################
# 2) PAYMENTS + SUBSCRIPTIONS
#############################

def calculate_vat(amount):
    return round(amount * 0.17, 2)

#############################
# 6) ANALYTICS / REPORTS
#############################

def calculate_engagement(visits, likes):
    if visits == 0:
        return 0
    return round((likes / visits) * 100, 2)
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="mega.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    # מצא את הקבצים שמכילים את שתי הפונקציות
    containing_vat = None
    containing_eng = None
    for fn, content in files.items():
        if "def calculate_vat" in content:
            containing_vat = fn
        if "def calculate_engagement" in content:
            containing_eng = fn
    assert containing_vat is not None and containing_eng is not None
    # אמור להיות פיצול לקבצים שונים (קוהזיה לפי Section)
    assert containing_vat != containing_eng


def test_classes_collocated_with_functions_no_generic_classes_file():
    code = """
#############################
# 1) USER MANAGEMENT
#############################

class User:
    def __init__(self, name):
        self.name = name

#############################
# 9) WORKFLOW / PIPELINES
#############################

def load_users_fake_db():
    return [User("Amir")]

#############################
# 6) ANALYTICS / REPORTS
#############################

def calculate_dummy(x):
    return x
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="mega.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    files = res.proposal.new_files
    # אין קובץ מחלקות גנרי
    assert "mega_classes.py" not in files
    # המחלקה User והפונקציה load_users_fake_db צריכות להיות באותו קובץ (Collocation)
    same_file_contains_both = False
    for fn, content in files.items():
        if "class User" in content and "def load_users_fake_db" in content:
            same_file_contains_both = True
            break
    assert same_file_contains_both
    # ואין ייבוא מהקובץ הגנרי
    combined = "\n".join(files.values())
    assert "from .mega_classes import User" not in combined


def test_unsectioned_helpers_preserved_alongside_sections():
    code = """
def slugify(text):
    return text.lower().replace(" ", "-")

#############################
# 6) ANALYTICS / REPORTS
#############################

def generate_report_json(stats):
    import json
    return json.dumps({"s": stats})
"""
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="mix.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success and res.proposal
    combined = "\n".join(res.proposal.new_files.values())
    assert "def slugify" in combined  # לא נעלם
    assert "def generate_report_json" in combined


from refactoring_engine import RefactoringEngine, RefactorType


def _make_functions(prefix: str, count: int) -> str:
    parts = []
    for i in range(count):
        parts.append(f"def {prefix}_{i}():\n    return {i}\n")
    return "\n".join(parts)


def test_convert_to_classes_many_same_domain_produces_single_class():
    # 14 פונקציות באותו דומיין/ prefix — מצופה מחלקה אחת (לא 14 קבצים)
    code = _make_functions("calc", 14)
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="big_calc.py", refactor_type=RefactorType.CONVERT_TO_CLASSES)
    assert res.success is True
    assert res.proposal is not None
    # מחלקה אחת בלבד
    assert len(res.proposal.new_files) == 1
    the_file = next(iter(res.proposal.new_files.keys()))
    assert the_file.endswith("_service.py")


def test_convert_to_classes_domain_grouping_creates_3_to_5_classes():
    # פונקציות IO
    io = [
        "def load_user():\n    return {}\n",
        "def save_user(u=None):\n    return True\n",
        "def read_config():\n    return {}\n",
        "def write_config(c=None):\n    return True\n",
        "def fetch_data():\n    return []\n",
    ]
    # פונקציות Helpers
    helpers = [
        "def parse_row(r=None):\n    return r\n",
        "def format_user(u=None):\n    return str(u)\n",
        "def normalize_name(n=''):\n    return (n or '').strip().lower()\n",
    ]
    # פונקציות Compute
    compute = [
        "def compute_score(x=0, y=0):\n    return x + y\n",
        "def compute_rank(s=0):\n    return int(s // 10)\n",
        "def calculate_stats(xs=None):\n    return len(xs or [])\n",
    ]
    code = "\n\n".join(io + helpers + compute)
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="domainful.py", refactor_type=RefactorType.CONVERT_TO_CLASSES)
    assert res.success is True
    assert res.proposal is not None
    # מצפים ל-3–5 מחלקות (IO/Helpers/Compute, ייתכן פיצול משנה)
    n_classes = len(res.proposal.new_files)
    assert 3 <= n_classes <= 5


def test_split_functions_limits_module_count_by_domain():
    # מקרה פיצול: נוודא שהמספר לא שווה למספר הפונקציות, אלא 3–5 מודולים משמעותיים
    io = _make_functions("load", 3) + "\n" + _make_functions("save", 2)
    helpers = _make_functions("format", 2) + "\n" + _make_functions("parse", 2)
    compute = _make_functions("compute", 3)
    code = "\n\n".join([io, helpers, compute])
    eng = RefactoringEngine()
    res = eng.propose_refactoring(code=code, filename="split_domain.py", refactor_type=RefactorType.SPLIT_FUNCTIONS)
    assert res.success is True
    assert res.proposal is not None
    # ספירה רק של מודולי פונקציות (ללא __init__ ו-*_shared.py)
    module_files = [fn for fn in res.proposal.new_files.keys() if fn.endswith(".py") and fn != "__init__.py" and not fn.endswith("_shared.py")]
    # מספר מודולים בתחום 3–5
    assert 3 <= len(module_files) <= 5

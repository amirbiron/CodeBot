"""שומר מבני: פונקציה בקוד הייצור שכותבת לא קוראת קודם דרך קאש.

**הכלל:** מסלול שכותב קורא טרי. הגטר המקוּש הוא לתצוגה.

``Repository.get_latest_version`` מעוטרת ב-``@cached``, והוובאפ כותב למסד בחיבור משלו — וכמה ממסלוליו אינם מבטלים את הקאש. לכן, לאורך חלון הקאש אחרי שמישהו קרא קובץ בבוט, הגטר מחזיר את הגרסה שהייתה, גם אם הקובץ כבר השתנה. מסלול שמעתיק ממנה שדה לגרסה חדשה — גוף הקוד, תיאור, תגיות — מחזיר בשקט את מה שהשתנה, ומסלול שמחליט לפיה ("השם תפוס") מחליט לפי מצב שכבר אינו קיים. זה קרה ב-#3229 (מספר הגרסה וגוף הקובץ ב-MCP) וב-#3459 (תיאור, תגיות ומועדף ב-``Repository.save_file``), ובכל פעם תוקנו הקוראים שנמצאו ולא המחלקה. הדפוס המלא: ``bugbot-rules/write-from-cached-read.md`` ב-amir-bug-patterns.

**מה נבדק.** כל פונקציה בקוד הייצור (לא ``tests/``, לא ``docs/``, ולא קבצי pytest בשורש) שיש בה גם קריאה מקוּשה וגם כתיבה, כשהקריאה המקוּשה קודמת בקוד לכתיבה האחרונה — לפי המיקום ולא רק לפי מספר השורה, כך שגם קריאה בתוך הארגומנטים של הכתיבה עצמה נספרת:

- **קריאה מקוּשה** — קריאה לפונקציה ששמה הוא שם של פונקציה מעוטרת ב-``@cached`` או ``@async_cached`` של ``cache_manager``. הרשימה נאספת מהקוד בכל ריצה ולא מוקלדת כאן, כדי שגטר מקוּש חדש ייכנס לבד. גם שם שמגיע כמחרוזת נספר — ``_call_files_api("get_latest_version", ...)`` בבוט קורא לאותה מתודה בדיוק, ושומר שמחפש רק ``.get_latest_version(`` לא ראה את מסלול עריכת ההערה שרץ בפועל (``conversation_handlers.receive_new_code``).
- **ותוכן שנקרא מ-``context.user_data['files_cache']``.** זו רשימת התצוגה של הבוט, ואין לה TTL בכלל. מותר לזהות דרכה את הקובץ (``file_name``, ``_id``) ולבדוק שהרשומה קיימת — אסור להעתיק ממנה שדה, או להעביר אותה שלמה הלאה, לפני כתיבה. התוכן נקרא מהמסד.
- **כתיבה** — ``WRITE_CALLS``, ישירות או כמחרוזת.

**מה עובר.** קריאה **אחרי** הכתיבה האחרונה — readback לדיווח על מה שנשמר, והשמירה עצמה ביטלה את הקאש. פונקציה ששמה הוא שם של גטר מקוּש — ההגדרה עצמה וההאצלות באותו שם ב-``DatabaseManager`` וב-``FilesFacade``.

**מגבלה ידועה, בכוונה:** השומר רואה פונקציה אחת. החלטה שנקראת בפונקציה אחת ונכתבת באחרת — ``save_flow.get_filename`` ששואל "קיים?" ומציג תפריט, או זרימת הרפקטור שקוראת את הקובץ לפני ההצעה ושומרת אחרי האישור — לא נתפסת.

הדגם: השומר המבני של ירושת המועדף מ-#3459 (``tests/test_mcp_description_age.py``). הבדיקות ההתנהגותיות שמטעינות את הקאש עצמו: ``tests/test_bot_writers_read_fresh_state.py``.
"""

from __future__ import annotations

import ast
import functools
import os
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Iterator, List, Optional, Set, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: תיקיות שאינן קוד ייצור, בכל עומק — לפי שם התיקייה, לא לפי קידומת של נתיב.
NOT_PRODUCTION_DIRS = frozenset({"tests", "docs", ".git", "node_modules", ".venv", "venv", "__pycache__"})

#: הדקורטורים של ``cache_manager`` שמגישים תוצאה מהקאש.
CACHE_DECORATORS = frozenset({"cached", "async_cached"})

#: הכתיבות. קריאה בשם הזה — ישירה, או כמחרוזת ל-dispatcher כמו ``_call_files_api``.
WRITE_CALLS = frozenset({
    "save_code_snippet", "save_file", "insert_one", "insert_many", "update_one",
    "update_many", "replace_one", "find_one_and_update", "delete_one", "delete_many",
    "rename_file",
})

#: מה מותר לקרוא מרשומה של ``files_cache`` לפני כתיבה: מי הקובץ, לא מה יש בו.
FILES_CACHE_IDENTITY = frozenset({"file_name", "_id"})

FILES_CACHE_KEY = "files_cache"

HOW_TO_FIX = (
    "מסלול שכותב קורא טרי, והגטר המקוּש הוא לתצוגה: get_latest_version_fresh / get_user_files_fresh "
    "(ב-FilesFacade וב-DatabaseManager), _fetch_latest_version / _fetch_user_files (ב-Repository), "
    "_latest_fresh (ב-MCP). מ-files_cache מזהים את הקובץ (file_name) — את התוכן קוראים מהמסד."
)


@dataclass(frozen=True)
class Violation:
    path: str
    function: str
    function_line: int
    read: str
    read_line: int
    write: str
    write_line: int

    def describe(self) -> str:
        return (
            f"{self.path}:{self.function_line} {self.function}() — קריאה מקוּשה ({self.read}) בשורה "
            f"{self.read_line}, כתיבה ({self.write}) בשורה {self.write_line}."
        )


def _production_files() -> Iterator[Path]:
    """קבצי הפייתון של הייצור. תיקייה שאינה ייצור לא נפתחת בכלל, כך ש-``node_modules`` אינו נסרק.

    הגיזום הוא השמה לתוך ``subdirectories[:]``: ``os.walk`` (topdown, ברירת המחדל) יורד רק לתיקיות
    שנשארו ברשימה — ה-docstring של ``os.walk`` ב-Python 3.11 וב-3.12, שעליהן רץ ה-CI.
    """
    for directory, subdirectories, files in os.walk(REPO_ROOT):
        subdirectories[:] = sorted(d for d in subdirectories if d not in NOT_PRODUCTION_DIRS)
        for name in sorted(files):
            if name.endswith(".py") and name != "conftest.py" and not name.startswith("test_"):
                yield Path(directory) / name


@functools.lru_cache(maxsize=1)
def _production_trees() -> Tuple[Tuple[str, ast.Module], ...]:
    """כל קובץ ייצור, מפורסר. נקרא מתוך הטסטים ולא בזמן ייבוא המודול."""
    trees = []
    for path in _production_files():
        source = path.read_text(encoding="utf-8")
        trees.append((path.relative_to(REPO_ROOT).as_posix(), ast.parse(source, filename=str(path))))
    return tuple(trees)


def _decorator_name(decorator: ast.expr) -> Optional[str]:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def cached_function_names(trees) -> FrozenSet[str]:
    """שמות הפונקציות שמעוטרות ב-``@cached`` / ``@async_cached`` בקוד הייצור."""
    names: Set[str] = set()
    for _, tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                _decorator_name(d) in CACHE_DECORATORS for d in node.decorator_list
            ):
                names.add(node.name)
    return frozenset(names)


Position = Tuple[int, int]


@dataclass(frozen=True)
class _Call:
    """קריאה בפונקציה. ``end`` הוא סוף הביטוי: כתיבה קורית אחרי שהארגומנטים שלה חושבו."""

    start: Position
    end: Position
    name: str


def _calls(function: ast.AST) -> Iterator[_Call]:
    """כל קריאה בפונקציה — כולל פונקציות מקוננות בתוכה, שרצות כחלק ממנה.

    השם הוא שם הפונקציה הנקראת, וגם כל מחרוזת שמועברת לה כארגומנט: ``_call_files_api("save_file", ...)``
    הוא קריאה ל-``save_file``.
    """
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        start = (node.lineno, node.col_offset)
        end = (node.end_lineno or node.lineno, node.end_col_offset or node.col_offset)
        func = node.func
        if isinstance(func, ast.Attribute):
            yield _Call(start, end, func.attr)
        elif isinstance(func, ast.Name):
            yield _Call(start, end, func.id)
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                yield _Call(start, end, arg.value)


def _constant_str(node: Optional[ast.AST]) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_files_cache(node: ast.AST, containers: Set[str]) -> bool:
    """``context.user_data['files_cache']``, ``.get('files_cache', ...)``, או שם שהוחזק בהם."""
    if isinstance(node, ast.Name):
        return node.id in containers
    if isinstance(node, ast.Subscript):
        return _constant_str(node.slice) == FILES_CACHE_KEY
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return bool(node.args) and _constant_str(node.args[0]) == FILES_CACHE_KEY
    if isinstance(node, ast.BoolOp):
        return any(_is_files_cache(value, containers) for value in node.values)
    return False


def _is_files_cache_entry(node: ast.AST, containers: Set[str], entries: Set[str]) -> bool:
    """רשומה אחת מתוך ``files_cache`` — ``files_cache[i]``, ``files_cache.get(i)``, או שם שהוחזק בהן."""
    if isinstance(node, ast.Name):
        return node.id in entries
    if isinstance(node, ast.Subscript):
        return _is_files_cache(node.value, containers)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return _is_files_cache(node.func.value, containers)
    if isinstance(node, ast.BoolOp):
        return any(_is_files_cache_entry(value, containers, entries) for value in node.values)
    return False


def files_cache_bindings(function: ast.AST) -> Tuple[Set[str], Set[str]]:
    """השמות בפונקציה שמחזיקים את ``files_cache`` עצמו, ואלה שמחזיקים רשומה ממנו."""
    assignments = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assignments.append((node.targets[0].id, node.value))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            assignments.append((node.target.id, node.value))
    containers: Set[str] = set()
    entries: Set[str] = set()
    changed = True
    while changed:  # עד נקודת שבת: שם יכול להיקשר לשם אחר שנקשר בשורה מאוחרת יותר בקוד
        changed = False
        for name, value in assignments:
            if name not in containers and _is_files_cache(value, containers):
                containers.add(name)
                changed = True
            elif name not in entries and _is_files_cache_entry(value, containers, entries):
                entries.add(name)
                changed = True
    return containers, entries


def _uses_content(entry: ast.AST, parents: dict) -> bool:
    """האם הביטוי הזה — רשומה של ``files_cache`` — משמש כאן את **התוכן** שלה.

    תוכן: שדה שאינו זהות הקובץ, או הרשומה כולה שעוברת הלאה — לפונקציה, ל-``dict(...)``, ל-``**``,
    לאחסון במקום אחר. לא תוכן: ``file_name`` / ``_id``, בדיקת קיום (``not``, ``if``, ``is None``,
    ``isinstance``), כתיבה לתוך הרשומה, וכינוי שלה בשם אחר — שנעקב בעצמו ב-``files_cache_bindings``.
    """
    if isinstance(entry, (ast.Name, ast.Subscript)) and not isinstance(entry.ctx, ast.Load):
        return False
    parent = parents.get(entry)
    if isinstance(parent, ast.Attribute) and parent.value is entry:
        call = parents.get(parent)
        if parent.attr == "get" and isinstance(call, ast.Call) and call.func is parent:
            return (_constant_str(call.args[0]) if call.args else None) not in FILES_CACHE_IDENTITY
        return True
    if isinstance(parent, ast.Subscript) and parent.value is entry:
        if not isinstance(parent.ctx, ast.Load):
            return False
        return _constant_str(parent.slice) not in FILES_CACHE_IDENTITY
    if isinstance(parent, (ast.Assign, ast.AnnAssign)) and parent.value is entry:
        targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
        return not all(isinstance(target, ast.Name) for target in targets)
    if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
        return False
    if isinstance(parent, (ast.If, ast.While, ast.IfExp)) and parent.test is entry:
        return False
    if isinstance(parent, ast.BoolOp):
        return False
    if isinstance(parent, ast.Compare) and all(isinstance(op, (ast.Is, ast.IsNot)) for op in parent.ops):
        return False
    if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id == "isinstance":
        return False
    return True


def files_cache_content_reads(function: ast.AST) -> List[Position]:
    """המקומות שבהם הפונקציה משתמשת בתוכן של רשומה מ-``files_cache`` — ראו ``_uses_content``."""
    containers, entries = files_cache_bindings(function)
    parents = {child: node for node in ast.walk(function) for child in ast.iter_child_nodes(node)}
    return [
        (node.lineno, node.col_offset)
        for node in ast.walk(function)
        # רשומה היא תמיד ביטוי (שם, אינדקס, ``.get``), ורק לביטוי יש מיקום בקוד.
        if isinstance(node, ast.expr)
        and _is_files_cache_entry(node, containers, entries)
        and _uses_content(node, parents)
    ]


def violations_in(tree: ast.AST, cached: FrozenSet[str], path: str = "<source>") -> List[Violation]:
    """פונקציות שקוראות דרך קאש **לפני** הכתיבה האחרונה שלהן.

    "לפני" לפי המקום בקוד: קריאה שמתחילה לפני שהכתיבה האחרונה מסתיימת — כולל קריאה בתוך הארגומנטים של
    הכתיבה עצמה, שמחושבים לפניה. קריאה שמתחילה אחרי שהיא נגמרה היא readback.
    """
    found = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or function.name in cached:
            continue
        calls = list(_calls(function))
        writes = [call for call in calls if call.name in WRITE_CALLS]
        if not writes:
            continue
        last_write = max(writes, key=lambda call: call.end)
        reads = [(call.start, call.name) for call in calls if call.name in cached]
        reads += [(position, f"{FILES_CACHE_KEY}[...]") for position in files_cache_content_reads(function)]
        early = [read for read in reads if read[0] < last_write.end]
        if early:
            (read_line, _), read = min(early)
            found.append(Violation(
                path, function.name, function.lineno, read, read_line, last_write.name, last_write.start[0]))
    return found


def test_no_production_function_writes_after_reading_through_a_cache():
    trees = _production_trees()
    cached = cached_function_names(trees)
    found = [violation for path, tree in trees for violation in violations_in(tree, cached, path)]
    assert not found, (
        f"פונקציות שקוראות דרך קאש ואחר כך כותבות: {len(found)}\n"
        + "\n".join("  " + violation.describe() for violation in found)
        + "\n" + HOW_TO_FIX
    )


def test_the_scan_sees_the_cached_getters_and_the_bot_paths():
    """בלי זה, סריקה שלא מצאה כלום — נתיב שזז, דקורטור ששמו השתנה — הייתה עוברת ירוקה."""
    trees = _production_trees()
    scanned = {path for path, _ in trees}
    for path in (
        "conversation_handlers.py",
        "handlers/file_view.py",
        "database/repository.py",
        "database/manager.py",
        "mcp_server/backend.py",
        "github_menu_handler.py",
        "file_manager.py",
    ):
        assert path in scanned, f"{path} לא נסרק — השומר לא רואה את אחד מהמסלולים שהוא נכתב בשבילם"
    assert not any(Path(path).parts[0] == "tests" for path in scanned)

    cached = cached_function_names(trees)
    assert {"get_latest_version", "get_user_files"} <= cached, sorted(cached)

    file_view = dict(trees)["handlers/file_view.py"]
    assert any(
        files_cache_bindings(node)[1]
        for node in ast.walk(file_view)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ), "אף פונקציה ב-handlers/file_view.py לא מחזיקה רשומה של files_cache — המפתח השתנה, והשומר עיוור לו"


#: גבולות הכלל, כקוד שאפשר להריץ: (מקור, האם זו הפרה).
RULE_CASES = [
    pytest.param(
        "def f(db):\n    doc = db.get_latest_version(1, 'a')\n    db.save_code_snippet(code=doc['code'])\n",
        True, id="cached-read-then-write",
    ),
    pytest.param(
        "def f(db):\n    db.save_file(1, 'a', 'x', 'py')\n    return db.get_latest_version(1, 'a')\n",
        False, id="readback-after-the-write",
    ),
    pytest.param(
        "def f(db):\n    doc = db.get_latest_version_fresh(1, 'a')\n    db.save_code_snippet(code=doc['code'])\n",
        False, id="fresh-read-then-write",
    ),
    pytest.param(
        "def f(db):\n    db.save_code_snippet(code=db.get_latest_version(1, 'a')['code'])\n",
        True, id="cached-read-inside-the-arguments-of-the-write",
    ),
    pytest.param(
        "def f(db):\n    return db.save_file(1, 'a', 'x', 'py') and db.get_latest_version(1, 'a')\n",
        False, id="readback-on-the-same-line",
    ),
    pytest.param(
        "def f():\n    doc = _call_files_api('get_latest_version', 1, 'a')\n    _call_files_api('save_file', 1, 'a', doc['code'], 'py')\n",
        True, id="read-and-write-dispatched-by-name",
    ),
    pytest.param(
        "def f(db):\n    def pick(name):\n        return db.get_latest_version(1, name)\n    pick('a')\n    db.save_file(1, 'a', 'x', 'py')\n",
        True, id="cached-read-in-a-nested-function",
    ),
    pytest.param(
        "def f(context, db, i):\n    files_cache = context.user_data.get('files_cache', {})\n    entry = files_cache.get(i)\n"
        "    db.save_code_snippet(code=entry.get('code'))\n",
        True, id="files-cache-content",
    ),
    pytest.param(
        "def f(context, db, i):\n    entry = context.user_data['files_cache'][i]\n    db.save_code_snippet(tags=entry['tags'])\n",
        True, id="files-cache-content-by-subscript",
    ),
    pytest.param(
        "def f(context, db, i):\n    files_cache = context.user_data.get('files_cache', {})\n    entry = files_cache.get(i)\n"
        "    if not entry:\n        return\n    doc = db.get_latest_version_fresh(1, entry.get('file_name'))\n"
        "    db.save_code_snippet(code=doc['code'])\n",
        False, id="files-cache-identifies-the-file-only",
    ),
    pytest.param(
        "def f(context, db, i):\n    entry = context.user_data.get('files_cache', {}).get(i)\n"
        "    code, language = fields(entry)\n    db.save_code_snippet(code=code, programming_language=language)\n",
        True, id="files-cache-entry-handed-whole-to-a-helper",
    ),
    pytest.param(
        "def f(context, db, i):\n    entry = context.user_data.get('files_cache', {}).get(i) or {}\n"
        "    if not isinstance(entry, dict) or entry is None:\n        return\n"
        "    doc = db.get_latest_version_fresh(1, entry['file_name'])\n    db.save_code_snippet(code=doc['code'])\n",
        False, id="files-cache-entry-only-checked-and-identified",
    ),
    pytest.param(
        "def f(context, db, i):\n    db.save_file(1, 'a', 'x', 'py')\n    files_cache = context.user_data.get('files_cache')\n"
        "    files_cache[i]['code'] = 'x'\n    return files_cache[i].get('version')\n",
        False, id="files-cache-refreshed-after-the-write",
    ),
    pytest.param(
        "class Repo:\n    def get_latest_version(self, user_id, name):\n        doc = self._fetch(user_id, name)\n"
        "        self.collection.update_one({}, {})\n        return self.get_latest_version(user_id, name)\n",
        False, id="the-cached-getter-itself-is-skipped",
    ),
]


@pytest.mark.parametrize("source, is_violation", RULE_CASES)
def test_the_rule_flags_a_cached_read_before_a_write_and_nothing_else(source, is_violation):
    found = violations_in(ast.parse(source), frozenset({"get_latest_version"}))
    assert bool(found) is is_violation, [violation.describe() for violation in found]

"""כותב אחד לאוסף ``note_threads``: המודול המשותף ``note_threads.py``.

לאוסף שני כותבים — שירות ה-MCP, והוובאפ. השדות הנגזרים במסמך (``status``,
``last_author_kind``, ``last_at``, ``comment_count``, ``body_bytes``) נכונים רק כל עוד כל
כתיבה מעדכנת אותם יחד, באותה פעולה — וזה נכון רק כל עוד כל כתיבה עוברת בפונקציות של
המודול. כותב שני שדוחף תגובה ישירות היה משאיר מונה ישן, סטטוס שלא נפתח, או שרשור שעבר
את התקרה (``bugbot-rules/derived-field-added-to-one-writer.md``).

**הסריקה היא על ה-AST** של כל קובץ פייתון בריפו, חוץ מ-``tests/`` (טסטים מכינים נתונים
ישירות) ומהמודול עצמו. כתיבה היא קריאה לאחת ממתודות הכתיבה של pymongo על ביטוי שמגיע
לאוסף: ``db["note_threads"]``, ``db.note_threads``, ``db[NOTE_THREADS_COLLECTION]``,
``self._threads_coll()`` — או על שם שהוצב מאחד מהם באותה פונקציה. העברת האוסף לפונקציה של
המודול (``note_threads.add_comment(coll, ...)``) אינה כתיבה כאן, ובשביל זה בדיוק היא קיימת.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "note_threads.py"

_WRITES = frozenset({
    "insert_one", "insert_many", "update_one", "update_many", "replace_one", "delete_one",
    "delete_many", "find_one_and_update", "find_one_and_replace", "find_one_and_delete",
    "bulk_write", "drop",
})
_SKIP_DIRS = frozenset({"tests", ".git", "node_modules", "venv", ".venv", "site-packages", "__pycache__"})


def _python_files() -> Iterator[Path]:
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts) or path == OWNER:
            continue
        yield path


def _reaches_threads(node: ast.AST) -> bool:
    """האם הביטוי הוא האוסף: מנוי במחרוזת/בקבוע, מאפיין, או המשיג של ה-backend."""
    if isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, ast.Constant) and key.value == "note_threads":
            return True
        if isinstance(key, ast.Name) and key.id == "NOTE_THREADS_COLLECTION":
            return True
        if isinstance(key, ast.Attribute) and key.attr == "NOTE_THREADS_COLLECTION":
            return True
    if isinstance(node, ast.Attribute) and node.attr == "note_threads":
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "_threads_coll":
        return True
    return False


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _own_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """הצמתים של ``scope`` **בלי** פונקציות מקוננות — לכל פונקציה הכינויים שלה."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _FUNCTIONS):
            stack.extend(ast.iter_child_nodes(node))


def _offences(source: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    tree = ast.parse(source)
    scopes = [tree, *(n for n in ast.walk(tree) if isinstance(n, _FUNCTIONS))]
    for scope in scopes:
        nodes = list(_own_nodes(scope))
        aliases = {
            target.id
            for node in nodes if isinstance(node, ast.Assign) and _reaches_threads(node.value)
            for target in node.targets if isinstance(target, ast.Name)
        }
        for node in nodes:
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in _WRITES:
                continue
            receiver = node.func.value
            if _reaches_threads(receiver) or (isinstance(receiver, ast.Name) and receiver.id in aliases):
                found.append((node.lineno, node.func.attr))
    return sorted(set(found))


def test_only_the_shared_module_writes_to_note_threads():
    offences = [
        f"{path.relative_to(ROOT)}:{line}: {method}"
        for path in _python_files()
        for line, method in _offences(path.read_text(encoding="utf-8"))
    ]
    assert not offences, (
        "כתיבה ל-note_threads מחוץ ל-note_threads.py — עברו דרך הפונקציות של המודול "
        f"(create_thread / add_comment / resolve_thread / reopen_thread / delete_note_threads): {offences}"
    )


def test_the_scan_sees_every_shape_of_a_direct_write():
    """הסורק עצמו: כל צורה של כתיבה ישירה נתפסת, והעברה למודול — לא."""
    caught = _offences(
        "def a(db):\n    db['note_threads'].insert_one({})\n"
        "def b(db):\n    db.note_threads.update_one({}, {})\n"
        "def c(db):\n    db[NOTE_THREADS_COLLECTION].delete_many({})\n"
        "def d(self):\n    coll = self._threads_coll()\n    coll.find_one_and_update({}, {})\n"
        "def e(db):\n    db[note_threads.NOTE_THREADS_COLLECTION].replace_one({}, {})\n"
    )
    assert [method for _, method in caught] == [
        "insert_one", "update_one", "delete_many", "find_one_and_update", "replace_one",
    ]
    assert _offences(
        "def f(self):\n    coll = self._threads_coll()\n    return note_threads.add_comment(coll, user_id=1)\n"
        "def g(db):\n    return db['note_threads'].find_one({})\n"
    ) == []

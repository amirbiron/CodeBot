#!/usr/bin/env python3
"""ניתוח הפער בין משתני הסביבה שנצרכים בקוד לבין אלה שמוצהרים ב-Config Inspector.

הרקע: ``services/config_inspector_service.py`` מחזיק טבלה של ``ConfigDefinition``
שממנה נבנים שני עמודי ה-Config Inspector. הטבלה הזו נכתבת ביד, ולכן היא נסחפת:
מישהו מוסיף ``os.getenv`` ולא מצהיר עליו, והמשתנה חי בפרודקשן בלי שאפשר לראות
אותו בשום מקום. הסקריפט הזה מודד את הפער, וגם משמש כמקור ל-
``tests/test_config_definitions_coverage.py``.

**הסקריפט מציע, הוא לא פוסק.** השיוך לשירותים נגזר מסגור ה-import מכל נקודת
כניסה, ויש לו שני כיווני טעות מוכחים:

- *false positive* — קובץ יושב בסגור אבל הייבוא אליו מותנה בדגל שכבוי כברירת מחדל
  (``services/webserver.py`` נטען מ-``main.py`` רק כש-``ENABLE_INTERNAL_SHARE_WEB`` דלוק).
- *false negative* — קובץ מיובא רק בתוך גוף פונקציה, ולכן אינו בסגור ה"ודאי",
  אבל הפונקציה נקראת בעליית התהליך (``SentryPoller.from_env`` ב-``main.py``).

לכן הפלט מפריד בין סגור **ודאי** (ייבוא ברמת המודול בלבד) לסגור **רופף** (כולל
ייבוא בתוך פונקציות), ומצרף לכל משתנה את הקבצים שצורכים אותו — כדי שההחלטה
תתקבל מול הראיה ולא מול מספר.

שימוש::

    python scripts/audit_config_definitions.py              # דוח קריא
    python scripts/audit_config_definitions.py --json       # פלט JSON
    python scripts/audit_config_definitions.py --keys-only  # שמות בלבד, שורה לשורה
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

#: הקובץ שמחזיק את טבלת ההצהרות.
DEFINITIONS_FILE = REPO_ROOT / "services" / "config_inspector_service.py"

#: רפרנס משתני הסביבה — משמש רק כדי לסמן למי כבר יש תיאור כתוב.
ENV_DOC_FILE = REPO_ROOT / "docs" / "environment-variables.rst"

#: תיקיות שאינן קוד המוצר.
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "_build",
    "site-packages",
    "__pycache__",
    "tests",
}

#: נקודות הכניסה של שירותי Render, ומהן נגזר סגור ה-import.
ENTRY_POINTS: Dict[str, str] = {
    "bot": "main.py",
    "webapp": "webapp/app.py",
    "mcp": "mcp_server/app.py",
    "webserver": "services/webserver.py",
}

#: שם משתנה סביבה סביר. מסנן מחרוזות אקראיות שנשלחות ל-``os.getenv``.
ENV_NAME_RE = re.compile(r"[A-Z][A-Z0-9_]{2,}")

#: מופע ``VAR`` בתוך התיעוד — כך מזוהה משתנה שכבר יש לו תיאור כתוב.
DOC_MENTION_RE = re.compile(r"``([A-Z][A-Z0-9_]{2,})``")

#: שורת פתיחה של רשומה בטבלת התיעוד. התיעוד מתעד לעיתים כמה שמות באותה שורה
#: (``A`` / ``B``), ולכן נאספים כל השמות שבשורה ולא רק הראשון.
DOC_ROW_RE = re.compile(r"^\s*\*\s+-\s+((?:``[A-Z][A-Z0-9_]{2,}``[\s/,]*)+)$", re.MULTILINE)

#: שם חלופי שמתועד בתוך התיאור של המשתנה הראשי, במקום בשורה משלו.
DOC_ALIAS_RE = re.compile(r"(?:Alias נתמך|שם חלופי נתמך)[^\n]*?``([A-Z][A-Z0-9_]{2,})``")


def iter_python_files() -> Iterable[Path]:
    """כל קובצי הפייתון של המוצר, בלי טסטים ובלי תלויות חיצוניות."""
    for path in sorted(REPO_ROOT.rglob("*.py")):
        rel_parts = set(path.relative_to(REPO_ROOT).parts)
        if rel_parts & EXCLUDED_DIRS:
            continue
        yield path


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


# --------------------------------------------------------------------------
# 1. מה מוצהר
# --------------------------------------------------------------------------

def collect_declared() -> Set[str]:
    """שמות המשתנים שמוצהרים ב-``CONFIG_DEFINITIONS``."""
    tree = _parse(DEFINITIONS_FILE)
    if tree is None:
        raise RuntimeError(f"Cannot parse {DEFINITIONS_FILE}")

    declared: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "ConfigDefinition":
            continue
        for keyword in node.keywords:
            if keyword.arg == "key" and isinstance(keyword.value, ast.Constant):
                declared.add(str(keyword.value.value))
    return declared


# --------------------------------------------------------------------------
# 2. מה נצרך
# --------------------------------------------------------------------------

def _env_read_from_call(node: ast.Call) -> Tuple[str | None, Any, bool]:
    """מזהה ``os.getenv("X"[, default])`` ו-``os.environ.get("X"[, default])``."""
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in {"getenv", "get"}:
        return None, None, False

    base = func.value
    is_os_env = (isinstance(base, ast.Name) and base.id == "os") or (
        isinstance(base, ast.Attribute) and base.attr == "environ"
    )
    if not is_os_env or not node.args:
        return None, None, False

    first = node.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return None, None, False

    if len(node.args) < 2:
        return first.value, None, False

    second = node.args[1]
    default = second.value if isinstance(second, ast.Constant) else "<expr>"
    return first.value, default, True


def _env_read_from_subscript(node: ast.Subscript) -> str | None:
    """מזהה ``os.environ["X"]``."""
    value = node.value
    if not (isinstance(value, ast.Attribute) and value.attr == "environ"):
        return None
    key = node.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value
    return None


def _pydantic_settings_fields(tree: ast.Module) -> Set[str]:
    """שמות שדות של מחלקת ``BaseSettings`` — pydantic קורא אותם מהסביבה לפי השם."""
    fields: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        base_names = {
            getattr(base, "id", None) or getattr(base, "attr", None)
            for base in node.bases
        }
        if "BaseSettings" not in base_names:
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fields.add(stmt.target.id)
    return fields


def collect_consumed() -> Dict[str, Dict[str, Set[str]]]:
    """מיפוי שם משתנה ← הקבצים שצורכים אותו והדיפולטים שנמצאו בקוד."""
    consumed: Dict[str, Dict[str, Set[str]]] = defaultdict(
        lambda: {"files": set(), "defaults": set()}
    )

    for path in iter_python_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()

        for node in ast.walk(tree):
            name: str | None = None
            default: Any = None
            has_default = False

            if isinstance(node, ast.Call):
                name, default, has_default = _env_read_from_call(node)
            elif isinstance(node, ast.Subscript):
                name = _env_read_from_subscript(node)

            if not name or not ENV_NAME_RE.fullmatch(name):
                continue
            consumed[name]["files"].add(rel)
            consumed[name]["defaults"].add(repr(default) if has_default else "<no-default>")

        for field_name in _pydantic_settings_fields(tree):
            if ENV_NAME_RE.fullmatch(field_name):
                consumed[field_name]["files"].add(rel)
                consumed[field_name]["defaults"].add("<pydantic-field>")

    return consumed


# --------------------------------------------------------------------------
# 3. לאיזה שירות שייך הקובץ — סגור ה-import
# --------------------------------------------------------------------------

def _module_name(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve(module: str, known: Set[str]) -> str | None:
    """ממפה שם מודול לשם קובץ בריפו, כולל ייבוא של סימבול מתוך חבילה."""
    if module in known:
        return module
    parent = module.rsplit(".", 1)[0] if "." in module else None
    if parent and parent in known:
        return parent
    return None


def build_import_graph() -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """שני גרפים: ייבוא ברמת המודול בלבד, וייבוא כולל (גם בתוך פונקציות)."""
    files = {_module_name(p): p for p in iter_python_files()}
    known = set(files)

    top_level: Dict[str, Set[str]] = {name: set() for name in files}
    all_level: Dict[str, Set[str]] = {name: set() for name in files}

    for name, path in files.items():
        tree = _parse(path)
        if tree is None:
            continue

        # כל צומת ייבוא, ואם הוא יושב בתוך def/async def הוא אינו "ברמת המודול"
        nested: Set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for inner in ast.walk(node):
                    if isinstance(inner, (ast.Import, ast.ImportFrom)):
                        nested.add(id(inner))

        for node in ast.walk(tree):
            targets: List[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # ייבוא יחסי
                    base = name.rsplit(".", 1)[0] if "." in name else ""
                    prefix = base
                    for _ in range(node.level - 1):
                        prefix = prefix.rsplit(".", 1)[0] if "." in prefix else ""
                    module = f"{prefix}.{node.module}" if node.module else prefix
                else:
                    module = node.module or ""
                targets = [module] + [
                    f"{module}.{alias.name}" for alias in node.names if module
                ]
            else:
                continue

            for target in targets:
                resolved = _resolve(target, known)
                if not resolved or resolved == name:
                    continue
                all_level[name].add(resolved)
                if id(node) not in nested:
                    top_level[name].add(resolved)

    return top_level, all_level


def _closure(graph: Dict[str, Set[str]], start: str) -> Set[str]:
    seen: Set[str] = set()
    stack = [start]
    while stack:
        current = stack.pop()
        if current in seen or current not in graph:
            continue
        seen.add(current)
        stack.extend(graph[current])
    return seen


def service_closures() -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """לכל שירות: קבוצת המודולים בסגור הוודאי ובסגור הרופף."""
    top_level, all_level = build_import_graph()
    certain: Dict[str, Set[str]] = {}
    loose: Dict[str, Set[str]] = {}
    for service, entry in ENTRY_POINTS.items():
        entry_module = _module_name(REPO_ROOT / entry)
        certain[service] = _closure(top_level, entry_module)
        loose[service] = _closure(all_level, entry_module)
    return certain, loose


# --------------------------------------------------------------------------
# 4. הרכבת הדוח
# --------------------------------------------------------------------------

def documented_keys() -> Tuple[Set[str], Set[str]]:
    """(מוזכר בתיעוד, מתועד בטבלה) — שתי רמות שונות של "כבר כתוב".

    "מתועד בטבלה" כולל גם שם שמופיע בשורה משולבת (``A`` / ``B``) וגם שם חלופי
    שנרשם בתוך תיאור המשתנה הראשי — שתי המוסכמות שבהן הרפרנס משתמש בפועל.
    """
    try:
        text = ENV_DOC_FILE.read_text(encoding="utf-8")
    except OSError:
        return set(), set()
    tabled: Set[str] = set()
    for row in DOC_ROW_RE.findall(text):
        tabled.update(DOC_MENTION_RE.findall(row))
    tabled.update(DOC_ALIAS_RE.findall(text))
    return set(DOC_MENTION_RE.findall(text)), tabled


def build_report() -> Dict[str, Any]:
    declared = collect_declared()
    consumed = collect_consumed()
    certain, loose = service_closures()
    mentioned, tabled = documented_keys()

    rows: List[Dict[str, Any]] = []
    for key in sorted(set(consumed) - declared):
        files = sorted(consumed[key]["files"])
        modules = {_module_name(REPO_ROOT / f) for f in files}
        rows.append(
            {
                "key": key,
                "files": files,
                "defaults": sorted(consumed[key]["defaults"]),
                "services_certain": sorted(
                    s for s, closure in certain.items() if modules & closure
                ),
                "services_loose": sorted(
                    s for s, closure in loose.items() if modules & closure
                ),
                "in_doc_table": key in tabled,
                "in_doc_text": key in mentioned,
            }
        )

    return {
        "declared_count": len(declared),
        "consumed_count": len(consumed),
        "gap_count": len(rows),
        "gap_with_doc_row": sum(1 for row in rows if row["in_doc_table"]),
        "rows": rows,
    }


def _print_report(report: Dict[str, Any]) -> None:
    print(f"מוצהרים ב-Config Inspector: {report['declared_count']}")
    print(f"נצרכים בקוד:               {report['consumed_count']}")
    print(f"בפער:                      {report['gap_count']}")
    print(f"  מתוכם עם שורה בתיעוד:    {report['gap_with_doc_row']}")
    print()
    for row in report["rows"]:
        services = ",".join(row["services_certain"]) or "-"
        loose_only = sorted(set(row["services_loose"]) - set(row["services_certain"]))
        loose_note = f" (רופף: {','.join(loose_only)})" if loose_only else ""
        doc = "doc-row" if row["in_doc_table"] else ("doc-text" if row["in_doc_text"] else "no-doc")
        print(f"{row['key']}")
        print(f"    שירותים: {services}{loose_note}   [{doc}]")
        print(f"    דיפולט:  {', '.join(row['defaults'])}")
        print(f"    קבצים:   {', '.join(row['files'][:6])}")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="פלט JSON מלא")
    parser.add_argument("--keys-only", action="store_true", help="שמות המשתנים שבפער בלבד")
    args = parser.parse_args(argv)

    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif args.keys_only:
        for row in report["rows"]:
            print(row["key"])
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())

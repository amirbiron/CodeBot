import ast
import pathlib
from typing import Iterable, Tuple, List

ROOT = pathlib.Path(__file__).resolve().parents[3]  # /workspace


def _python_files_under(rel_path: str) -> Iterable[pathlib.Path]:
    base = ROOT / rel_path
    if not base.exists():
        return []
    return base.rglob("*.py")


def _collect_imports(py_file: pathlib.Path) -> List[Tuple[str, str]]:
    """
    Return list of (node_type, module) for each import in file.
    node_type: 'import' or 'from'
    module: fully specified module for 'from', or the first alias for 'import'
    """
    try:
        source = py_file.read_text(encoding="utf-8")
    except Exception:
        return []
    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        return []
    imports: List[Tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(("import", alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imports.append(("from", mod))
    return imports


def _collect_dynamic_database_imports(py_file: pathlib.Path) -> List[str]:
    """
    Detect runtime dependencies on the legacy `database` package via dynamic means.

    Why: patterns like `importlib.import_module("database")` bypass ast.Import/ast.ImportFrom checks,
    and patterns like `sys.modules.get("database")`/`sys.modules["database"]` are another indirect
    way to reach the DB layer from handlers. We want to keep all of these out of handlers so that
    persistence is accessed only via composition/facades/services.
    """
    try:
        source = py_file.read_text(encoding="utf-8")
    except Exception:
        return []
    try:
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        return []
    mods: List[str] = []
    for node in ast.walk(tree):
        # importlib.import_module("database" / "database.*")
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "importlib":
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        mod = node.args[0].value
                        if mod.startswith("database"):
                            mods.append(mod)

            # __import__("database" / "database.*")
            if isinstance(node.func, ast.Name) and node.func.id == "__import__":
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    mod = node.args[0].value
                    if mod.startswith("database"):
                        mods.append(mod)

            # sys.modules.get("database" / "database.*")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                # sys.modules.get(...)
                if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "modules":
                    if isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "sys":
                        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            mod = node.args[0].value
                            if mod.startswith("database"):
                                mods.append(f"sys.modules.get({mod})")

        # sys.modules["database" / "database.*"]
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Attribute) and node.value.attr == "modules":
                if isinstance(node.value.value, ast.Name) and node.value.value.id == "sys":
                    sl = node.slice
                    if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                        mod = sl.value
                        if mod.startswith("database"):
                            mods.append(f"sys.modules[{mod}]")
    return mods


def _dynamic_database_import_violations(files: Iterable[pathlib.Path]) -> List[Tuple[pathlib.Path, str]]:
    violations: List[Tuple[pathlib.Path, str]] = []
    for f in files:
        for mod in _collect_dynamic_database_imports(f):
            violations.append((f, mod))
    return violations


def _violations(files: Iterable[pathlib.Path], forbidden_prefixes: Iterable[str], allowed_prefixes: Iterable[str] = ()) -> List[Tuple[pathlib.Path, str]]:
    violations: List[Tuple[pathlib.Path, str]] = []
    allowed_prefixes = tuple(allowed_prefixes)
    forbidden_prefixes = tuple(forbidden_prefixes)
    for f in files:
        for _kind, mod in _collect_imports(f):
            if not mod:
                continue
            # allowlist takes precedence
            if allowed_prefixes and any(mod.startswith(p) for p in allowed_prefixes):
                continue
            if any(mod.startswith(p) for p in forbidden_prefixes):
                violations.append((f, mod))
    return violations


def test_domain_does_not_depend_on_handlers_or_infrastructure():
    files = list(_python_files_under("src/domain"))
    # Domain should not import handlers, legacy services, or infrastructure
    forbidden = ("handlers", "services", "database", "src.infrastructure", "webapp")
    violations = _violations(files, forbidden_prefixes=forbidden)
    assert not violations, f"Domain layer import violations:\n" + "\n".join(f"- {p}: {mod}" for p, mod in violations)


def test_application_does_not_depend_on_handlers_or_infrastructure():
    files = list(_python_files_under("src/application"))
    # Application can import domain and its own modules, but not handlers or infrastructure
    forbidden = ("handlers", "database", "webapp", "src.infrastructure")
    violations = _violations(files, forbidden_prefixes=forbidden)
    assert not violations, f"Application layer import violations:\n" + "\n".join(f"- {p}: {mod}" for p, mod in violations)


def test_handlers_do_not_depend_directly_on_domain_or_raw_infrastructure():
    files = list(_python_files_under("handlers"))
    # Handlers should not import domain directly; infrastructure only via composition
    forbidden = ("src.domain", "src.infrastructure")
    allowed = ("src.infrastructure.composition",)
    violations = _violations(files, forbidden_prefixes=forbidden, allowed_prefixes=allowed)
    assert not violations, f"Handlers import violations:\n" + "\n".join(f"- {p}: {mod}" for p, mod in violations)


def test_handlers_do_not_import_database_directly():
    """
    Handlers must not import the legacy `database` package directly.
    Access to persistence should go through composition/facades/services.
    """
    files = list(_python_files_under("handlers"))
    forbidden = ("database",)
    violations = _violations(files, forbidden_prefixes=forbidden)
    dyn = _dynamic_database_import_violations(files)
    assert not violations and not dyn, "Handlers must not import database directly:\n" + "\n".join(
        [*(f"- {p}: {mod}" for p, mod in violations), *(f"- {p}: {mod} (dynamic)" for p, mod in dyn)]
    )


def test_top_level_handler_like_modules_do_not_import_database_directly():
    """
    Some legacy "handlers" live at the repository root (not under handlers/**).

    They still behave like handlers (Telegram flows / menus) and must not import the
    legacy `database` package directly.
    """
    explicit = (
        "bot_handlers.py",
        "conversation_handlers.py",
        "github_menu_handler.py",
        "github_upload_fix.py",
        "backup_menu_handler.py",
        "file_manager.py",
    )
    files = [ROOT / f for f in explicit if (ROOT / f).exists()]
    # Also include any handler-like modules under root (excluding handlers/ and tests/)
    # to avoid missing nested handler files like reminders/handlers.py.
    try:
        for f in ROOT.rglob("*handler*.py"):
            if "tests" in f.parts:
                continue
            if "node_modules" in f.parts:
                continue
            if ".venv" in f.parts or "venv" in f.parts:
                continue
            if (ROOT / "handlers") in f.parents:
                continue
            files.append(f)
    except Exception:
        pass
    # De-dup while preserving order
    seen = set()
    uniq = []
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        uniq.append(f)
    files = uniq
    forbidden = ("database",)
    violations = _violations(files, forbidden_prefixes=forbidden)
    dyn = _dynamic_database_import_violations(files)
    assert not violations and not dyn, "Top-level handler-like modules must not import database directly:\n" + "\n".join(
        [*(f"- {p}: {mod}" for p, mod in violations), *(f"- {p}: {mod} (dynamic)" for p, mod in dyn)]
    )


def test_infrastructure_does_not_depend_on_handlers():
    files = list(_python_files_under("src/infrastructure"))
    forbidden = ("handlers",)
    violations = _violations(files, forbidden_prefixes=forbidden)
    assert not violations, f"Infrastructure layer import violations:\n" + "\n".join(f"- {p}: {mod}" for p, mod in violations)


# ---- WebApp Architecture Tests ------------------------------------------------


def _count_webapp_database_violations() -> Tuple[int, List[Tuple[pathlib.Path, str]]]:
    """
    Count database import violations in webapp.

    Returns (total_violations, list_of_violations).
    This helper is used both for tracking progress and for the eventual strict test.
    """
    files = list(_python_files_under("webapp"))

    # Allowed: composition root, existing services that are already factored out
    allowed = (
        "src.infrastructure.composition",
        "services.shared_theme_service",
        "services.theme_presets_service",
        "services.rules_storage",
    )

    # Forbidden: direct database imports
    forbidden = ("database",)

    static_violations = _violations(files, forbidden_prefixes=forbidden, allowed_prefixes=allowed)
    dynamic_violations = _dynamic_database_import_violations(files)

    all_violations = [*static_violations, *dynamic_violations]
    return len(all_violations), all_violations


def test_webapp_database_import_violations_tracking():
    """
    Track the number of database import violations in webapp.

    This test documents the current state and tracks progress as we migrate
    webapp to use the composition root instead of direct database imports.

    Target: 0 violations (all imports via src.infrastructure.composition)
    Current: ~20 violations (as of January 2026)

    When we reach 0 violations, this test should be replaced with
    test_webapp_does_not_import_database_directly().
    """
    count, violations = _count_webapp_database_violations()

    # Document current state - update this as we make progress
    # This is not a strict assertion, just tracking
    KNOWN_VIOLATION_FILES = {
        "webapp/app.py",
        "webapp/bookmarks_api.py",
        "webapp/collections_api.py",
        "webapp/routes/repo_browser.py",
        "webapp/routes/webhooks.py",
    }

    violation_files = {str(p.relative_to(ROOT)) for p, _ in violations}

    # Log for visibility
    if violations:
        print(f"\n[WebApp Layering] Found {count} database import violations:")
        for p, mod in violations[:10]:  # Show first 10
            print(f"  - {p.relative_to(ROOT)}: {mod}")
        if count > 10:
            print(f"  ... and {count - 10} more")

    # This assertion will fail if new violations are introduced
    # (files not in KNOWN_VIOLATION_FILES start importing database directly)
    new_violation_files = violation_files - KNOWN_VIOLATION_FILES
    assert not new_violation_files, (
        f"New database import violations detected in previously clean files:\n"
        + "\n".join(f"- {f}" for f in sorted(new_violation_files))
        + "\n\nUse src.infrastructure.composition instead of direct database imports."
    )


def test_webapp_does_not_import_database_directly():
    """
    WebApp must not import the legacy `database` package directly.

    Access to persistence should go through:
    - src.infrastructure.composition.get_files_facade()
    - src.infrastructure.composition.get_bookmarks_manager()
    - src.infrastructure.composition.get_collections_manager()
    - src.infrastructure.composition.get_rules_storage()
    - services.shared_theme_service.get_shared_theme_service()

    NOTE: This test is currently expected to fail (xfail).
    It will pass once we complete the webapp layering migration.
    See docs/WEBAPP_LAYERING_ANALYSIS.md for the migration plan.
    """
    import pytest

    count, violations = _count_webapp_database_violations()

    if count > 0:
        pytest.xfail(
            f"WebApp layering migration in progress: {count} violations remaining. "
            f"See docs/WEBAPP_LAYERING_ANALYSIS.md"
        )

    # This will only run when count == 0
    assert not violations, (
        "WebApp must not import database directly:\n"
        + "\n".join(f"- {p}: {mod}" for p, mod in violations)
    )


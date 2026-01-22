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


# ============================================================================
# WebApp Architecture Tests (Progress Tracking)
# ============================================================================
# These tests track progress toward the goal of having WebApp access DB
# only through composition/facades/services.
# They document current violations and will start failing as we clean up.
# ============================================================================


def _webapp_files_excluding_feature_suggestions() -> List[pathlib.Path]:
    """
    Return webapp Python files, excluding FEATURE_SUGGESTIONS directories.
    """
    files = []
    for f in _python_files_under("webapp"):
        parts = f.parts
        if "FEATURE_SUGGESTIONS" in parts:
            continue
        files.append(f)
    return files


def test_webapp_api_modules_database_imports_progress():
    """
    Track progress: WebApp API modules should not import database directly.

    Target: 0 violations (all DB access through FilesFacade).
    Current: Known violations documented below. As we clean up, update baseline.

    This test documents the current state and tracks improvement.
    """
    # API modules we're tracking (not the main app.py which has many)
    api_modules = (
        "bookmarks_api.py",
        "collections_api.py",
        "themes_api.py",
        "sticky_notes_api.py",
        "push_api.py",
        "rules_api.py",
    )

    files = []
    webapp_root = ROOT / "webapp"
    for mod in api_modules:
        p = webapp_root / mod
        if p.exists():
            files.append(p)

    forbidden = ("database",)
    allowed = ("src.infrastructure.composition",)
    violations = _violations(files, forbidden_prefixes=forbidden, allowed_prefixes=allowed)
    dyn = _dynamic_database_import_violations(files)

    # Current known violations (baseline - update as we clean up)
    # All API modules cleaned up! They now use FilesFacade.
    KNOWN_VIOLATIONS_COUNT = 0  # Target achieved!

    total_violations = len(violations) + len(dyn)

    # This test passes as long as we don't regress (add new violations)
    # It will fail if violations INCREASE, alerting us to new database imports
    if total_violations > KNOWN_VIOLATIONS_COUNT:
        assert False, (
            f"WebApp API modules: NEW database imports detected! "
            f"Expected max {KNOWN_VIOLATIONS_COUNT}, found {total_violations}.\n"
            f"Violations:\n" +
            "\n".join(f"- {p}: {mod}" for p, mod in violations) +
            ("\n" if violations and dyn else "") +
            "\n".join(f"- {p}: {mod} (dynamic)" for p, mod in dyn)
        )

    # Report progress (informational, not a failure)
    if total_violations < KNOWN_VIOLATIONS_COUNT:
        # Update the baseline in the test when violations decrease!
        pass  # Good progress!

    # Document current state
    # When total_violations reaches 0, change this test to assert no violations


def test_webapp_routes_database_imports_progress():
    """
    Track progress: WebApp route modules should not import database directly.

    Target: 0 violations.
    """
    routes_dir = ROOT / "webapp" / "routes"
    files = list(routes_dir.rglob("*.py")) if routes_dir.exists() else []

    forbidden = ("database",)
    allowed = ("src.infrastructure.composition",)
    violations = _violations(files, forbidden_prefixes=forbidden, allowed_prefixes=allowed)

    # Current known violations (baseline)
    # repo_browser.py: from database.db_manager
    # webhooks.py: from database.db_manager (conditional)
    KNOWN_VIOLATIONS_COUNT = 2  # Update as we clean up

    total_violations = len(violations)

    if total_violations > KNOWN_VIOLATIONS_COUNT:
        assert False, (
            f"WebApp routes: NEW database imports detected! "
            f"Expected max {KNOWN_VIOLATIONS_COUNT}, found {total_violations}.\n"
            f"Violations:\n" +
            "\n".join(f"- {p}: {mod}" for p, mod in violations)
        )


def test_webapp_should_use_composition_facade():
    """
    Verify that get_files_facade / get_snippet_service are available and importable.

    This is a sanity check to ensure the composition layer is correctly set up
    for WebApp to use.
    """
    try:
        from src.infrastructure.composition import get_files_facade, get_snippet_service
    except ImportError as e:
        assert False, f"Could not import composition functions: {e}"

    # Verify these are callable
    assert callable(get_files_facade), "get_files_facade should be callable"
    assert callable(get_snippet_service), "get_snippet_service should be callable"


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
    assert not violations, "Handlers must not import database directly:\n" + "\n".join(f"- {p}: {mod}" for p, mod in violations)


def test_infrastructure_does_not_depend_on_handlers():
    files = list(_python_files_under("src/infrastructure"))
    forbidden = ("handlers",)
    violations = _violations(files, forbidden_prefixes=forbidden)
    assert not violations, f"Infrastructure layer import violations:\n" + "\n".join(f"- {p}: {mod}" for p, mod in violations)


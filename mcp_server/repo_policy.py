"""Secrets-path policy for the repo-browser tools (Phase D, admin-only).

The bare mirrors can contain anything that was ever committed — including
``.env`` files, private keys and credential stores. The engine's read paths
serve file contents verbatim (no redaction), so this policy is a **mandatory
precondition** for the MCP repo tools (FEATURE doc §13.5):

- ``get_repo_file`` **blocks** a denied path (``path_denied``),
- ``list_repo_tree`` **omits** denied paths from listings,
- ``search_repo`` **skips** them in results.

Matching is fail-closed: any internal error while evaluating a path counts as
denied. Paths are normalized (posix separators, ``normpath``, lowercase) and
matched case-insensitively against both the full path and the basename, so
nested paths (``config/.env``) and case variants (``.ENV``) are covered.

Stdlib-only on purpose — trivially unit-testable, importable anywhere.
"""

from __future__ import annotations

import fnmatch
import os
import posixpath

# Baseline denylist (lowercase glob patterns, matched against basename AND full
# path). Deliberately errs on over-blocking — this is a security filter, not a
# relevance filter. Extend per-deploy via MCP_REPO_DENYLIST_EXTRA (CSV globs).
BASENAME_DENYLIST: tuple[str, ...] = (
    ".env*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "id_dsa*",
    "secrets.*",
    "credentials*",
    "*.p12",
    "*.pfx",
    ".netrc",
    ".npmrc",
    "*.keystore",
    "*.jks",
)

_EXTRA_ENV = "MCP_REPO_DENYLIST_EXTRA"


def _patterns() -> tuple[str, ...]:
    extra = tuple(p.strip().lower() for p in os.getenv(_EXTRA_ENV, "").split(",") if p.strip())
    return BASENAME_DENYLIST + extra


def is_denied(path: object) -> bool:
    """Return True if ``path`` must not be served. Errors ⇒ True (fail closed)."""
    try:
        norm = posixpath.normpath(str(path or "").replace("\\", "/")).lower().lstrip("/")
        if not norm or norm in (".", ".."):
            return True
        base = posixpath.basename(norm)
        for pattern in _patterns():
            if fnmatch.fnmatchcase(base, pattern) or fnmatch.fnmatchcase(norm, pattern):
                return True
        return False
    except Exception:
        return True

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
matched case-insensitively against the full path **and against every path
component**, so case variants (``.ENV``) are covered and a sensitive name is
caught wherever it sits in the tree — as a file (``config/.env``) or as a
directory holding other files (``config/.env/README.md``).

Stdlib-only on purpose — trivially unit-testable, importable anywhere.
"""

from __future__ import annotations

import fnmatch
import os
import posixpath

# Baseline denylist (lowercase glob patterns, matched against the full path AND
# against every component of it — a sensitive name is caught as a file and as a
# directory holding other files). Deliberately errs on over-blocking — this is a
# security filter, not a relevance filter. Extend per-deploy via
# MCP_REPO_DENYLIST_EXTRA (CSV globs).
#
# השם היה ``BASENAME_DENYLIST`` כל עוד ההתאמה הייתה מול ה-basename. היא אינה,
# והשם הוא המקום שאליו מגיע מי שבא להוסיף תבנית — הוא היה כותב תבנית ל-basename
# ולא יודע שהיא נבדקת מול כל רכיב ומול הנתיב השלם.
PATH_DENYLIST: tuple[str, ...] = (
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
    return PATH_DENYLIST + extra


def denylist_patterns() -> tuple[str, ...]:
    """The exact patterns :func:`is_denied` matches against, for callers that
    must apply the same policy *earlier* than the result list.

    ``search_repo`` hands these to the engine, which turns each one into a
    ``git grep`` exclude pathspec — so a denied file is never scanned, never
    returned **and never counted**. Deriving both from this one function is the
    whole point: a second hand-written list would drift, and the drift would be
    invisible (the count would quietly include a file the results dropped).

    :func:`is_denied` stays the last layer on the results regardless — a
    pattern the engine cannot express still blocks here.
    """
    return _patterns()


def is_denied(path: object) -> bool:
    """Return True if ``path`` must not be served. Errors ⇒ True (fail closed)."""
    try:
        norm = posixpath.normpath(str(path or "").replace("\\", "/")).lower().lstrip("/")
        if not norm or norm in (".", ".."):
            return True
        # **כל רכיב בנתיב, ולא רק ה-basename.** שם רגיש יכול להיות תיקייה
        # ולא קובץ, והקבצים שבתוכה רגישים בדיוק כמוהו. ההתאמה הקודמת בדקה
        # basename ונתיב מלא בלבד, וזה נתן כיסוי **מקרי**: ``fnmatch`` מרשה
        # ל-``*`` לחצות ``/``, ולכן ``credentials*`` תפס את
        # ``credentials/notes.md`` — כי התיקייה במקרה ישבה ברכיב הראשון —
        # ואילו ``config/.env/README.md`` עבר. נמדד, לפני התיקון:
        # ``config/.env/README.md``, ``a/secrets.d/x.md``,
        # ``keys/id_rsa/readme.md``, ``x/.NETRC/y.md`` ו-
        # ``deep/a/b/credentials/notes.md`` — כולם ``False``.
        #
        # זהו ``filter-too-narrow`` §2 ב-``amir-bug-patterns`` (התאמה
        # מדויקת במקום התאמה ליחידה הנכונה), ואותה מחלקה כמו ``K16``: גבול
        # היררכי שנבדק כרצף תווים במקום כרצף רכיבים.
        #
        # **ובדיקת ה-basename נמחקה ולא נוספה לה שנייה.** הרכיב האחרון
        # **הוא** ה-basename — נמדד שהם זהים בכל צורה שמגיעה לכאן, אחרי
        # ``normpath`` — ולכן סריקת הרכיבים בולעת אותה. שתי בדיקות שמתארות
        # אותו כלל הן ``duplicate-rule-second-copy``.
        #
        # **ובדיקת הנתיב המלא נשארת, והיא אינה כפילות:** תבנית שמגיעה
        # מ-``MCP_REPO_DENYLIST_EXTRA`` יכולה להכיל ``/`` (``internal/*``),
        # והיא מתאימה לנתיב ולא לאף רכיב בודד.
        #
        # **העלות נמדדה ולא הוערכה, ועל כל המראות ולא על אחת.** המדיניות
        # הזאת חלה על כל מראה שהשירות מגיש, ולכן המדידה נעשתה על שלושתן,
        # עם נתיבים מופרדי-``\0`` (פיצול על רווחים מרסק נתיבים שיש בהם
        # רווח וסופר רסיסים): CodeBot 10,174 נתיבים — שניים חסומים לפני
        # ושניים אחרי; Han 688 — אפס ואפס; ``amir-bug-patterns`` 95 —
        # אפס. **אפס קבצים חדשים נחסמים בכל אחת מהן, ואפס משוחררים.**
        # זו הבדיקה ש-``blanket-policy-silent-block`` דורש לפני מדיניות
        # שמרחיבה חסימה, והיא מכסה את המשטח שהמדיניות באמת חלה עליו.
        parts = [part for part in norm.split("/") if part and part != "."]
        if not parts:
            return True
        for pattern in _patterns():
            if fnmatch.fnmatchcase(norm, pattern):
                return True
            if any(fnmatch.fnmatchcase(part, pattern) for part in parts):
                return True
        return False
    except Exception:
        return True

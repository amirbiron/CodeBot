"""Pure handler for the public docs tool ``codekeeper_docs_get_section``.

Same contract as ``repo_handlers.py``: a plain function, no MCP/Starlette imports,
clamped inputs, ``{"ok": False, "error": "..."}`` rejections. **Not** admin-gated —
this is a public tool; the tool body deliberately omits ``require_admin``.

It reuses ``RepoBackend.get_file`` to read the raw RST text from the mirror (that already
handles ref-default, secrets policy, and the ``sync_in_progress`` retry contract), then
``services.rst_parser`` to extract a single section with navigation. Guiding rule: never
return only "not found" — no section ⇒ TOC; missing ⇒ TOC + suggestions; duplicate ⇒
candidates with breadcrumb.
"""

from __future__ import annotations

import os
import posixpath
from typing import Any

from services import rst_parser
from .handlers import _clamp

MAX_CHARS_DEFAULT = 12_000
MAX_CHARS_MAX = 100_000
MAX_CHARS_MIN = 500
DEFAULT_DOCS_REPO = "CodeBot"
_TOC_MAX = 400  # תקרת פריטי TOC בתשובה (הגנת גודל)


def _allowed_docs_repos() -> list[str]:
    """רשימת הריפואים המותרים לכלי (CSV ב-MCP_DOCS_REPO), עם fallback ל-CodeBot."""
    raw = os.getenv("MCP_DOCS_REPO", DEFAULT_DOCS_REPO) or DEFAULT_DOCS_REPO
    repos = [r.strip() for r in raw.split(",") if r.strip()]
    return repos or [DEFAULT_DOCS_REPO]


def _resolve_docs_repo(repo: str | None) -> str | None:
    """ברירת מחדל = הריפו הראשון ב-allowlist; repo מפורש מותר רק אם ב-allowlist (אחרת None).

    הכלי ציבורי — בלי האכיפה הזו כל משתמש מאומת יכול לקרוא .rst מכל ריפו ב-mirror (IDOR).
    """
    allowed = _allowed_docs_repos()
    r = (repo or "").strip()
    if not r:
        return allowed[0]
    return r if r in allowed else None


def _resolve_docs_path(path: str) -> str | None:
    """נתיב מלא (docs/x.rst) או slug קצר (x / x.rst) → נתיב מנורמל תחת docs/ בלבד.

    מחזיר None עבור traversal (``..``), נתיב מוחלט, או כל נתיב שאינו תחת ``docs/`` — כולל
    קלט שמכיל slash (למשל ``webapp/x``). זו הגנת שכבה בנוסף לאימות ה-path של ה-backend.
    """
    p = (path or "").strip().strip("/")
    if not p or "\x00" in p:
        return None
    if not p.endswith(".rst"):
        p = p + ".rst"
    if "/" not in p:
        p = "docs/" + p
    # נרמול וחסימה: traversal שיוצא מ-docs/ (docs/../x → x.rst), נתיב מוחלט, וכל דבר מחוץ ל-docs/
    norm = posixpath.normpath(p)
    if not norm.startswith("docs/"):
        return None
    return norm


def _toc(doc: "rst_parser.Document") -> tuple[list, bool]:
    items = rst_parser.build_toc(doc)
    if len(items) > _TOC_MAX:
        return items[:_TOC_MAX], True
    return items, False


def _section_ref(sec: "rst_parser.Section") -> dict:
    return {"title": sec.title, "level": sec.level,
            "line_range": [sec.heading_line, sec.end_line]}


def docs_get_section(
    backend: Any,
    *,
    path: str,
    section: str | None = None,
    include_subsections: bool = True,
    max_chars: int = MAX_CHARS_DEFAULT,
    offset: int = 0,
    repo: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    file_path = _resolve_docs_path(path)
    if not file_path:
        return {"ok": False, "error": "missing_path"}
    repo_name = _resolve_docs_repo(repo)
    if not repo_name:
        return {"ok": False, "error": "repo_not_allowed", "requested_repo": repo}
    max_chars = _clamp(max_chars, MAX_CHARS_MIN, MAX_CHARS_MAX, MAX_CHARS_DEFAULT)
    offset = _clamp(offset, 0, 10 ** 9, 0)

    # קריאה — reuse מלא של RepoBackend.get_file (ref default, מדיניות סודות, sync_in_progress)
    res = backend.get_file(repo=repo_name, path=file_path, ref=((ref or "").strip() or None))
    if not res.get("ok"):
        # not_found / invalid_input / sync_in_progress — מוסיפים הקשר ומעבירים הלאה
        res.setdefault("repo", repo_name)
        res.setdefault("path", file_path)
        return res
    if res.get("status") != "ok":
        # binary / too_large — אין תוכן טקסט לפרסר
        return {"ok": False, "error": f"unreadable_{res.get('status')}",
                "repo": repo_name, "path": file_path, "file": res.get("file")}

    content = res.get("content") or ""
    file_meta = res.get("file") or {}
    doc = rst_parser.parse_document(content)
    toc_items, toc_truncated = _toc(doc)

    base: dict[str, Any] = {
        "ok": True, "repo": repo_name, "path": file_path,
        "ref": file_meta.get("ref"), "resolved_commit": file_meta.get("resolved_commit"),
        "includes": list(doc.includes),
    }

    # בלי section → עץ כותרות (הכלי משמש גם לניווט)
    if not (section or "").strip():
        base.update({"mode": "toc", "toc": toc_items, "toc_truncated": toc_truncated,
                     "section_count": len(doc.sections)})
        return base

    matches = rst_parser.find_sections(doc, section)

    # לא נמצא → TOC מלא + הצעות קרובות (לעולם לא רק "לא נמצא")
    if not matches:
        base.update({
            "ok": False, "error": "section_not_found", "requested": section,
            "suggestions": rst_parser.suggest(doc, section),
            "toc": toc_items, "toc_truncated": toc_truncated,
        })
        return base

    # כותרת כפולה → כל המועמדים עם breadcrumb (בלי לנחש)
    if len(matches) > 1:
        base.update({
            "ok": False, "error": "ambiguous_section", "requested": section,
            "candidates": [{
                "title": s.title, "breadcrumb": list(s.breadcrumb),
                "level": s.level, "line_range": [s.heading_line, s.end_line],
            } for s in matches],
        })
        return base

    # התאמה יחידה → הסקשן + ניווט (שכנים ותת-סקשנים)
    sec = matches[0]
    full = rst_parser.section_text(doc, sec, include_subsections)
    total = len(full)
    chunk = full[offset:offset + max_chars]
    truncated = (offset + len(chunk)) < total
    prev, nxt = rst_parser.neighbors(doc, sec)

    base.update({
        "mode": "section",
        "section": sec.title,
        "breadcrumb": list(sec.breadcrumb),
        "level": sec.level,
        "line_range": [sec.heading_line, sec.end_line],
        "include_subsections": bool(include_subsections),
        "offset": offset,
        "content": chunk,
        "truncated": truncated,
        "subsections": [_section_ref(s) for s in rst_parser.direct_subsections(doc, sec)],
        "neighbors": {
            "prev": _section_ref(prev) if prev else None,
            "next": _section_ref(nxt) if nxt else None,
        },
    })
    if truncated:
        base["remaining_chars"] = total - (offset + len(chunk))
        base["next_offset"] = offset + len(chunk)
    return base

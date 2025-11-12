#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import os
import re
import sys
import textwrap
from typing import List, Optional, Tuple

# Lazy imports to keep script lightweight
try:
    from urllib.parse import urlparse
    from urllib.request import Request, urlopen
except Exception:  # pragma: no cover
    urlparse = None  # type: ignore
    Request = None  # type: ignore
    urlopen = None  # type: ignore


@dataclasses.dataclass
class ParsedSnippet:
    title: str
    description: str
    code: str
    language: str


HEADER_RE = re.compile(r"^\s{0,3}#{2,4}\s+(.+?)\s*$")
WHY_RE = re.compile(r"^\s*\*\*למה זה שימושי:\*\*\s*(.+?)\s*$")
FENCE_START_RE = re.compile(r"^```([a-zA-Z0-9_+-]*)\s*$")
FENCE_END_RE = re.compile(r"^```\s*$")


def _guess_language(value: str, fallback: str = "text") -> str:
    value = (value or "").strip().lower()
    if not value:
        return fallback
    mapping = {
        "py": "python",
        "js": "javascript",
        "ts": "typescript",
        "sh": "bash",
        "shell": "bash",
        "yml": "yaml",
        "md": "markdown",
        "golang": "go",
        "html5": "html",
        "css3": "css",
    }
    return mapping.get(value, value)


def _fetch_url(url: str, timeout: int = 20) -> str:
    if Request is None or urlopen is None:
        raise RuntimeError("URL fetching is not available in this environment")
    req = Request(url, headers={"User-Agent": "CodeBot/Importer"})
    with urlopen(req, timeout=timeout) as resp:  # type: ignore[arg-type]
        data = resp.read()
        return data.decode("utf-8", errors="replace")


def _maybe_to_raw_url(url: str) -> str:
    """Best-effort conversion of GitHub/Gist file URLs to raw content URLs."""
    try:
        parsed = urlparse(url)
    except Exception:
        return url

    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    # GitHub repo file: https://github.com/{owner}/{repo}/blob/{branch}/{path}
    if host == "github.com" and "/blob/" in path:
        parts = path.strip("/").split("/")
        if len(parts) >= 5:
            owner, repo, _blob, branch = parts[:4]
            tail = "/".join(parts[4:])
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{tail}"

    # Gist: https://gist.github.com/{user}/{id}
    if host == "gist.github.com":
        parts = path.strip("/").split("/")
        if len(parts) >= 2:
            user, gist_id = parts[:2]
            # Generic raw for default file
            return f"https://gist.githubusercontent.com/{user}/{gist_id}/raw"

    return url


def load_source(source: str | None) -> str:
    if not source or source == "-":
        return sys.stdin.read()

    # Local file path
    if os.path.exists(source):
        with open(source, "r", encoding="utf-8") as f:
            return f.read()

    # URL
    src = _maybe_to_raw_url(source)
    return _fetch_url(src)


def parse_markdown(markdown_text: str) -> List[ParsedSnippet]:
    lines = markdown_text.splitlines()
    results: List[ParsedSnippet] = []

    current_title: Optional[str] = None
    current_description: Optional[str] = None

    i = 0
    while i < len(lines):
        line = lines[i]

        # Header/title
        m_header = HEADER_RE.match(line)
        if m_header:
            # Normalize title: strip emoji checkmarks and extra spaces
            raw_title = m_header.group(1).strip()
            # Remove leading bullets/emoji decorations
            raw_title = re.sub(r"^[✅\-\s]+", "", raw_title)
            current_title = raw_title
            current_description = None
            i += 1
            continue

        # Why useful line
        m_why = WHY_RE.match(line)
        if m_why:
            current_description = m_why.group(1).strip()
            i += 1
            continue

        # Code fence start
        m_fence = FENCE_START_RE.match(line)
        if m_fence:
            lang = _guess_language(m_fence.group(1) or "text")
            code_lines: List[str] = []
            i += 1
            while i < len(lines):
                if FENCE_END_RE.match(lines[i]):
                    break
                code_lines.append(lines[i])
                i += 1
            # Skip closing fence line
            # If malformed markdown and no closing fence, we still proceed with accumulated lines
            if i < len(lines) and FENCE_END_RE.match(lines[i]):
                i += 1

            title = (current_title or "סניפט ללא כותרת").strip()
            description = (current_description or "מתוך מסמך מיוחד").strip()

            # Compact description (first sentence, up to ~160 chars)
            description = description.replace("\n", " ").strip()
            if len(description) > 160:
                description = description[:157].rstrip() + "..."

            code_text = "\n".join(code_lines).rstrip("\n")
            # Safety: trim super‑long code blocks to a sane size (but keep most realistic snippets)
            if len(code_text) > 150_000:
                code_text = code_text[:150_000] + "\n# ... trimmed ..."

            results.append(ParsedSnippet(title=title, description=description, code=code_text, language=lang))
            continue

        i += 1

    return results


def persist_snippets(
    snippets: List[ParsedSnippet],
    *,
    user_id: int = 1,
    username: str = "CodeBot",
    auto_approve: bool = True,
    dry_run: bool = False,
) -> Tuple[int, int, int]:
    """Persist snippets into the Snippets Library DB using repository APIs.

    Returns: (created, approved, skipped)
    """
    try:
        from database import db as _db
        from database.repository import Repository  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"Database import unavailable: {e}")

    created = 0
    approved = 0
    skipped = 0

    # Helper: check duplicates by title (case-insensitive) in any status
    def _exists_title_ci(title: str) -> bool:
        try:
            coll = getattr(_db, 'snippets_collection', None)
            if coll is None:
                return False
            # Case-insensitive exact title match
            q = {"title": {"$regex": f"^{re.escape(title)}$", "$options": "i"}}
            doc = coll.find_one(q)
            return bool(doc)
        except Exception:
            return False

    for snip in snippets:
        if _exists_title_ci(snip.title):
            skipped += 1
            continue

        if dry_run:
            created += 1
            if auto_approve:
                approved += 1
            continue

        try:
            res = _db._get_repo().create_snippet_proposal(
                title=snip.title,
                description=snip.description,
                code=snip.code,
                language=snip.language,
                user_id=int(user_id),
                username=username,
            )
            if res:
                created += 1
                if auto_approve:
                    ok = _db._get_repo().approve_snippet(res, int(user_id))
                    if ok:
                        approved += 1
            else:
                # treat as skipped on failure
                skipped += 1
        except Exception:
            skipped += 1

    return created, approved, skipped


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Import code snippets into the WebApp Snippets Library from a Markdown file or URL (including GitHub/Gist).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Examples:
              # From local file
              scripts/import_snippets_from_markdown.py --source docs/new-snippets.md

              # From GitHub file page (auto-converts to raw)
              scripts/import_snippets_from_markdown.py --source https://github.com/user/repo/blob/main/SNIPPETS.md

              # From Gist page (auto-converts to raw)
              scripts/import_snippets_from_markdown.py --source https://gist.github.com/user/abcdef123456

              # From stdin
              cat SNIPPETS.md | scripts/import_snippets_from_markdown.py --source -
            """
        ),
    )
    p.add_argument("--source", required=True, help="Path, URL, or '-' for stdin")
    p.add_argument("--user-id", type=int, default=1, help="Importer user id to attribute (default: 1)")
    p.add_argument("--username", default="CodeBot", help="Importer username (default: CodeBot)")
    p.add_argument("--no-approve", action="store_true", help="Do not auto-approve newly created snippets")
    p.add_argument("--dry-run", action="store_true", help="Parse and show counts without writing to DB")

    args = p.parse_args(argv)

    try:
        content = load_source(args.source)
    except Exception as e:
        print(f"Failed to load source: {e}", file=sys.stderr)
        return 2

    snippets = parse_markdown(content)
    if not snippets:
        print("No snippets found in source", file=sys.stderr)
        return 3

    auto_approve = not args.no_approve

    try:
        created, approved, skipped = persist_snippets(
            snippets,
            user_id=args.user_id,
            username=args.username,
            auto_approve=auto_approve,
            dry_run=args.dry_run,
        )
    except Exception as e:
        print(f"Import failed: {e}", file=sys.stderr)
        return 4

    print(
        f"Snippets parsed: {len(snippets)} | created: {created} | approved: {approved} | skipped: {skipped}"
    )
    if args.dry_run:
        print("(dry-run: nothing was written)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, Iterable, List


def _iter_files(base: Path, includes: List[str]) -> Iterable[Path]:
    if not includes:
        # default: all files under base
        for p in base.rglob("*"):
            if p.is_file():
                yield p
        return
    # respect globs
    for pattern in includes:
        for p in base.glob(pattern):
            if p.is_file():
                yield p


def _split_norm_lines(text: str) -> List[str]:
    """Split text into normalized lines with trailing blanks removed.

    - Convert CRLF/CR to LF
    - Rstrip trailing spaces on each line
    - Drop trailing empty lines so a trailing newline does not change content
    """
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in s.split("\n")]
    # Remove trailing empty lines
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _norm_content(text: str) -> str:
    # Normalize content using the split helper above
    return "\n".join(_split_norm_lines(text))


def scan_duplicates(base_path: str, *, includes: List[str], min_lines: int = 5, max_files: int = 500) -> Dict[str, List[str]]:
    """
    Find exact duplicate files by normalized content.

    Returns mapping: content_hash -> list of relative file paths (len>=2).
    """
    base = Path(base_path or ".").resolve()
    files: List[Path] = []
    seen: set[str] = set()
    for p in _iter_files(base, includes):
        # De-duplicate same path from overlapping globs
        rp = str(p.resolve())
        if rp in seen:
            continue
        seen.add(rp)
        files.append(p)
        if len(files) >= max_files:
            break

    groups: Dict[str, List[str]] = {}
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # Count effective lines after normalization (ignoring trailing blanks)
        eff_lines = len(_split_norm_lines(text)) if text else 0
        if eff_lines < max(1, int(min_lines or 1)):
            continue
        norm = _norm_content(text)
        h = hashlib.sha1(norm.encode("utf-8")).hexdigest()
        rel = os.path.relpath(str(p), str(base))
        groups.setdefault(h, []).append(rel)

    # Keep only hashes with duplicates
    return {h: paths for h, paths in groups.items() if len(paths) >= 2}

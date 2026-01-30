"""
Code chunking service for semantic search.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from config import config

logger = logging.getLogger(__name__)

# Configuration
CHUNK_SIZE = getattr(config, "CHUNK_SIZE_LINES", 220)
CHUNK_OVERLAP = getattr(config, "CHUNK_OVERLAP_LINES", 40)
MIN_CHUNK_SIZE = 10


@dataclass
class CodeChunk:
    """Represents a chunk of code."""

    index: int
    content: str
    start_line: int
    end_line: int

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


def split_code_to_chunks(
    code: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[CodeChunk]:
    """
    Split code into overlapping chunks.

    Strategy:
    - Each chunk contains up to chunk_size lines
    - Overlap between consecutive chunks keeps context
    """
    if not code or not code.strip():
        return []

    lines = code.splitlines()
    total_lines = len(lines)

    if total_lines <= chunk_size:
        return [
            CodeChunk(index=0, content=code, start_line=1, end_line=total_lines)
        ]

    chunks: List[CodeChunk] = []
    step = chunk_size - overlap

    if step <= 0:
        step = max(1, chunk_size // 2)

    chunk_index = 0
    start = 0

    while start < total_lines:
        end = min(start + chunk_size, total_lines)
        chunk_lines = lines[start:end]

        if len(chunk_lines) >= MIN_CHUNK_SIZE:
            chunks.append(
                CodeChunk(
                    index=chunk_index,
                    content="\n".join(chunk_lines),
                    start_line=start + 1,
                    end_line=end,
                )
            )
            chunk_index += 1

        start += step

        if total_lines - start < MIN_CHUNK_SIZE:
            break

    logger.debug("Split %s lines into %s chunks", total_lines, len(chunks))
    return chunks


def create_embedding_text(
    code_chunk: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    language: Optional[str] = None,
) -> str:
    """
    Build combined text for embedding.

    Combines metadata (title/description/tags) with code to enable cross-language search.
    """
    parts: List[str] = []

    if title:
        parts.append(f"Title: {title}")

    if description:
        parts.append(f"Description: {description}")

    if tags:
        parts.append(f"Tags: {', '.join(tags)}")

    if language:
        parts.append(f"Language: {language}")

    if code_chunk:
        parts.append(f"\nCode:\n{code_chunk}")

    return "\n".join(parts)

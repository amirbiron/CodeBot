"""CodeKeeper MCP server package.

A small, self-contained Model Context Protocol (MCP) server that exposes a
user's saved code files and collections to MCP clients (Claude Code / Claude
Desktop today; Claude.ai via OAuth in a later phase).

Design goals for this package:
- Read-only for now (Phase 0). No write/delete tools.
- Every module here imports only light dependencies at module top-level, so the
  pieces can be unit-tested in isolation without pulling in the whole app.
  The heavy ``database`` package is imported lazily inside ``backend`` /
  ``app`` (only when actually serving), never at import time.
- Authentication is a Personal Access Token (Bearer) verified against the
  ``mcp_tokens`` collection. The authenticated ``user_id`` is derived from the
  token only, never from client input.
"""

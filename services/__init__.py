from typing import List, Optional
from .backoff_state import BackoffState

__all__: List[str] = [
    "backup_service",
    "code_service",
    "github_service",
]

# Optional export: github_backoff_state singleton
github_backoff_state: Optional[BackoffState]
try:  # pragma: no cover
    from .backoff_state import state as _state
    github_backoff_state = _state
except Exception:  # pragma: no cover
    github_backoff_state = None

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Pattern
import re
import json

try:  # Optional dependency; JSON is a valid subset of YAML
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


class ErrorSignatures:
    """Load and classify log lines based on regex signatures.

    The configuration file is expected to be YAML, but JSON is accepted as well
    (JSON is a subset of YAML). When PyYAML is unavailable, a JSON parser is used
    as a fallback. The file schema:

    {
      "critical": ["regex1", "regex2"],
      "network_db": ["regex..."],
      "app_runtime": ["regex..."],
      "noise_allowlist": ["regex..."]
    }
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.compiled: Dict[str, List[Pattern[str]]] = {}
        self.allowlist: List[Pattern[str]] = []
        self._load()

    def _compile_list(self, patterns: List[str]) -> List[Pattern[str]]:
        out: List[Pattern[str]] = []
        for patt in patterns or []:
            try:
                out.append(re.compile(patt, re.IGNORECASE))
            except re.error:
                # Skip invalid regex patterns silently (fail-open)
                continue
        return out

    def _load(self) -> None:
        if not self.path.exists():
            # Keep empty configuration (fail-open)
            self.compiled = {}
            self.allowlist = []
            return
        text = self.path.read_text(encoding="utf-8")
        data: Dict[str, List[str]]
        try:
            if yaml is not None:  # type: ignore[truthy-bool]
                data = yaml.safe_load(text) or {}
            else:
                data = json.loads(text or "{}")
        except Exception:
            # On parse error keep empty config
            data = {}
        # Compile categories except the allowlist key
        self.compiled = {k: self._compile_list(v) for k, v in data.items() if k != "noise_allowlist"}
        self.allowlist = self._compile_list(list(data.get("noise_allowlist", [])))

    def reload(self) -> None:
        """Reload configuration from disk (best-effort)."""
        try:
            self._load()
        except Exception:
            return

    def classify(self, line: str) -> Optional[str]:
        """Return the first category name that matches the line, or None."""
        try:
            for category, patterns in self.compiled.items():
                for p in patterns:
                    if p.search(line):
                        return category
            return None
        except Exception:
            return None

    def is_noise(self, line: str) -> bool:
        """Return True if the line matches a known noise/allowlist pattern."""
        try:
            for p in self.allowlist:
                if p.search(line):
                    return True
            return False
        except Exception:
            return False

    def categories(self) -> List[str]:
        return list(self.compiled.keys())

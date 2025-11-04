from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple

try:  # Optional dependency; YAML is preferred but JSON (subset) is supported
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


def _parse_scalar(token: str) -> Any:
    if token == "":
        return ""
    lowered = token.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none"}:
        return None
    if token.startswith(("'", '"')) and token.endswith(("'", '"')) and len(token) >= 2:
        body = token[1:-1]
        if token[0] == '"':
            try:
                return bytes(body, "utf-8").decode("unicode_escape")
            except Exception:
                return body
        return body
    try:
        if token.startswith("0") and len(token) > 1:
            raise ValueError
        return int(token)
    except Exception:
        pass
    try:
        return float(token)
    except Exception:
        pass
    return token


def _predict_container(entries: List[Tuple[int, str]], start_index: int, parent_indent: int) -> str:
    for next_indent, next_token in entries[start_index:]:
        if next_indent <= parent_indent:
            break
        if next_token.startswith("- "):
            return "list"
        return "dict"
    return "dict"


def _minimal_yaml_load(text: str) -> Dict[str, Any]:
    entries: List[Tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw:
            continue
        if raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        token = raw.strip()
        if not token:
            continue
        entries.append((indent, token))

    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Any]] = [(-1, root)]

    for idx, (indent, token) in enumerate(entries):
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if token.startswith("- "):
            if not isinstance(parent, list):
                raise ValueError("list item without list parent")
            value_part = token[2:].strip()
            if not value_part:
                new_item: Dict[str, Any] = {}
                parent.append(new_item)
                stack.append((indent, new_item))
                continue
            if ":" in value_part:
                key, val_part = value_part.split(":", 1)
                key = key.strip()
                val_part = val_part.strip()
                new_item = {key: _parse_scalar(val_part) if val_part else {}}
                parent.append(new_item)
                stack.append((indent, new_item))
                if val_part == "":
                    container_type = _predict_container(entries, idx + 1, indent)
                    next_container: Any = [] if container_type == "list" else {}
                    new_item[key] = next_container
                    stack.append((indent, next_container))
                else:
                    if isinstance(new_item[key], (dict, list)):
                        stack.append((indent, new_item[key]))
                continue
            parent.append(_parse_scalar(value_part))
            continue

        if ":" not in token:
            raise ValueError("unsupported YAML token")
        key, value_part = token.split(":", 1)
        key = key.strip()
        value_part = value_part.strip()
        if not isinstance(parent, dict):
            raise ValueError("mapping without dict parent")

        if value_part == "":
            container_type = _predict_container(entries, idx + 1, indent)
            new_container2: Any = [] if container_type == "list" else {}
            parent[key] = new_container2
            stack.append((indent, new_container2))
        else:
            value = _parse_scalar(value_part)
            parent[key] = value
            if isinstance(value, (dict, list)):
                stack.append((indent, value))

    return root


@dataclass(frozen=True)
class SignatureRule:
    id: str
    category: str
    pattern: Pattern[str]
    raw_pattern: str
    summary: str
    severity: str
    policy: str
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class SignatureMatch:
    category: str
    signature_id: str
    severity: str
    policy: str
    summary: str
    pattern: Pattern[str]
    metadata: Dict[str, Any]


class ErrorSignatures:
    """Load and classify log lines based on regex signatures and taxonomy.

    The configuration file supports a structured YAML format:

    noise_allowlist:
      - 'client disconnected|Broken pipe'

    categories:
      retryable:
        default_severity: anomaly
        default_policy: retry
        signatures:
          - id: network_reset
            summary: ...
            pattern: 'ECONNRESET|ETIMEDOUT'

    Backwards compatibility: a legacy JSON/YAML dict of the form

      {"critical": ["regex1"], "noise_allowlist": ["..."]}

    is also accepted and will be converted into the structured schema on load.
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self._rules_by_category: Dict[str, List[SignatureRule]] = {}
        self._signature_index: Dict[str, SignatureRule] = {}
        self._category_defaults: Dict[str, Dict[str, str]] = {}
        self.allowlist: List[Pattern[str]] = []
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def reload(self) -> None:
        """Reload configuration from disk (best-effort)."""
        try:
            self._load()
        except Exception:  # pragma: no cover - fail open
            return

    def match(self, line: str) -> Optional[SignatureMatch]:
        """Return full signature metadata for the first match, or None."""

        if not line:
            return None
        try:
            for category, rules in self._rules_by_category.items():
                for rule in rules:
                    if rule.pattern.search(line):
                        return SignatureMatch(
                            category=category,
                            signature_id=rule.id,
                            severity=rule.severity or self._category_defaults.get(category, {}).get("severity", "anomaly"),
                            policy=rule.policy or self._category_defaults.get(category, {}).get("policy", "escalate"),
                            summary=rule.summary,
                            pattern=rule.pattern,
                            metadata=dict(rule.metadata),
                        )
        except Exception:  # pragma: no cover - classification should not break logging
            return None
        return None

    def classify(self, line: str) -> Optional[str]:
        """Return the category name for the first matching signature, or None."""

        match = self.match(line)
        return match.category if match else None

    def is_noise(self, line: str) -> bool:
        """True if the line matches an allowlisted/noise pattern."""

        if not line:
            return False
        try:
            for patt in self.allowlist:
                if patt.search(line):
                    return True
        except Exception:  # pragma: no cover
            return False
        return False

    def categories(self) -> List[str]:
        return list(self._rules_by_category.keys())

    def category_defaults(self) -> Dict[str, Dict[str, str]]:
        """Expose category metadata (severity/policy/description)."""

        return dict(self._category_defaults)

    def signature_details(self, signature_id: str) -> Optional[SignatureRule]:
        return self._signature_index.get(signature_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            self._rules_by_category = {}
            self._signature_index = {}
            self._category_defaults = {}
            self.allowlist = []
            return

        text = self.path.read_text(encoding="utf-8")
        data = self._parse_config(text)

        self.allowlist = self._compile_allowlist(data.get("noise_allowlist", []))

        raw_categories = data.get("categories")
        if raw_categories is None:
            # Legacy schema fallback: top-level keys (except noise) are categories with pattern lists
            raw_categories = {
                str(k): {"signatures": v}
                for k, v in data.items()
                if k != "noise_allowlist"
            }
        if not isinstance(raw_categories, dict):
            raw_categories = {}

        rules_by_category: Dict[str, List[SignatureRule]] = {}
        signature_index: Dict[str, SignatureRule] = {}
        category_defaults: Dict[str, Dict[str, str]] = {}

        for raw_name, cfg in raw_categories.items():
            category = self._normalize_category(raw_name)
            if not category:
                continue
            defaults = self._extract_category_defaults(cfg)
            entries = self._extract_signature_entries(cfg)
            compiled_rules: List[SignatureRule] = []
            for idx, entry in enumerate(entries):
                rule = self._build_rule(category, entry, idx, defaults, signature_index)
                if rule is None:
                    continue
                compiled_rules.append(rule)
                signature_index[rule.id] = rule
            if compiled_rules:
                rules_by_category[category] = compiled_rules
                category_defaults[category] = defaults

        self._rules_by_category = rules_by_category
        self._signature_index = signature_index
        self._category_defaults = category_defaults

    @staticmethod
    def _parse_config(text: str) -> Dict[str, Any]:
        if not text:
            return {}
        loaders: List[Any] = []
        if yaml is not None:  # type: ignore[truthy-bool]
            loaders.append(lambda: yaml.safe_load(text) or {})
        if yaml is None:
            loaders.append(lambda: _minimal_yaml_load(text))
        loaders.append(lambda: json.loads(text or "{}"))

        for loader in loaders:
            try:
                loaded = loader()
            except Exception:
                continue
            if isinstance(loaded, dict):
                return loaded
        return {}

    @staticmethod
    def _normalize_category(name: Any) -> str:
        try:
            text = str(name or "").strip()
        except Exception:
            return ""
        return text if text else ""

    @staticmethod
    def _extract_category_defaults(cfg: Any) -> Dict[str, str]:
        if not isinstance(cfg, dict):
            return {"severity": "anomaly", "policy": "escalate", "description": ""}
        severity = str(cfg.get("default_severity") or cfg.get("severity") or "anomaly").lower()
        policy = str(cfg.get("default_policy") or cfg.get("policy") or "escalate").lower()
        description = str(cfg.get("description") or "")
        return {"severity": severity, "policy": policy, "description": description}

    @staticmethod
    def _extract_signature_entries(cfg: Any) -> List[Any]:
        if isinstance(cfg, dict):
            entries = cfg.get("signatures", [])
            return entries if isinstance(entries, list) else []
        if isinstance(cfg, list):
            return cfg
        return []

    def _build_rule(
        self,
        category: str,
        entry: Any,
        idx: int,
        defaults: Dict[str, str],
        existing: Dict[str, SignatureRule],
    ) -> Optional[SignatureRule]:
        raw_pattern: str
        summary = ""
        severity = defaults.get("severity", "anomaly")
        policy = defaults.get("policy", "escalate")
        metadata: Dict[str, Any] = {}

        if isinstance(entry, str):
            raw_pattern = entry
            sig_id = f"{category}_{idx}"
        elif isinstance(entry, dict):
            raw_pattern = str(entry.get("pattern") or entry.get("regex") or "")
            if not raw_pattern:
                return None
            sig_id = str(entry.get("id") or f"{category}_{idx}")
            summary = str(entry.get("summary") or entry.get("description") or "")
            if entry.get("severity"):
                severity = str(entry.get("severity")).lower()
            if entry.get("policy"):
                policy = str(entry.get("policy")).lower()
            metadata = {
                str(k): v
                for k, v in entry.items()
                if k not in {"id", "pattern", "regex", "summary", "description", "severity", "policy"}
            }
        else:
            return None

        try:
            raw_pattern = str(raw_pattern or "").strip()
        except Exception:
            raw_pattern = ""
        if not raw_pattern:
            return None

        try:
            compiled = re.compile(raw_pattern, re.IGNORECASE)
        except re.error:
            return None

        sig_id = self._dedupe_signature_id(sig_id, existing)

        return SignatureRule(
            id=sig_id,
            category=category,
            pattern=compiled,
            raw_pattern=raw_pattern,
            summary=summary,
            severity=severity,
            policy=policy,
            metadata=metadata,
        )

    @staticmethod
    def _dedupe_signature_id(sig_id: Any, existing: Dict[str, SignatureRule]) -> str:
        try:
            base = str(sig_id or "signature").strip()
        except Exception:
            base = "signature"
        if not base:
            base = "signature"
        candidate = base
        counter = 1
        while candidate in existing:
            candidate = f"{base}_{counter}"
            counter += 1
        return candidate

    @staticmethod
    def _compile_allowlist(entries: Any) -> List[Pattern[str]]:
        patterns: List[Pattern[str]] = []
        if not isinstance(entries, list):
            return patterns
        for item in entries:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if not text:
                continue
            try:
                patterns.append(re.compile(text, re.IGNORECASE))
            except re.error:
                continue
        return patterns

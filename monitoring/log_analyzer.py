from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
import collections
import hashlib
import json
import re
import time

from .error_signatures import ErrorSignatures, SignatureMatch

try:  # Optional dependency; JSON is a valid subset of YAML
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


@dataclass
class _Group:
    category: str
    signature: str = ""
    summary: str = ""
    severity_hint: str = ""
    policy: str = ""
    count: int = 0
    first_ts: float = 0.0
    last_ts: float = 0.0
    samples: Deque[str] = field(default_factory=lambda: collections.deque(maxlen=3))
    last_alert_ts: float = 0.0


class LogEventAggregator:
    """Group and deduplicate log events based on regex classification and fingerprints.

    Behavior:
    - Noise lines are ignored (allowlist)
    - Classify by category (from ErrorSignatures)
    - Fingerprint based on category + canonicalization of the line
    - Maintain rolling window per fingerprint
    - Emit a single grouped alert when count >= min_count within window
    - Immediate categories trigger alert at first occurrence
    - Cooldown prevents repeated alerts for the same fingerprint
    - Alerts are sent via internal_alerts (critical or anomaly)
    """

    def __init__(
        self,
        *,
        signatures_path: str,
        alerts_config_path: str,
        shadow: bool = False,
        now_fn: Optional[callable] = None,
    ) -> None:
        self.signatures = ErrorSignatures(signatures_path)
        self.alerts_cfg = self._load_alerts_config(alerts_config_path)
        self.now = now_fn or (lambda: time.time())
        # When shadow is enabled, grouping occurs but alerts are not emitted to sinks.
        self.shadow = bool(shadow)
        self._groups: Dict[str, _Group] = {}
        self._canon_patterns: List[re.Pattern[str]] = [
            re.compile(r"(Out of memory|OOMKilled)", re.I),
            re.compile(r"(gunicorn.*worker timeout)", re.I),
            re.compile(r"(certificate verify failed|x509: .* expired)", re.I),
            re.compile(r"(ECONNRESET|ETIMEDOUT|EAI_AGAIN|socket hang up)", re.I),
            re.compile(r"(Too many open files|ENFILE|EMFILE)", re.I),
            re.compile(r"(No space left on device|ENOSPC)", re.I),
            re.compile(r"(Traceback \(|UnhandledPromiseRejection|TypeError:|ReferenceError:)", re.I),
            re.compile(r"(Exited with code (?!0)\d+)", re.I),
        ]

    # --- Config loading ---
    @staticmethod
    def _load_alerts_config(path: str) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            # sane defaults
            return {
                "window_minutes": 5,
                "min_count_default": 3,
                "cooldown_minutes": 10,
                "immediate_categories": ["critical"],
            }
        text = p.read_text(encoding="utf-8")
        try:
            if yaml is not None:  # type: ignore[truthy-bool]
                data = yaml.safe_load(text) or {}
            else:
                data = json.loads(text or "{}")
        except Exception:
            data = {}
        # Apply defaults
        default_immediate = ["config", "critical"]
        immediate = data.get("immediate_categories", default_immediate)
        if not isinstance(immediate, list):
            immediate = default_immediate
        return {
            "window_minutes": int(data.get("window_minutes", 5) or 5),
            "min_count_default": int(data.get("min_count_default", 3) or 3),
            "cooldown_minutes": int(data.get("cooldown_minutes", 10) or 10),
            "immediate_categories": list(immediate) or default_immediate,
        }

    # --- Canonicalization and fingerprinting ---
    def _canonicalize(self, line: str) -> str:
        for rx in self._canon_patterns:
            m = rx.search(line)
            if m:
                return m.group(1).lower()
        # generic fallback: strip volatile numbers/hexes to group similar lines
        out = re.sub(r"0x[0-9A-Fa-f]+", "0x?", line)
        out = re.sub(r"\b\d+\b", "#", out)
        return out[:200].lower()

    def _fingerprint(self, line: str, match: SignatureMatch) -> str:
        canon = self._canonicalize(line)
        basis = f"{match.category}|{match.signature_id}|{canon}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]

    # --- Public API ---
    def analyze_line(self, line: str, now_ts: Optional[float] = None) -> Optional[Tuple[str, _Group]]:
        t = float(now_ts if now_ts is not None else self.now())
        if not line:
            return None
        # Filter noise
        if self.signatures.is_noise(line):
            self._evict_expired(t)
            return None

        match = self.signatures.match(line)
        if not match:
            self._evict_expired(t)
            return None
        fp = self._fingerprint(line, match)
        g = self._groups.get(fp)
        severity_hint = str(match.severity or "").lower()
        policy_hint = str(match.policy or "").lower()
        summary_hint = str(match.summary or "")
        category = match.category

        if g is None:
            g = _Group(
                category=category,
                signature=str(match.signature_id or ""),
                summary=summary_hint,
                severity_hint=severity_hint,
                policy=policy_hint,
                count=0,
                first_ts=t,
                last_ts=t,
            )
            self._groups[fp] = g
        else:
            g.category = category
            if match.signature_id:
                g.signature = str(match.signature_id)
            if summary_hint:
                g.summary = summary_hint
            if severity_hint:
                g.severity_hint = severity_hint
            if policy_hint:
                g.policy = policy_hint
        # If the previous alert is in the past and we have lines that arrived during the cooldown,
        # reset the series so a fresh window starts after cooldown. This prevents a stale first_ts
        # (set during cooldown) from blocking a new emission after cooldown has elapsed.
        try:
            cooldown_sec = max(1, int(self.alerts_cfg.get("cooldown_minutes", 10) or 10)) * 60
        except Exception:
            cooldown_sec = 600
        cooldown_end = (g.last_alert_ts or 0.0) + float(cooldown_sec)
        if g.last_alert_ts and t >= cooldown_end and g.count > 0 and g.first_ts < cooldown_end:
            # Drop accumulated state from within the cooldown window
            g.count = 0
            g.first_ts = 0.0
            g.samples.clear()
        # When a new series starts (after previous alert), reset the first_ts to track a fresh window
        if g.count == 0:
            g.first_ts = t
        g.count += 1
        g.last_ts = t
        # Always append; deque(maxlen=3) maintains a rolling window automatically
        g.samples.append(line.strip())
        # Decide whether to emit
        immediate_categories = {str(c) for c in self.alerts_cfg.get("immediate_categories", [])}
        if not g.severity_hint:
            g.severity_hint = severity_hint or "anomaly"
        if not g.policy:
            g.policy = policy_hint or "escalate"

        target_severity = "critical" if (g.severity_hint == "critical" or category in immediate_categories) else "anomaly"
        emitted = self._maybe_emit(fp, g, t, severity=target_severity)
        self._evict_expired(t)
        if emitted:
            return fp, g
        return None

    def _maybe_emit(self, fp: str, g: _Group, t: float, *, severity: str) -> bool:
        cooldown = max(1, int(self.alerts_cfg.get("cooldown_minutes", 10) or 10)) * 60
        if (t - (g.last_alert_ts or 0.0)) < cooldown:
            return False
        if severity == "critical":
            return self._emit(fp, g, t, severity="critical")
        min_count = max(1, int(self.alerts_cfg.get("min_count_default", 3) or 3))
        window_sec = max(60, int(self.alerts_cfg.get("window_minutes", 5) or 5) * 60)
        # Ensure enough occurrences within window
        if g.count >= min_count and (t - g.first_ts) <= window_sec:
            emit_severity = "anomaly" if severity not in {"critical"} else "critical"
            return self._emit(fp, g, t, severity=emit_severity)
        return False

    # --- Emission ---
    def _emit(self, fp: str, g: _Group, t: float, *, severity: str) -> bool:
        try:
            title = self._render_title(g, count=g.count)
            body = self._render_body(g, fingerprint=fp, first_ts=g.first_ts, last_ts=g.last_ts)
            if self.shadow:
                try:
                    # Log an anomaly/critical marker without emitting real alerts; avoid recursion by using a distinct event name
                    import structlog  # type: ignore
                    lvl = "ANOMALY" if severity == "anomaly" else "ERROR"
                    structlog.get_logger().warning(
                        event="log_aggregator_shadow_emit",
                        level=lvl,
                        name=title,
                        summary=body,
                        fingerprint=fp,
                        count=int(g.count),
                        category=str(g.category),
                        signature=str(g.signature or ""),
                        policy=str(g.policy or ""),
                        severity_hint=str(g.severity_hint or ""),
                    )
                except Exception:
                    pass
            else:
                try:
                    from internal_alerts import emit_internal_alert  # type: ignore
                except Exception:  # pragma: no cover
                    emit_internal_alert = None  # type: ignore
                if emit_internal_alert is not None:
                    emit_internal_alert(
                        name=title,
                        severity=severity,
                        summary=body,
                        fingerprint=fp,
                        count=int(g.count),
                        category=str(g.category),
                        signature=str(g.signature or ""),
                        policy=str(g.policy or ""),
                        severity_hint=str(g.severity_hint or ""),
                    )
            g.last_alert_ts = t
            # Reset group state to allow a fresh window for future occurrences
            g.count = 0
            g.first_ts = 0.0
            g.samples.clear()
            return True
        except Exception:
            return False

    # --- Housekeeping ---
    def _evict_expired(self, now_ts: float) -> None:
        window_sec = max(60, int(self.alerts_cfg.get("window_minutes", 5) or 5) * 60)
        to_delete: List[str] = []
        for fp, g in self._groups.items():
            if (now_ts - g.last_ts) > window_sec * 2:
                to_delete.append(fp)
        for fp in to_delete:
            self._groups.pop(fp, None)

    # --- Rendering ---
    def _render_title(self, g: _Group, *, count: int) -> str:
        base_labels = {
            "config": "תקלות קונפיגורציה",
            "retryable": "שגיאות ניתנות לריטרי",
            "third_party": "כשלי ספק חיצוני",
            "transient": "תקלות חולפות",
            "user_error": "שגיאת משתמש",
            "critical": "התראה קריטית",
            "network_db": "בעיות רשת/DB",
            "app_runtime": "שגיאות אפליקציה",
        }
        base = base_labels.get(g.category, "התראות")
        descriptor = g.summary.strip() if g.summary else ""
        if not descriptor and g.signature:
            rule = self.signatures.signature_details(g.signature)
            if rule and rule.summary:
                descriptor = rule.summary
            else:
                descriptor = g.signature.replace("_", " ")
        count_label = f"{int(max(1, count))} מופעים"
        if descriptor:
            return f"{base} — {descriptor} ({count_label})"
        return f"{base} — {count_label}"

    @staticmethod
    def _fmt_ts(ts: float) -> str:
        try:
            import datetime as _dt

            return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat()
        except Exception:
            return str(int(ts))

    def _render_body(self, g: _Group, *, fingerprint: str, first_ts: float, last_ts: float) -> str:
        descriptor = g.summary.strip() if g.summary else ""
        if not descriptor and g.signature:
            rule = self.signatures.signature_details(g.signature)
            if rule and rule.summary:
                descriptor = rule.summary
            else:
                descriptor = g.signature.replace("_", " ")
        samples = "\n".join(list(g.samples)[:3])
        policy = g.policy or self.signatures.category_defaults().get(g.category, {}).get("policy", "")
        severity_hint = g.severity_hint or self.signatures.category_defaults().get(g.category, {}).get("severity", "")
        return (
            f"Fingerprint: {fingerprint}\n"
            f"קטגוריה: {g.category}\n"
            f"חתימה: {descriptor or g.signature or '-'}\n"
            f"מדיניות: {policy or '-'}\n"
            f"סיווג: {severity_hint or '-'}\n"
            f"חלון: {self._fmt_ts(first_ts)} → {self._fmt_ts(last_ts)}\n"
            f"דוגמאות:\n{samples}"
        )

    # --- Introspection for tests ---
    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for fp, g in self._groups.items():
            out[fp] = {
                "category": g.category,
                "signature": g.signature,
                "summary": g.summary,
                "severity_hint": g.severity_hint,
                "policy": g.policy,
                "count": g.count,
                "first_ts": g.first_ts,
                "last_ts": g.last_ts,
                "last_alert_ts": g.last_alert_ts,
                "samples": list(g.samples),
            }
        return out

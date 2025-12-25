from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _parse_iso_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _is_true(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class SentryPollerConfig:
    enabled: bool = False
    interval_seconds: int = 300
    limit: int = 10
    # Severity emitted into internal_alerts ("info"|"warning"|"error"|"critical")
    severity: str = "error"
    # When true: first run will only "seed" state without sending alerts.
    seed_silent: bool = True
    # De-dup window per issue to avoid spam (seconds). 0 disables.
    dedup_seconds: int = 900


class SentryPoller:
    """Poll Sentry recent issues and emit internal alerts on new activity.

    This is a fallback for environments that don't have Sentry Webhook actions.
    """

    def __init__(self, cfg: SentryPollerConfig):
        self.cfg = cfg
        self._seeded = False
        self._last_seen_by_issue: Dict[str, datetime] = {}
        self._last_emitted_by_issue: Dict[str, datetime] = {}

    @staticmethod
    def from_env() -> SentryPollerConfig:
        try:
            enabled = _is_true(__import__("os").getenv("SENTRY_POLL_ENABLED", "false"))
        except Exception:
            enabled = False
        try:
            interval_seconds = int(float(__import__("os").getenv("SENTRY_POLL_INTERVAL_SECS", "300") or 300))
        except Exception:
            interval_seconds = 300
        try:
            limit = int(float(__import__("os").getenv("SENTRY_POLL_LIMIT", "10") or 10))
        except Exception:
            limit = 10
        severity = str(__import__("os").getenv("SENTRY_POLL_SEVERITY", "error") or "error").strip().lower() or "error"
        if severity not in {"info", "warning", "warn", "error", "critical"}:
            severity = "error"
        if severity == "warn":
            severity = "warning"
        try:
            seed_silent = _is_true(__import__("os").getenv("SENTRY_POLL_SEED_SILENT", "true"))
        except Exception:
            seed_silent = True
        try:
            dedup_seconds = int(float(__import__("os").getenv("SENTRY_POLL_DEDUP_SECONDS", "900") or 900))
        except Exception:
            dedup_seconds = 900
        return SentryPollerConfig(
            enabled=bool(enabled),
            interval_seconds=max(30, int(interval_seconds)),
            limit=max(1, min(100, int(limit))),
            severity=str(severity),
            seed_silent=bool(seed_silent),
            dedup_seconds=max(0, int(dedup_seconds)),
        )

    def _should_emit_issue(self, issue_id: str, now: datetime) -> bool:
        if self.cfg.dedup_seconds <= 0:
            return True
        prev = self._last_emitted_by_issue.get(issue_id)
        if prev is None:
            return True
        return (now - prev).total_seconds() >= float(self.cfg.dedup_seconds)

    async def tick(self) -> Dict[str, Any]:
        """One poll iteration. Returns a small stats dict (for logs/tests)."""
        if not self.cfg.enabled:
            return {"ok": True, "enabled": False, "polled": 0, "emitted": 0, "seeded": self._seeded}
        try:
            import integrations_sentry as sentry_client  # type: ignore
        except Exception:
            return {"ok": False, "enabled": True, "error": "import_failed"}

        # If not configured, do nothing (fail-open)
        try:
            if not bool(getattr(sentry_client, "is_configured", lambda: False)()):
                return {"ok": True, "enabled": True, "configured": False, "polled": 0, "emitted": 0, "seeded": self._seeded}
        except Exception:
            return {"ok": True, "enabled": True, "configured": False, "polled": 0, "emitted": 0, "seeded": self._seeded}

        now = datetime.now(timezone.utc)
        try:
            issues = await sentry_client.get_recent_issues(limit=int(self.cfg.limit))  # type: ignore[attr-defined]
        except Exception:
            issues = []
        if not isinstance(issues, list):
            issues = []

        emitted = 0
        polled = 0

        for issue in issues[: int(self.cfg.limit)]:
            if not isinstance(issue, dict):
                continue
            polled += 1
            issue_id = str(issue.get("id") or "").strip()
            if not issue_id:
                continue
            last_seen = _parse_iso_dt(str(issue.get("lastSeen") or ""))
            if last_seen is None:
                continue
            prev_seen = self._last_seen_by_issue.get(issue_id)
            # Update state first
            self._last_seen_by_issue[issue_id] = last_seen

            # First run seeding: do not emit existing issues
            if not self._seeded and self.cfg.seed_silent:
                continue

            if prev_seen is not None and last_seen <= prev_seen:
                continue

            if not self._should_emit_issue(issue_id, now):
                continue

            short_id = str(issue.get("shortId") or "").strip()
            title = str(issue.get("title") or "").strip()
            link = str(issue.get("permalink") or "").strip()

            name = f"Sentry: {short_id or issue_id[:8]}"
            summary = title or "Sentry issue activity"
            details = {
                "is_new_error": True,
                "alert_type": "sentry_issue",
                "source": "sentry_poll",
                "sentry_issue_id": issue_id,
                "sentry_short_id": short_id or None,
                "sentry_permalink": link or None,
                "sentry_last_seen": last_seen.isoformat(),
                "sentry_first_seen": str(issue.get("firstSeen") or "").strip() or None,
            }
            details = {k: v for k, v in details.items() if v not in (None, "")}

            try:
                from internal_alerts import emit_internal_alert  # type: ignore
                emit_internal_alert(name=name, severity=str(self.cfg.severity), summary=summary, **details)
                self._last_emitted_by_issue[issue_id] = now
                emitted += 1
            except Exception:
                continue

        # Mark seeded after first successful iteration (even if 0 issues)
        if not self._seeded:
            self._seeded = True
        return {"ok": True, "enabled": True, "configured": True, "polled": polled, "emitted": emitted, "seeded": self._seeded}


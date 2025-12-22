"""
Rules Evaluator - הערכת כללים על התראות נכנסות
================================================
מחבר בין מערכת ההתראות לבין מנוע הכללים.

🔧 הערה: סינכרוני לחלוטין (PyMongo).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import socket
import ipaddress
from urllib.parse import urlparse
import os

logger = logging.getLogger(__name__)


def evaluate_alert_rules(alert_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    מעריך את כל הכללים הפעילים על התראה נכנסת.

    Args:
        alert_data: נתוני ההתראה מ-internal_alerts או monitoring/alerts_storage

    Returns:
        dict עם תוצאות ההערכה, או None אם אין כללים מתאימים

    🔧 מיפוי שדות מההתראות הקיימות ל-EvaluationContext:
    ```
    ההתראה המקורית           ←→    שדה ב-context
    ─────────────────────────────────────────────────
    name                     ←→    alert_name
    severity                 ←→    severity
    summary                  ←→    summary
    details.alert_type       ←→    alert_type
    details.sentry_issue_id  ←→    sentry_issue_id
    details.sentry_short_id  ←→    sentry_short_id
    details.project          ←→    project
    details.environment      ←→    environment
    details.error_signature  ←→    error_signature
    source                   ←→    source
    silenced                 ←→    is_silenced
    ```
    """
    try:
        from webapp.app import get_db
        from services.rules_storage import get_rules_storage
        from services.rule_engine import EvaluationContext, get_rule_engine
        from monitoring.alerts_storage import enrich_alert_with_signature

        # קבלת כללים פעילים
        storage = get_rules_storage(get_db())
        rules = storage.get_enabled_rules()

        if not rules:
            return None

        # בניית context מההתראה
        details = alert_data.get("details", {}) or {}

        # 🔧 העשרה: חתימה + האם זו שגיאה חדשה (best-effort, לא לשבור אם אין DB)
        try:
            if isinstance(details, dict):
                enrich_alert_with_signature(details)
        except Exception:
            pass

        now = datetime.now(timezone.utc)
        # המדריך מגדיר 0=ראשון, 6=שבת (Python: Monday=0)
        day_of_week = (now.weekday() + 1) % 7

        context_data = {
            # שדות בסיסיים מההתראה
            "alert_name": str(alert_data.get("name", "")),
            "severity": str(alert_data.get("severity", "info")).lower(),
            "summary": str(alert_data.get("summary", "")),
            "source": str(alert_data.get("source", "")),
            "is_silenced": bool(alert_data.get("silenced", False)),
            "hour_of_day": int(now.hour),
            "day_of_week": int(day_of_week),
            # שדות מ-details
            "alert_type": str(details.get("alert_type", "")),
            "sentry_issue_id": str(details.get("sentry_issue_id", "")),
            "sentry_short_id": str(details.get("sentry_short_id", "")),
            "sentry_permalink": str(details.get("sentry_permalink", "")),
            "project": str(details.get("project", "")),
            "environment": str(details.get("environment", "")),
            "error_signature": str(details.get("error_signature", "")),
            "error_signature_hash": str(details.get("error_signature_hash", "")),
            "is_new_error": bool(details.get("is_new_error", False)),
            "error_message": str(details.get("error_message") or details.get("message") or alert_data.get("summary", "") or ""),
            "stack_trace": str(details.get("stack_trace") or ""),
            "first_seen_at": details.get("first_seen_at"),
            "occurrence_count": int(details.get("occurrence_count") or details.get("count") or 1),
            "culprit": str(details.get("culprit", "")),
            "action": str(details.get("action", "")),
            # מדדים (אם קיימים)
            "error_rate": details.get("error_rate", details.get("error_rate_percent", alert_data.get("error_rate"))),
            "requests_per_minute": details.get("requests_per_minute", alert_data.get("requests_per_minute")),
            "latency_avg_ms": details.get("latency_avg_ms", details.get("latency_ms", alert_data.get("latency_avg_ms"))),
        }

        # הערכת כללים
        engine = get_rule_engine()
        matched_rules: List[Dict[str, Any]] = []

        for rule in rules:
            try:
                context = EvaluationContext(data=context_data)
                result = engine.evaluate(rule, context)

                if result.matched:
                    matched_rules.append(
                        {
                            "rule_id": rule.get("rule_id"),
                            "rule_name": rule.get("name"),
                            "triggered_conditions": result.triggered_conditions,
                            "actions": result.actions_to_execute,
                        }
                    )
            except Exception as e:
                logger.warning(f"Error evaluating rule {rule.get('rule_id')}: {e}")
                continue

        if matched_rules:
            return {
                "matched": True,
                "rules": matched_rules,
                "alert_data": alert_data,
            }

        return None

    except Exception as e:
        logger.error(f"Error in evaluate_alert_rules: {e}")
        return None


def _is_safe_webhook_url(url: str) -> bool:
    """
    Basic SSRF guardrail for webhook URLs.

    - Only allow http/https schemes.
    - Reject URLs resolving to private/loopback/link-local/multicast/unspecified IPs.
    - Optionally restrict hostnames via environment-based allowlists:
      * ALLOWED_WEBHOOK_HOSTS: comma-separated exact hostnames.
      * ALLOWED_WEBHOOK_SUFFIXES: comma-separated domain suffixes (e.g. ".example.com").
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname
        if not hostname:
            return False
        hostname = hostname.strip().lower()
        if not hostname:
            return False

        # Optional allowlists for additional control
        try:
            raw_hosts = (os.getenv("ALLOWED_WEBHOOK_HOSTS") or "").strip()
            allowed_hosts = {h.strip().lower() for h in raw_hosts.split(",") if h.strip()} if raw_hosts else set()
        except Exception:
            allowed_hosts = set()
        try:
            raw_suffixes = (os.getenv("ALLOWED_WEBHOOK_SUFFIXES") or "").strip()
            allowed_suffixes = [s.strip().lower() for s in raw_suffixes.split(",") if s.strip()] if raw_suffixes else []
        except Exception:
            allowed_suffixes = []

        if allowed_hosts or allowed_suffixes:
            in_hosts = hostname in allowed_hosts if allowed_hosts else False
            in_suffixes = any(
                hostname.endswith(suffix) or hostname == suffix.lstrip(".")
                for suffix in allowed_suffixes
            ) if allowed_suffixes else False
            if not (in_hosts or in_suffixes):
                return False

        # Resolve all addresses for the hostname and ensure none are internal.
        try:
            addrinfo = socket.getaddrinfo(hostname, parsed.port or 80, type=socket.SOCK_STREAM)
        except Exception:
            # If resolution fails, treat as unsafe to avoid surprises.
            return False

        for family, _, _, _, sockaddr in addrinfo:
            try:
                if family == socket.AF_INET:
                    ip_str = sockaddr[0]
                elif family == socket.AF_INET6:
                    ip_str = sockaddr[0]
                else:
                    # Unknown family – be conservative
                    return False
                ip = ipaddress.ip_address(ip_str)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_multicast
                    or ip.is_unspecified
                ):
                    return False
            except Exception:
                return False
        return True
    except Exception:
        return False


def execute_matched_actions(evaluation_result: Dict[str, Any]) -> None:
    """
    מבצע את הפעולות של כללים שהותאמו.

    Args:
        evaluation_result: תוצאת evaluate_alert_rules()
    """
    if not evaluation_result or not evaluation_result.get("matched"):
        return

    alert_data = evaluation_result.get("alert_data", {})

    for matched_rule in evaluation_result.get("rules", []):
        for action in matched_rule.get("actions", []):
            try:
                action_type = action.get("type", "")

                if action_type == "suppress":
                    # סימון ההתראה כמושתקת
                    alert_data["silenced"] = True
                    alert_data["silenced_by_rule"] = matched_rule.get("rule_id")
                    logger.info(f"Alert suppressed by rule: {matched_rule.get('rule_id')}")

                elif action_type == "send_alert":
                    # שליחה להתראה נוספת (לערוץ ספציפי)
                    _send_custom_notification(action, alert_data, matched_rule)

                elif action_type == "create_github_issue":
                    # יצירת GitHub Issue
                    _create_github_issue(action, alert_data, matched_rule)

                elif action_type == "webhook":
                    _call_webhook(action, alert_data)

            except Exception as e:
                logger.error(f"Error executing action {action_type}: {e}")


def _send_custom_notification(action: Dict, alert_data: Dict, matched_rule: Dict) -> None:
    """שולח התראה מותאמת לערוץ ספציפי."""
    try:
        channel = action.get("channel", "default")
        severity = action.get("severity", alert_data.get("severity", "info"))
        template = action.get("message_template", "{{rule_name}}: {{summary}}")

        # החלפת placeholders
        message = template.replace("{{rule_name}}", matched_rule.get("rule_name", ""))
        message = message.replace("{{summary}}", alert_data.get("summary", ""))
        message = message.replace(
            "{{triggered_conditions}}",
            ", ".join(matched_rule.get("triggered_conditions", [])),
        )

        logger.info(f"Custom notification [{channel}]: {message[:100]}...")
        # כאן תוסיף את הלוגיקה לשליחה בפועל לערוץ המתאים

    except Exception as e:
        logger.error(f"Error sending custom notification: {e}")


def _create_github_issue(action: Dict, alert_data: Dict, matched_rule: Dict) -> None:
    """
    יוצר GitHub Issue (ראה github_issue_action.py).

    🔧 תיקון באג: asyncio.run() נכשל ב-nested event loop!
    - Flask עם ASGI (Hypercorn/uvicorn) כבר מריץ event loop
    - asyncio.run() יזרוק RuntimeError במקרה כזה

    פתרון: שימוש ב-ThreadPoolExecutor להרצת async code.
    """
    try:
        from concurrent.futures import ThreadPoolExecutor
        import asyncio

        from services.github_issue_action import GitHubIssueAction

        handler = GitHubIssueAction()
        triggered = matched_rule.get("triggered_conditions", [])

        def run_async():
            """הרצה בתוך thread חדש עם event loop נקי."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(handler.execute(action, alert_data, triggered))
            finally:
                loop.close()

        # הרצה ב-thread pool כדי לא לחסום את ה-request
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_async)
            result = future.result(timeout=30)  # timeout לבטיחות

            if result and not result.get("success"):
                logger.warning(f"GitHub issue creation failed: {result.get('error')}")
            elif result and result.get("success"):
                logger.info(f"GitHub issue created: {result.get('issue_url')}")

    except Exception as e:
        logger.error(f"Error creating GitHub issue: {e}")


def _call_webhook(action: Dict, alert_data: Dict) -> None:
    """קריאה ל-webhook."""
    try:
        import requests

        url = str(action.get("webhook_url", "") or "").strip()
        if not url:
            return

        if not _is_safe_webhook_url(url):
            logger.warning("Blocked unsafe webhook URL: %s", url)
            return

        requests.post(url, json=alert_data, timeout=10)
    except Exception as e:
        logger.error(f"Error calling webhook: {e}")


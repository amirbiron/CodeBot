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
import json
import re

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = ("token", "password", "secret", "authorization", "api_key", "apikey", "private_key", "key")


def _truthy_env(name: str) -> bool:
    try:
        raw = (os.getenv(name) or "").strip().lower()
        return raw in {"1", "true", "yes", "on"}
    except Exception:
        return False


def _safe_str(value: Any, *, limit: int = 600) -> str:
    try:
        text = str(value)
    except Exception:
        text = "<unprintable>"
    text = text.replace("\n", "\\n")
    if len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def _looks_sensitive_key(key: str) -> bool:
    try:
        lk = str(key or "").lower()
    except Exception:
        return False
    return any(m in lk for m in _SENSITIVE_KEYS)


def _sanitize_for_log(obj: Any) -> Any:
    """Best-effort sanitation for logging: redact obvious secrets + shrink huge fields."""
    try:
        if isinstance(obj, dict):
            out: Dict[str, Any] = {}
            for k, v in obj.items():
                if _looks_sensitive_key(str(k)):
                    out[k] = "<REDACTED>"
                    continue
                # avoid huge blobs
                if str(k).lower() in {"stack_trace", "traceback", "error_message", "message", "content", "raw_data"}:
                    out[k] = _safe_str(v, limit=220)
                    continue
                out[k] = _sanitize_for_log(v)
            return out
        if isinstance(obj, list):
            return [_sanitize_for_log(x) for x in obj[:20]]
        if isinstance(obj, tuple):
            return tuple(_sanitize_for_log(x) for x in obj[:20])
        if isinstance(obj, str):
            # normalize obvious memory addresses to reduce noise in logs
            return re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", _safe_str(obj, limit=600))
        return obj
    except Exception:
        return "<unprintable>"


def evaluate_alert_rules(alert_data: Dict[str, Any], *, verbose: Optional[bool] = None) -> Optional[Dict[str, Any]]:
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
        if verbose is None:
            # ברירת מחדל: שקט. הדלקה רק כשצריך (סימולטור/דיבוג).
            verbose = _truthy_env("RULES_VERBOSE_LOGGING") or _truthy_env("RULES_EVALUATOR_VERBOSE")

        if verbose:
            try:
                logger.warning("Rules evaluator input alert_data=%s", _safe_str(_sanitize_for_log(alert_data)))
            except Exception:
                pass

        # חשוב: לא לייבא מ-webapp.app כאן.
        # בזמן startup ייתכן ש-webapp/app.py עדיין באמצע import ואז get_db לא מוגדר עדיין,
        # מה שגורם ל: "cannot import name 'get_db' from partially initialized module".
        from services.db_provider import get_db
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
                context = EvaluationContext(
                    data=context_data,
                    metadata={"verbose": bool(verbose), "origin": "services.rules_evaluator"},
                )
                if verbose:
                    try:
                        logger.warning(
                            "Evaluating rule '%s' (id=%s)",
                            str(rule.get("name") or rule.get("rule_id") or ""),
                            str(rule.get("rule_id") or ""),
                        )
                    except Exception:
                        pass
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
            if verbose:
                try:
                    logger.warning("Rules evaluator done: matched_rules=%s/%s", len(matched_rules), len(rules))
                except Exception:
                    pass
            return {
                "matched": True,
                "rules": matched_rules,
                "alert_data": alert_data,
            }

        if verbose:
            try:
                logger.warning("Rules evaluator done: matched_rules=0/%s", len(rules))
            except Exception:
                pass
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

        # החלפת placeholders (best-effort)
        rule_name = str(matched_rule.get("rule_name", "") or "")
        summary = str(alert_data.get("summary") or alert_data.get("message") or "")
        triggered = matched_rule.get("triggered_conditions", []) or []
        try:
            triggered_list = [str(x) for x in triggered]
        except Exception:
            triggered_list = []
        try:
            triggered_json = json.dumps(triggered_list, ensure_ascii=False, indent=2) if triggered_list else ""
        except Exception:
            triggered_json = ""

        message = str(template or "")
        message = message.replace("{{rule_name}}", rule_name)
        message = message.replace("{{summary}}", summary)
        message = message.replace("{{severity}}", str(severity))
        message = message.replace("{{triggered_conditions}}", ", ".join(triggered_list))
        message = message.replace("{{triggered_conditions_json}}", triggered_json)

        # Telegram limit is 4096 chars; keep margin for safety
        max_len = 3800
        if len(message) > max_len:
            message = message[: max_len - 1] + "…"

        # MVP: ערוץ ראשון נתמך = Telegram (channel: telegram/default)
        if str(channel).strip().lower() in {"telegram", "default"}:
            _send_telegram_direct(message)
            return

        # ערוצים אחרים עדיין לא ממומשים (לא שוברים Fail-open)
        logger.info("Custom notification skipped (unsupported channel=%s rule_id=%s)", channel, matched_rule.get("rule_id"))

    except Exception as e:
        logger.error(f"Error sending custom notification: {e}")


def _send_telegram_direct(text: str) -> None:
    """Direct dispatch to Telegram Bot API (fail-open).

    חשוב: לא לקרוא כאן ל-emit_internal_alert כדי לא ליצור לולאה.
    """
    token = str(os.getenv("ALERT_TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(os.getenv("ALERT_TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return
    if not text:
        return
    try:
        api = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}

        # Prefer the project's lightweight HTTP helper if available
        try:
            from http_sync import request  # type: ignore
        except Exception:  # pragma: no cover
            request = None  # type: ignore

        from telegram_api import parse_telegram_json_from_response, require_telegram_ok

        if callable(request):
            resp = request("POST", api, json=payload, timeout=5)
        else:
            import requests  # local import to keep module import side-effects minimal

            resp = requests.post(api, json=payload, timeout=5)

        body = parse_telegram_json_from_response(resp, url=api)
        require_telegram_ok(body, url=api)
    except Exception as e:
        # Fail-open: never raise from rules evaluator actions
        try:
            logger.error(
                "Telegram send_alert failed (rule engine, fail-open). error=%s",
                str(e),
            )
        except Exception:
            pass
        return


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


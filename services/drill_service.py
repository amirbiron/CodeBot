from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from http_sync import request as _http_request  # type: ignore
except Exception:  # pragma: no cover
    _http_request = None  # type: ignore

try:
    import requests as _requests  # type: ignore
except Exception:  # pragma: no cover
    _requests = None  # type: ignore

from config.drill_scenarios import DRILL_SCENARIOS

try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover

    def emit_event(event: str, severity: str = "info", **fields: Any) -> None:  # type: ignore
        return None


class DrillDisabledError(RuntimeError):
    pass


class DrillScenarioNotFoundError(KeyError):
    pass


def _env_true(key: str) -> bool:
    try:
        return str(os.getenv(key, "")).strip().lower() in {"1", "true", "yes", "on"}
    except Exception:
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_and_render_placeholders(value: Any, replacements: Dict[str, str]) -> Any:
    """
    מחליף פלייסהולדרים בתוך מבני dict/list בצורה רקורסיבית.
    תומך ב-strings בלבד (מבלי לשנות ints/bools וכו').
    """
    if isinstance(value, str):
        out = value
        for token, rep in replacements.items():
            out = out.replace(token, rep)
        return out
    if isinstance(value, dict):
        return {k: _copy_and_render_placeholders(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy_and_render_placeholders(v, replacements) for v in value]
    return value


def prepare_drill_metadata(scenario_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    מעבד metadata ומחליף פלייסהולדרים (למשל {{current_timestamp}}).
    """
    base = dict(metadata or {})
    base.setdefault("is_drill", True)
    base.setdefault("scenario", scenario_id)
    rendered = _copy_and_render_placeholders(
        base,
        {
            "{{current_timestamp}}": _now_iso(),
            "{{scenario_id}}": str(scenario_id),
        },
    )
    # הבטחה שהדגל תמיד נשאר True גם אחרי templating
    try:
        rendered["is_drill"] = True
    except Exception:
        rendered = dict(rendered)
        rendered["is_drill"] = True
    return rendered


def _base_url() -> str:
    return str(os.getenv("PUBLIC_BASE_URL") or os.getenv("WEBAPP_URL") or "").strip().rstrip("/")


def _send_telegram_message(text: str) -> bool:
    token = str(os.getenv("ALERT_TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(os.getenv("ALERT_TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return False

    api = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        if _http_request is not None:
            _http_request("POST", api, json=payload, timeout=5)
            return True
        if _requests is not None:  # pragma: no cover
            _requests.post(api, json=payload, timeout=5)
            return True
    except Exception:
        return False
    return False


@dataclass(frozen=True)
class DrillRunResult:
    success: bool
    drill_id: str
    scenario_id: str
    alert: Dict[str, Any]
    pipeline: Dict[str, Any]
    telegram_sent: bool


def list_scenarios() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for key, scenario in DRILL_SCENARIOS.items():
        items.append(
            {
                "id": key,
                "title": scenario.get("title"),
                "severity": scenario.get("severity"),
                "alert_type": scenario.get("alert_type"),
                "description": scenario.get("message"),
            }
        )
    return items


def run_drill_scenario(
    scenario_id: str,
    *,
    requested_by: Optional[str] = None,
) -> DrillRunResult:
    """
    מריץ תרגול:
    - שומר את ההתראה ב-alerts_storage (כדי שתופיע ב-Observability)
    - מחשב "Pipeline result" בסיסי (Runbook match + quick fixes) בעזרת observability_dashboard
    - שולח הודעת Telegram מסומנת
    - שומר בהיסטוריית drills (monitoring/drills_storage)
    """
    if not _env_true("DRILL_MODE_ENABLED"):
        raise DrillDisabledError("drill_mode_disabled")

    sid = str(scenario_id or "").strip()
    if not sid:
        raise DrillScenarioNotFoundError("missing_scenario_id")
    scenario = DRILL_SCENARIOS.get(sid)
    if not isinstance(scenario, dict):
        raise DrillScenarioNotFoundError(sid)

    drill_id = str(uuid.uuid4())
    ts_iso = _now_iso()
    title = str(scenario.get("title") or "").strip() or f"🎭 DRILL: {sid}"
    if not title.startswith("🎭"):
        title = f"🎭 {title}"
    severity = str(scenario.get("severity") or "info").strip().lower() or "info"
    alert_type = str(scenario.get("alert_type") or "").strip().lower()
    message = str(scenario.get("message") or "").strip()

    metadata = prepare_drill_metadata(sid, scenario.get("metadata") if isinstance(scenario.get("metadata"), dict) else {})
    # תאימות ל-observability_dashboard: הוא מצפה ל-alert_type בתוך metadata לפעמים
    if alert_type and "alert_type" not in metadata:
        metadata["alert_type"] = alert_type
    metadata.setdefault("source", "drill")
    metadata.setdefault("drill_id", drill_id)

    alert_snapshot = {
        "alert_uid": drill_id,
        "timestamp": ts_iso,
        "name": title,
        "severity": severity,
        "summary": message,
        "alert_type": alert_type or (metadata.get("alert_type") or ""),
        "metadata": metadata,
        "source": "drill",
        "silenced": False,
    }

    # Persist to alerts DB (best-effort)
    try:
        from monitoring.alerts_storage import record_alert  # type: ignore

        record_alert(
            alert_id=drill_id,
            name=title,
            severity=severity,
            summary=message,
            source="drill",
            silenced=False,
            details=metadata,
        )
    except Exception:
        pass

    # Compute a lightweight pipeline snapshot (runbook match + quick fixes)
    pipeline: Dict[str, Any] = {
        "runbook_matched": False,
        "quick_fixes_count": 0,
    }
    try:
        from services import observability_dashboard as _obs_dash  # type: ignore

        runbook_payload = _obs_dash.fetch_runbook_for_event(
            event_id=drill_id,
            fallback_metadata={
                "type": "alert",
                "title": title,
                "summary": message,
                "timestamp": ts_iso,
                "severity": severity,
                "metadata": metadata,
                "source": "drill",
            },
        )
        if isinstance(runbook_payload, dict):
            pipeline["runbook_matched"] = bool(runbook_payload.get("runbook"))
            pipeline["quick_fixes_count"] = len(runbook_payload.get("actions") or [])
    except Exception:
        pass

    url = _base_url()
    alert_link = f"{url}/admin/observability?focus_ts={ts_iso}#history" if url else "/admin/observability"

    telegram_text = (
        "🎭 DRILL MODE — תרגול בלבד\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{title}\n\n"
        f"📊 פרטים:\n{message or '—'}\n\n"
        "🎯 מה לבדוק:\n"
        "- Config Radar הציג Runbook נכון?\n"
        "- Quick Fixes מוצגים ועובדים (לינקים/העתקה)?\n"
        "- Incident Replay נראה תקין?\n\n"
        f"🔗 Observability: {alert_link}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Runbook matched: {'כן' if pipeline.get('runbook_matched') else 'לא'}\n"
        f"🧩 Quick fixes: {int(pipeline.get('quick_fixes_count') or 0)}\n\n"
        "⚠️ זה לא אירוע אמיתי — רק תרגול"
    )
    telegram_sent = _send_telegram_message(telegram_text)

    # Persist drill history (best-effort)
    try:
        from monitoring.drills_storage import record_drill  # type: ignore

        record_drill(
            drill_id=drill_id,
            scenario_id=sid,
            started_at_iso=ts_iso,
            alert=alert_snapshot,
            pipeline=pipeline,
            telegram_sent=bool(telegram_sent),
            requested_by=requested_by,
        )
    except Exception:
        pass

    try:
        emit_event(
            "drill_run",
            severity="anomaly",
            handled=True,
            drill_id=drill_id,
            scenario_id=sid,
            alert_type=alert_type,
            telegram_sent=bool(telegram_sent),
        )
    except Exception:
        pass

    return DrillRunResult(
        success=True,
        drill_id=drill_id,
        scenario_id=sid,
        alert=alert_snapshot,
        pipeline=pipeline,
        telegram_sent=bool(telegram_sent),
    )


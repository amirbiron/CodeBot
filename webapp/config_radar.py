from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # PyYAML is preferred but not mandatory
    import yaml  # type: ignore
except Exception:  # pragma: no cover - fallback to JSON only
    yaml = None  # type: ignore

__all__ = ["build_config_radar_snapshot"]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALERTS_PATH = "config/alerts.yml"
DEFAULT_ERROR_SIGNATURES_PATH = "config/error_signatures.yml"
DEFAULT_IMAGE_SETTINGS_PATH = "config/image_settings.yaml"
DEFAULT_ALERT_QUICK_FIXES_PATH = "config/alert_quick_fixes.json"
DEFAULT_RUNBOOKS_PATH = "config/observability_runbooks.yml"


@dataclass
class SectionResult:
    payload: Dict[str, Any]
    issues: List[Dict[str, str]]


def build_config_radar_snapshot() -> Dict[str, Any]:
    """Loads the three configuration files, validates them and returns a merged snapshot."""
    alerts_path = _resolve_path("ALERTS_GROUPING_CONFIG", DEFAULT_ALERTS_PATH)
    error_signatures_path = _resolve_path("ERROR_SIGNATURES_PATH", DEFAULT_ERROR_SIGNATURES_PATH)
    image_settings_path = _resolve_path("IMAGE_SETTINGS_PATH", DEFAULT_IMAGE_SETTINGS_PATH)
    quick_fix_path = _resolve_path("ALERT_QUICK_FIX_PATH", DEFAULT_ALERT_QUICK_FIXES_PATH)
    runbooks_path = _resolve_path("OBSERVABILITY_RUNBOOK_PATH", DEFAULT_RUNBOOKS_PATH)

    alerts_section, immediate_categories = _build_alerts_section(alerts_path)
    error_section = _build_error_signatures_section(error_signatures_path, immediate_categories)
    image_section = _build_image_settings_section(image_settings_path)
    quick_fix_section = _build_quick_fixes_section(quick_fix_path)
    runbook_section = _build_runbooks_section(runbooks_path)

    per_file_validation = {
        alerts_section.payload["path"]: _summarize_issues(alerts_section.issues),
        error_section.payload["path"]: _summarize_issues(error_section.issues),
        image_section.payload["path"]: _summarize_issues(image_section.issues),
        quick_fix_section.payload["path"]: _summarize_issues(quick_fix_section.issues),
        runbook_section.payload["path"]: _summarize_issues(runbook_section.issues),
    }

    all_issues: List[Dict[str, str]] = (
        alerts_section.issues
        + error_section.issues
        + image_section.issues
        + quick_fix_section.issues
        + runbook_section.issues
    )
    overall_status = "ok" if not any(_is_error(i) for i in all_issues) else "error"

    return {
        "ok": overall_status == "ok",
        "checked_at": _iso_now(),
        "alerts": alerts_section.payload,
        "error_signatures": error_section.payload,
        "image_settings": image_section.payload,
        "quick_fixes": quick_fix_section.payload,
        "runbooks": runbook_section.payload,
        "validation": {
            "status": overall_status,
            "issues": all_issues,
            "files": per_file_validation,
        },
    }


def _build_alerts_section(path: Path) -> Tuple[SectionResult, set[str]]:
    data, issues = _load_mapping(path, required_name="alerts.yml")
    summary = {
        "path": _relative_path(path),
        "window_minutes": _coerce_positive_int(data.get("window_minutes")),
        "min_count_default": _coerce_positive_int(data.get("min_count_default")),
        "cooldown_minutes": _coerce_non_negative_int(data.get("cooldown_minutes")),
        "immediate_categories": _normalize_string_list(
            data.get("immediate_categories"), preserve_case=True
        ),
        "git": _git_metadata(path),
    }

    if summary["window_minutes"] is None:
        issues.append(_issue(path.name, "window_minutes", "חייב להיות מספר שלם וחיובי"))
    if summary["min_count_default"] is None:
        issues.append(_issue(path.name, "min_count_default", "חייב להיות מספר שלם וחיובי"))
    if summary["cooldown_minutes"] is None:
        issues.append(
            _issue(path.name, "cooldown_minutes", "חייב להיות מספר שלם אפסי או חיובי")
        )
    if not summary["immediate_categories"]:
        issues.append(_issue(path.name, "immediate_categories", "נדרש לפחות ערך אחד"))

    immediate_set = {c.lower() for c in summary["immediate_categories"]}

    return SectionResult(summary, issues), immediate_set


def _build_error_signatures_section(path: Path, immediate_categories: set[str]) -> SectionResult:
    data, issues = _load_mapping(path, required_name="error_signatures.yml")

    allowlist = _normalize_string_list(data.get("noise_allowlist"), preserve_case=True)
    for idx, expr in enumerate(allowlist):
        try:
            re.compile(expr)
        except re.error as exc:
            issues.append(
                _issue(path.name, f"noise_allowlist[{idx}]", f"Regex לא תקין: {exc}")
            )

    raw_categories = data.get("categories")
    if not isinstance(raw_categories, dict):
        raw_categories = {}
    if not raw_categories:
        issues.append(_issue(path.name, "categories", "לא הוגדרו קטגוריות שגיאה"))

    categories_summary: List[Dict[str, Any]] = []
    for name, cfg in raw_categories.items():
        if not isinstance(cfg, dict):
            issues.append(_issue(path.name, f"categories.{name}", "ערך חייב להיות אובייקט"))
            continue
        default_severity = str(
            cfg.get("default_severity") or cfg.get("severity") or "anomaly"
        ).lower()
        default_policy = str(
            cfg.get("default_policy") or cfg.get("policy") or "escalate"
        ).lower()
        description = str(cfg.get("description") or "")
        signatures_raw = cfg.get("signatures") or []
        if not isinstance(signatures_raw, list):
            issues.append(_issue(path.name, f"categories.{name}.signatures", "חייב להיות מערך"))
            continue
        signatures_summary, sig_issues = _summarize_signatures(
            path.name,
            name,
            signatures_raw,
            default_severity,
            default_policy,
        )
        issues.extend(sig_issues)
        categories_summary.append(
            {
                "name": str(name),
                "description": description,
                "default_severity": default_severity,
                "default_policy": default_policy,
                "total_signatures": len(signatures_summary),
                "is_immediate": str(name).lower() in immediate_categories,
                "signatures": signatures_summary,
            }
        )

    summary = {
        "path": _relative_path(path),
        "noise_allowlist": allowlist,
        "categories": categories_summary,
        "git": _git_metadata(path),
    }
    return SectionResult(summary, issues)


def _build_image_settings_section(path: Path) -> SectionResult:
    data, issues = _load_mapping(path, required_name="image_settings.yaml")
    root = data.get("image_generation")
    if not isinstance(root, dict):
        issues.append(_issue(path.name, "image_generation", "השורש image_generation חסר או לא תקין"))
        root = {}

    preview = root.get("preview") if isinstance(root.get("preview"), dict) else {}
    image_all = root.get("image_all") if isinstance(root.get("image_all"), dict) else {}

    summary = {
        "path": _relative_path(path),
        "default_theme": (root.get("default_theme") or "dark"),
        "default_style": (root.get("default_style") or "monokai"),
        "default_width": _coerce_positive_int(root.get("default_width")),
        "default_font_size": _coerce_positive_int(root.get("default_font_size")),
        "line_height": _coerce_positive_int(root.get("line_height")),
        "padding": _coerce_non_negative_int(root.get("padding")),
        "supported_formats": _normalize_string_list(root.get("supported_formats"), preserve_case=True),
        "width_options": _normalize_int_list(root.get("width_options")),
        "preview": {
            "enabled": bool(preview.get("enabled", False)),
            "max_lines": _coerce_positive_int(preview.get("max_lines")),
            "width": _coerce_positive_int(preview.get("width")),
        },
        "image_all": {
            "max_lines": _coerce_positive_int(image_all.get("max_lines")),
            "max_images": _coerce_positive_int(image_all.get("max_images")),
            "max_total_chars": _coerce_positive_int(image_all.get("max_total_chars")),
        },
        "git": _git_metadata(path),
    }

    _require(summary, "default_width", issues, path.name)
    _require(summary, "default_font_size", issues, path.name)
    _require(summary, "line_height", issues, path.name)
    _require(summary, "padding", issues, path.name, allow_zero=True)
    if not summary["supported_formats"]:
        issues.append(_issue(path.name, "supported_formats", "יש להגדיר לפחות פורמט אחד נתמך"))
    if not summary["width_options"]:
        issues.append(_issue(path.name, "width_options", "יש להגדיר רוחבים נתמכים"))

    for section, record in (("preview", summary["preview"]), ("image_all", summary["image_all"])):
        for field_name, allow_zero in (
            ("max_lines", False),
            ("width", False),
            ("max_images", False),
            ("max_total_chars", False),
        ):
            if field_name not in record:
                continue
            if record[field_name] is None:
                issues.append(
                    _issue(path.name, f"{section}.{field_name}", "ערך חייב להיות מספר שלם וחיובי")
                )
            elif not allow_zero and record[field_name] <= 0:  # type: ignore[operator]
                issues.append(
                    _issue(path.name, f"{section}.{field_name}", "ערך חייב להיות גדול מאפס")
                )

    return SectionResult(summary, issues)


def _build_quick_fixes_section(path: Path) -> SectionResult:
    data, issues = _load_mapping(path, required_name="alert_quick_fixes.json")

    version = data.get("version")
    if not isinstance(version, int):
        issues.append(_issue(path.name, "version", "יש להגדיר מספר גרסה (version) תקני"))

    raw_by_alert = data.get("by_alert_type")
    if not isinstance(raw_by_alert, dict):
        issues.append(_issue(path.name, "by_alert_type", "חייב להיות מפתח מסוג אובייקט"))
        raw_by_alert = {}

    raw_by_severity = data.get("by_severity")
    if not isinstance(raw_by_severity, dict):
        raw_by_severity = {}

    fallback_actions = data.get("fallback")
    if not isinstance(fallback_actions, list):
        fallback_actions = []

    alert_types_summary: List[Dict[str, Any]] = []
    for name, actions in raw_by_alert.items():
        if not isinstance(actions, list):
            issues.append(_issue(path.name, f"by_alert_type.{name}", "חייב להיות מערך פעולות"))
            continue
        action_summaries: List[Dict[str, Any]] = []
        for idx, action in enumerate(actions[:3]):
            action_summaries.append(_summarize_quick_fix_action(path.name, f"by_alert_type.{name}[{idx}]", action, issues))
        alert_types_summary.append(
            {
                "name": str(name),
                "actions_count": len(actions),
                "sample_actions": [a for a in action_summaries if a],
            }
        )

    severity_summary: List[Dict[str, Any]] = []
    for severity, actions in raw_by_severity.items():
        if not isinstance(actions, list):
            issues.append(_issue(path.name, f"by_severity.{severity}", "חייב להיות מערך פעולות"))
            continue
        action_summaries: List[Dict[str, Any]] = []
        for idx, action in enumerate(actions[:3]):
            action_summaries.append(_summarize_quick_fix_action(path.name, f"by_severity.{severity}[{idx}]", action, issues))
        severity_summary.append(
            {
                "severity": str(severity),
                "actions_count": len(actions),
                "sample_actions": [a for a in action_summaries if a],
            }
        )

    fallback_summary = [
        _summarize_quick_fix_action(path.name, f"fallback[{idx}]", action, issues)
        for idx, action in enumerate(fallback_actions[:3])
    ]

    summary = {
        "path": _relative_path(path),
        "version": version,
        "total_alert_types": len(alert_types_summary),
        "total_severity_rules": len(severity_summary),
        "total_fallback": len(fallback_actions),
        "alert_types": alert_types_summary,
        "severity_rules": severity_summary,
        "fallback_actions": [a for a in fallback_summary if a],
        "git": _git_metadata(path),
    }
    return SectionResult(summary, issues)


def _summarize_quick_fix_action(
    file_name: str,
    scope: str,
    action: Any,
    issues: List[Dict[str, str]],
) -> Dict[str, Any]:
    if not isinstance(action, dict):
        issues.append(_issue(file_name, scope, "כל פעולה חייבת להיות אובייקט עם label/type"))
        return {}
    label = str(action.get("label") or action.get("id") or "").strip()
    if not label:
        issues.append(_issue(file_name, scope, "label חסר"))
    action_type = str(action.get("type") or "link").lower()
    payload = ""
    if action_type == "link":
        payload = str(action.get("href") or "")
        if not payload:
            issues.append(_issue(file_name, scope, "href חסר לפעולת לינק"))
    elif action_type == "copy":
        payload = str(action.get("payload") or "")
        if not payload:
            issues.append(_issue(file_name, scope, "payload חסר לפעולת copy"))
    else:
        issues.append(_issue(file_name, scope, f"סוג פעולה לא נתמך: {action_type}"))
    return {
        "label": label or "—",
        "type": action_type,
        "value": payload or "—",
        "safety": action.get("safety") or "safe",
    }


def _build_runbooks_section(path: Path) -> SectionResult:
    data, issues = _load_mapping(path, required_name="observability_runbooks.yml")

    version = data.get("version")
    if not isinstance(version, int):
        issues.append(_issue(path.name, "version", "יש להגדיר מספר גרסה (version) תקני"))

    default_flow = data.get("default")
    runbooks_raw = data.get("runbooks")
    if not isinstance(runbooks_raw, dict):
        issues.append(_issue(path.name, "runbooks", "השורש runbooks חייב להיות מפה של אובייקטים"))
        runbooks_raw = {}

    runbooks_summary: List[Dict[str, Any]] = []
    for key, cfg in runbooks_raw.items():
        if not isinstance(cfg, dict):
            issues.append(_issue(path.name, f"runbooks.{key}", "ערך חייב להיות אובייקט Runbook"))
            continue
        steps = cfg.get("steps")
        if not isinstance(steps, list):
            issues.append(_issue(path.name, f"runbooks.{key}.steps", "steps חייב להיות מערך"))
            steps = []
        aliases_raw = cfg.get("aliases")
        if aliases_raw is not None and not isinstance(aliases_raw, list):
            issues.append(_issue(path.name, f"runbooks.{key}.aliases", "aliases חייב להיות מערך מחרוזות"))
            aliases_raw = []
        steps_preview = _summarize_runbook_steps(path.name, key, steps, issues)
        runbooks_summary.append(
            {
                "name": str(key),
                "title": cfg.get("title"),
                "description": cfg.get("description"),
                "aliases": [str(alias) for alias in (aliases_raw or []) if isinstance(alias, str)],
                # Config Radar UI shows only a preview (up to 6 items) so keep the displayed count consistent
                # with what the user actually sees.
                "steps_count": len(steps_preview),
                "steps_total": len(steps),
                "steps": steps_preview,
            }
        )

    summary = {
        "path": _relative_path(path),
        "version": version,
        "default_runbook": default_flow,
        "total_runbooks": len(runbooks_summary),
        "runbooks": runbooks_summary,
        "git": _git_metadata(path),
    }
    if not default_flow:
        issues.append(_issue(path.name, "default", "הגדרת ברירת המחדל (default) חסרה"))
    return SectionResult(summary, issues)


def _summarize_runbook_steps(
    file_name: str,
    book_name: str,
    steps: Sequence[Any],
    issues: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for idx, step in enumerate(steps[:6]):
        if not isinstance(step, dict):
            issues.append(_issue(file_name, f"runbooks.{book_name}.steps[{idx}]", "כל צעד חייב להיות אובייקט"))
            continue
        action = step.get("action")
        action_label = ""
        action_type = ""
        action_value = ""
        action_safety = ""
        if isinstance(action, dict):
            action_label = str(action.get("label") or "")
            action_type = str(action.get("type") or "").lower()
            action_safety = str(action.get("safety") or "")
            if action_type == "link":
                action_value = str(action.get("href") or "")
            elif action_type == "copy":
                action_value = str(action.get("payload") or "")
        summaries.append(
            {
                "id": step.get("id"),
                "title": step.get("title"),
                "action_label": action_label,
                "action_type": action_type,
                "action_value": action_value,
                "action_safety": action_safety,
            }
        )
    return summaries


def _summarize_signatures(
    file_name: str,
    category: str,
    entries: Sequence[Any],
    default_severity: str,
    default_policy: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    summaries: List[Dict[str, Any]] = []
    issues: List[Dict[str, str]] = []

    for idx, entry in enumerate(entries):
        sig_id = f"{category}_{idx}"
        summary = ""
        severity = default_severity
        policy = default_policy
        pattern = ""

        if isinstance(entry, str):
            pattern = entry.strip()
        elif isinstance(entry, dict):
            sig_id = str(entry.get("id") or sig_id)
            summary = str(entry.get("summary") or entry.get("description") or "")
            severity = str(entry.get("severity") or severity).lower()
            policy = str(entry.get("policy") or policy).lower()
            pattern = str(entry.get("pattern") or entry.get("regex") or "").strip()
        else:
            issues.append(_issue(file_name, f"categories.{category}.signatures[{idx}]", "פורמט לא נתמך"))
            continue

        if not pattern:
            issues.append(
                _issue(file_name, f"categories.{category}.signatures[{idx}].pattern", "Regex חסר")
            )
            continue

        try:
            re.compile(pattern)
        except re.error as exc:
            issues.append(
                _issue(
                    file_name,
                    f"categories.{category}.signatures[{idx}].pattern",
                    f"Regex לא תקין: {exc}",
                )
            )

        summaries.append(
            {
                "id": sig_id,
                "summary": summary,
                "pattern": pattern,
                "severity": severity,
                "policy": policy,
            }
        )

    return summaries, issues


def _load_mapping(path: Path, *, required_name: str) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    issues: List[Dict[str, str]] = []

    if not path.exists():
        issues.append(_issue(required_name, "file", f"הקובץ {path} לא קיים"))
        return {}, issues

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        issues.append(_issue(required_name, "file", f"קריאת הקובץ נכשלה: {exc}"))
        return {}, issues

    data, parse_issue = _parse_yaml_or_json(text)
    if parse_issue:
        issues.append(_issue(required_name, "file", parse_issue))
    if not isinstance(data, dict):
        issues.append(_issue(required_name, "file", "מבנה הקובץ חייב להיות YAML/JSON של מפתחות"))
        return {}, issues
    return data, issues


def _parse_yaml_or_json(text: str) -> Tuple[Any, Optional[str]]:
    yaml_missing = yaml is None
    yaml_error: Optional[str] = None

    if yaml is not None:
        try:
            loaded = yaml.safe_load(text)
            if loaded is not None:
                return loaded, None
        except Exception as exc:
            yaml_error = f"פענוח YAML נכשל: {exc}"

    try:
        return json.loads(text or "{}"), None
    except Exception as exc:
        if yaml_missing:
            return {}, "לא ניתן לקרוא קובץ YAML כי ספריית PyYAML אינה מותקנת (pip install pyyaml)"
        if yaml_error:
            return {}, yaml_error
        return {}, f"קובץ אינו JSON תקין: {exc}"


def _resolve_path(env_key: str, default_rel_path: str) -> Path:
    raw = os.getenv(env_key)
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        return candidate
    return (REPO_ROOT / default_rel_path).resolve()


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except Exception:
        return str(path)


def _git_metadata(path: Path) -> Dict[str, Optional[str]]:
    meta = {
        "path": _relative_path(path),
        "last_updated": None,
        "last_commit": None,
        "author": None,
    }
    try:
        completed = subprocess.run(
            ["git", "log", "-1", "--format=%ct|%h|%an", "--", str(path)],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(REPO_ROOT),
        )
        raw = completed.stdout.strip()
        if not raw:
            return meta
        ts_str, *rest = raw.split("|")
        ts = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
        meta["last_updated"] = ts.isoformat()
        if rest:
            meta["last_commit"] = rest[0] or None
        if len(rest) > 1:
            meta["author"] = rest[1] or None
    except Exception:
        return meta
    return meta


def _coerce_positive_int(value: Any) -> Optional[int]:
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return None
    return candidate if candidate > 0 else None


def _coerce_non_negative_int(value: Any) -> Optional[int]:
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return None
    return candidate if candidate >= 0 else None


def _normalize_string_list(value: Any, *, preserve_case: bool = False) -> List[str]:
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        result.append(text if preserve_case else text.lower())
    return result


def _normalize_int_list(value: Any) -> List[int]:
    if not isinstance(value, list):
        return []
    result: List[int] = []
    for item in value:
        try:
            num = int(item)
        except (TypeError, ValueError):
            continue
        if num > 0:
            result.append(num)
    return sorted(set(result))


def _require(summary: Dict[str, Any], key: str, issues: List[Dict[str, str]], file_name: str, *, allow_zero: bool = False) -> None:
    value = summary.get(key)
    if value is None:
        issues.append(_issue(file_name, key, "ערך חסר או לא תקין"))
    elif not allow_zero and isinstance(value, int) and value <= 0:
        issues.append(_issue(file_name, key, "ערך חייב להיות חיובי"))


def _issue(file_name: str, field: str, message: str, *, level: str = "error") -> Dict[str, str]:
    return {"file": file_name, "field": field, "message": message, "level": level}


def _summarize_issues(issues: List[Dict[str, str]]) -> Dict[str, Any]:
    status = "ok" if not any(_is_error(issue) for issue in issues) else "error"
    return {"status": status, "issues": issues}


def _is_error(issue: Dict[str, str]) -> bool:
    return issue.get("level", "error").lower() != "warning"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


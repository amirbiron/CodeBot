import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional


def _parse_bool(value: str | None, default: bool = False) -> bool:
    v = str(value or "").strip().lower()
    if not v:
        return default
    return v in {"1", "true", "t", "yes", "y", "on", "enabled"}


def _now() -> float:
    return time.time()


def _stable_traits_fingerprint(traits: dict[str, Any] | None) -> str:
    if not traits:
        return ""
    try:
        payload = json.dumps(traits, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        payload = str(traits)
    return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()


def _normalize_flag_name_for_env(flag_name: str) -> str:
    # Normalize to env-var-friendly token: uppercase + underscores only.
    s = str(flag_name or "").strip().upper()
    out = []
    for ch in s:
        if ("A" <= ch <= "Z") or ("0" <= ch <= "9"):
            out.append(ch)
        else:
            out.append("_")
    # Collapse multiple underscores
    normalized = "".join(out)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized.strip("_")


def _env_flag_key(flag_name: str) -> str:
    # Boolean flag: FF_<FLAG>
    return f"FF_{_normalize_flag_name_for_env(flag_name)}"


def _env_value_key(flag_name: str) -> str:
    # Value flag: FFV_<FLAG>
    return f"FFV_{_normalize_flag_name_for_env(flag_name)}"


@dataclass(frozen=True)
class _IdentityCacheEntry:
    created_at: float
    flags: Any


class FeatureFlagsService:
    """שכבת Feature Flags פשוטה עם אופציה ל-Flagsmith.

    עקרונות:
    - אתחול פעם אחת ושימוש חוזר.
    - Fail-open נשלט ב-ENV עבור תקלות רשת/SDK (לא עבור מצב "לא מוגדר").
    - קאש קצר ל-identity flags כדי לא לפגוע בביצועים.
    - אין תלות קשיחה ב-flagsmith: אם לא מותקן/לא מוגדר – השירות נשאר כבוי.
    """

    def __init__(
        self,
        *,
        backend: str,
        enabled: bool,
        fail_open: bool,
        identity_cache_ttl_seconds: float,
        client: Any | None,
        emit_event: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._backend = str(backend or "").strip().lower() or "env"
        self._enabled = bool(enabled)
        self._fail_open = bool(fail_open)
        self._ttl = max(0.0, float(identity_cache_ttl_seconds))
        self._client = client
        self._emit_event = emit_event
        self._lock = threading.Lock()
        self._identity_cache: dict[str, _IdentityCacheEntry] = {}

    @property
    def enabled(self) -> bool:
        # "enabled" means: feature flags layer is active (either env backend or flagsmith backend).
        if not self._enabled:
            return False
        if self._backend == "flagsmith":
            return self._client is not None
        # env backend is always available (no deps)
        return True

    def _emit(self, event: str, severity: str = "info", **fields: Any) -> None:
        try:
            if callable(self._emit_event):
                self._emit_event(event, severity=severity, **fields)
        except Exception:
            return None

    @classmethod
    def from_env(cls) -> "FeatureFlagsService":
        # Optional structured event emission (fail-open)
        try:
            from observability import emit_event  # type: ignore
        except Exception:  # pragma: no cover
            emit_event = None  # type: ignore

        env_key = str(
            os.getenv("FLAGSMITH_ENV_KEY")
            or os.getenv("FLAGSMITH_ENVIRONMENT_KEY")
            or ""
        ).strip()
        api_url = str(os.getenv("FLAGSMITH_API_URL") or "").strip() or None

        fail_open = _parse_bool(os.getenv("FLAGSMITH_FAIL_OPEN"), default=False)
        try:
            ttl = float(os.getenv("FLAGSMITH_IDENTITY_CACHE_TTL_SECONDS") or "60")
        except Exception:
            ttl = 60.0

        # אם אין Flagsmith env key – עדיין ניתן לעבוד "ENV בלבד" בלי התקנות:
        # FF_<FLAG>=true/false  (בוליאני)
        # FFV_<FLAG>=<value>    (ערך)
        if not env_key:
            return cls(
                backend="env",
                enabled=True,
                fail_open=False,
                identity_cache_ttl_seconds=ttl,
                client=None,
                emit_event=emit_event,
            )

        # Import flagsmith lazily so tests/CI won't require it unless actually used.
        try:
            from flagsmith import Flagsmith  # type: ignore
        except Exception as e:
            try:
                if callable(emit_event):
                    emit_event(
                        "flagsmith_import_failed",
                        severity="anomaly",
                        handled=True,
                        error=str(e),
                    )
            except Exception:
                pass
            return cls(
                backend="env",
                enabled=True,
                fail_open=fail_open,
                identity_cache_ttl_seconds=ttl,
                client=None,
                emit_event=emit_event,
            )

        try:
            kwargs: dict[str, Any] = {"environment_key": env_key}
            if api_url:
                kwargs["api_url"] = api_url
            client = Flagsmith(**kwargs)
        except Exception as e:
            try:
                if callable(emit_event):
                    emit_event(
                        "flagsmith_init_failed",
                        severity="anomaly",
                        handled=True,
                        error=str(e),
                    )
            except Exception:
                pass
            client = None

        return cls(
            backend="flagsmith",
            enabled=True,
            fail_open=fail_open,
            identity_cache_ttl_seconds=ttl,
            client=client,
            emit_event=emit_event,
        )

    def _get_identity_flags(self, identifier: str, traits: dict[str, Any] | None) -> Any | None:
        if not self.enabled or self._backend != "flagsmith":
            return None

        fp = _stable_traits_fingerprint(traits)
        cache_key = f"{identifier}::{fp}"
        now = _now()

        # Fast path: cache hit
        if self._ttl > 0:
            with self._lock:
                entry = self._identity_cache.get(cache_key)
                if entry is not None and (now - float(entry.created_at)) <= self._ttl:
                    return entry.flags

        # Cache miss: fetch
        try:
            # SDK signature differs across versions; be defensive.
            try:
                flags = self._client.get_identity_flags(identifier=identifier, traits=traits)  # type: ignore[attr-defined]
            except TypeError:
                flags = self._client.get_identity_flags(identifier=identifier)  # type: ignore[attr-defined]
        except Exception as e:
            self._emit(
                "flagsmith_get_identity_flags_failed",
                severity="anomaly",
                handled=True,
                error=str(e),
            )
            return None

        if self._ttl > 0:
            with self._lock:
                self._identity_cache[cache_key] = _IdentityCacheEntry(created_at=now, flags=flags)
                # Best-effort eviction: keep dict bounded (avoid unbounded growth).
                if len(self._identity_cache) > 5000:
                    try:
                        # Remove ~10% oldest entries
                        items = sorted(self._identity_cache.items(), key=lambda kv: kv[1].created_at)
                        for k, _v in items[: max(1, int(len(items) * 0.1))]:
                            self._identity_cache.pop(k, None)
                    except Exception:
                        pass

        return flags

    def _env_is_enabled(self, flag_name: str) -> bool:
        key = _env_flag_key(flag_name)
        if key not in os.environ:
            return False
        return _parse_bool(os.getenv(key), default=False)

    def _env_get_value(self, flag_name: str, default: Any = None) -> Any:
        key = _env_value_key(flag_name)
        if key in os.environ:
            v = os.getenv(key)
            return default if v in (None, "") else v
        # Fallback: allow reading FF_<FLAG> as a value too (useful for numeric-as-string)
        key2 = _env_flag_key(flag_name)
        if key2 in os.environ:
            v = os.getenv(key2)
            return default if v in (None, "") else v
        return default

    def is_enabled(self, flag_name: str, *, user_id: str | None = None, traits: dict[str, Any] | None = None) -> bool:
        name = str(flag_name or "").strip()
        if not name:
            return False

        if not self.enabled:
            return False

        if self._backend == "env":
            # אין תמיכה ב-targeting/rollout במצב ENV בלבד.
            return self._env_is_enabled(name)

        if user_id:
            identity_flags = self._get_identity_flags(str(user_id), traits=traits)
            if identity_flags is None:
                return bool(self._fail_open)
            try:
                return bool(identity_flags.is_feature_enabled(name))
            except Exception:
                return bool(self._fail_open)

        try:
            return bool(self._client.is_feature_enabled(name))  # type: ignore[attr-defined]
        except Exception as e:
            self._emit(
                "flagsmith_is_feature_enabled_failed",
                severity="anomaly",
                handled=True,
                error=str(e),
                flag=name,
            )
            return bool(self._fail_open)

    def get_value(
        self,
        flag_name: str,
        *,
        user_id: str | None = None,
        traits: dict[str, Any] | None = None,
        default: Any = None,
    ) -> Any:
        name = str(flag_name or "").strip()
        if not name:
            return default

        if not self.enabled:
            return default

        if self._backend == "env":
            return self._env_get_value(name, default=default)

        if user_id:
            identity_flags = self._get_identity_flags(str(user_id), traits=traits)
            if identity_flags is None:
                return default
            try:
                value = identity_flags.get_feature_value(name)
            except Exception:
                return default
            return default if value in (None, "") else value

        try:
            flags = self._client.get_environment_flags()  # type: ignore[attr-defined]
        except Exception:
            # SDK may not support this method; fallback to default.
            return default
        try:
            value = flags.get_feature_value(name)
        except Exception:
            return default
        return default if value in (None, "") else value


# Singleton לשימוש פשוט ברוב המקומות (אופציונלי).
feature_flags = FeatureFlagsService.from_env()


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
        enabled: bool,
        fail_open: bool,
        identity_cache_ttl_seconds: float,
        client: Any | None,
        emit_event: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._fail_open = bool(fail_open)
        self._ttl = max(0.0, float(identity_cache_ttl_seconds))
        self._client = client
        self._emit_event = emit_event
        self._lock = threading.Lock()
        self._identity_cache: dict[str, _IdentityCacheEntry] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled and (self._client is not None)

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

        if not env_key:
            return cls(
                enabled=False,
                fail_open=fail_open,
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
                enabled=False,
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
            enabled=True,
            fail_open=fail_open,
            identity_cache_ttl_seconds=ttl,
            client=client,
            emit_event=emit_event,
        )

    def _get_identity_flags(self, identifier: str, traits: dict[str, Any] | None) -> Any | None:
        if not self.enabled:
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

    def is_enabled(self, flag_name: str, *, user_id: str | None = None, traits: dict[str, Any] | None = None) -> bool:
        name = str(flag_name or "").strip()
        if not name:
            return False

        if not self.enabled:
            return False

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


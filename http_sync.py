from __future__ import annotations

import os
import threading
from typing import Optional, Any, Mapping
import time
import logging

import requests
from requests.adapters import HTTPAdapter

try:
    # Retry is optional depending on urllib3 version bundled with requests
    from urllib3.util import Retry  # type: ignore
except Exception:  # pragma: no cover
    Retry = None  # type: ignore


_local = threading.local()


def _to_int(env_name: str, default: int) -> int:
    try:
        val = os.getenv(env_name)
        if val is None or val == "":
            return int(default)
        return int(val)
    except Exception:
        return int(default)


def _to_float(env_name: str, default: float) -> float:
    try:
        val = os.getenv(env_name)
        if val is None or val == "":
            return float(default)
        return float(val)
    except Exception:
        return float(default)


def _create_session() -> requests.Session:
    pool_conns = _to_int("REQUESTS_POOL_CONNECTIONS", 20)
    pool_max = _to_int("REQUESTS_POOL_MAXSIZE", 100)
    retries = _to_int("REQUESTS_RETRIES", 2)
    backoff = _to_float("REQUESTS_RETRY_BACKOFF", 0.2)

    sess = requests.Session()
    adapter_kwargs = {"pool_connections": pool_conns, "pool_maxsize": pool_max}

    if Retry is not None:
        status_forcelist = (500, 502, 503, 504)
        allowed = frozenset(["GET", "POST", "PUT", "PATCH", "DELETE"])  # HEAD rarely used here
        try:
            retry = Retry(
                total=retries,
                connect=retries,
                read=0,  # do not retry read timeouts to avoid long hangs
                status=retries,
                backoff_factor=backoff,
                status_forcelist=status_forcelist,
                allowed_methods=allowed,
                raise_on_status=False,
            )
        except TypeError:
            # Older urllib3 uses method_whitelist
            retry = Retry(
                total=retries,
                connect=retries,
                read=0,  # do not retry read timeouts to avoid long hangs
                status=retries,
                backoff_factor=backoff,
                status_forcelist=status_forcelist,
                method_whitelist=allowed,  # type: ignore[arg-type]
                raise_on_status=False,
            )
        adapter_kwargs["max_retries"] = retry

    adapter = HTTPAdapter(**adapter_kwargs)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


def get_session() -> requests.Session:
    sess: Optional[requests.Session] = getattr(_local, "session", None)
    if sess is None:
        sess = _create_session()
        _local.session = sess
    return sess


def request(method: str, url: str, **kwargs):
    timeout = kwargs.pop("timeout", _to_float("REQUESTS_TIMEOUT", 8.0))
    slow_ms = _to_float("HTTP_SLOW_MS", 0.0)
    logger = logging.getLogger(__name__)
    t0 = time.perf_counter()
    headers = kwargs.get("headers")
    merged_headers = _merge_observability_headers(headers)
    if merged_headers is not None:
        kwargs["headers"] = merged_headers
    resp = get_session().request(method=method, url=url, timeout=timeout, **kwargs)
    try:
        if slow_ms and slow_ms > 0:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            if dur_ms > slow_ms:
                # לוג מינימלי ללא הדפסת כותרות/טוקנים
                logger.warning(
                    "slow_http",
                    extra={
                        "method": str(method).upper(),
                        "url": str(url),
                        "status": int(getattr(resp, "status_code", 0) or 0),
                        "ms": round(dur_ms, 1),
                    },
                )
    except Exception:
        # לעולם לא להפיל את הקריאה בגלל לוג
        pass
    return resp


def _merge_observability_headers(headers: Any) -> Mapping[str, str] | None:
    base: dict[str, str] = {}
    if headers is None:
        base = {}
    elif isinstance(headers, Mapping):
        for key, value in headers.items():
            if key is None or value is None:
                continue
            try:
                base[str(key)] = str(value)
            except Exception:
                continue
    else:
        try:
            for key, value in dict(headers).items():  # type: ignore[arg-type]
                if key is None or value is None:
                    continue
                base[str(key)] = str(value)
        except Exception:
            base = {}

    try:
        from observability import prepare_outgoing_headers  # type: ignore

        merged = prepare_outgoing_headers(base or None)
    except Exception:
        merged = None

    if merged:
        return merged
    if headers is None:
        # לא נוספו כותרות – נחזיר None כדי לשמור על ברירת המחדל של requests
        return None
    return base or None

"""
Simple concurrent load test client for CodeBot services (Session 5).

Goals:
- Generate concurrent HTTP requests to a base URL and measure SLOs.
- Compute success ratio, p95 latency, and error rate.
- Avoid external deps: use asyncio + aiohttp if available, else urllib.
- Write outputs under /tmp by default, never mutate project files.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:
    import aiohttp  # type: ignore
except Exception:
    aiohttp = None  # type: ignore

DEFAULT_ENDPOINTS = [
    "/",  # homepage or health
    "/metrics",
    "/webapp/index.html",
]


@dataclass
class Result:
    status: int
    latency: float


async def _fetch_aiohttp(session: "aiohttp.ClientSession", url: str) -> Result:
    t0 = time.perf_counter()
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            await resp.read()
            return Result(status=resp.status, latency=max(0.0, time.perf_counter() - t0))
    except Exception:
        return Result(status=599, latency=max(0.0, time.perf_counter() - t0))


def _fetch_urllib(url: str) -> Result:
    import urllib.request
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # nosec - test tool
            status = getattr(resp, "status", 200) or 200
            _ = resp.read()
            return Result(status=int(status), latency=max(0.0, time.perf_counter() - t0))
    except Exception:
        return Result(status=599, latency=max(0.0, time.perf_counter() - t0))


async def _worker_aiohttp(base: str, endpoints: List[str], n: int, results: List[Result]) -> None:
    assert aiohttp is not None
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for _ in range(n):
            ep = random.choice(endpoints)
            r = await _fetch_aiohttp(session, base + ep)
            results.append(r)


async def _run_async(base_url: str, users: int, per_user: int, endpoints: List[str]) -> List[Result]:
    assert aiohttp is not None
    results: List[Result] = []
    tasks = [asyncio.create_task(_worker_aiohttp(base_url, endpoints, per_user, results)) for _ in range(users)]
    await asyncio.gather(*tasks)
    return results


def _run_sync(base_url: str, users: int, per_user: int, endpoints: List[str]) -> List[Result]:
    # Fallback synchronous implementation
    results: List[Result] = []
    total = users * per_user
    for _ in range(total):
        ep = random.choice(endpoints)
        results.append(_fetch_urllib(base_url + ep))
    return results


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    k = (len(values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return float(values[f])
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return float(d0 + d1)


def _summarize(results: List[Result]) -> Tuple[dict, str]:
    total = len(results)
    if total == 0:
        return {"total": 0}, "No results"
    statuses = [r.status for r in results]
    latencies = sorted([r.latency for r in results])
    # Count success for 2xx and 3xx only; 4xx/5xx are errors
    ok = sum(1 for s in statuses if 200 <= s < 400)
    err = total - ok
    success_ratio = (ok / total) * 100.0
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    avg = statistics.fmean(latencies) if latencies else 0.0
    summary = {
        "total": total,
        "ok": ok,
        "errors": err,
        "success_ratio_percent": round(success_ratio, 2),
        "latency_avg_sec": round(avg, 4),
        "latency_p50_sec": round(p50, 4),
        "latency_p95_sec": round(p95, 4),
        "latency_p99_sec": round(p99, 4),
    }
    text = (
        f"Total={total}, OK={ok}, Errors={err}, Success={success_ratio:.2f}%\n"
        f"Latency: avg={avg:.3f}s p50={p50:.3f}s p95={p95:.3f}s p99={p99:.3f}s"
    )
    return summary, text


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Simple load test for CodeBot")
    p.add_argument("--base-url", required=True, help="Base URL, e.g., http://localhost:8080")
    p.add_argument("--users", type=int, default=20, help="Concurrent users (tasks)")
    p.add_argument("--per-user", type=int, default=20, help="Requests per user")
    p.add_argument("--ramp-sec", type=int, default=0, help="Ramp-up seconds (noop; reserved)")
    p.add_argument("--endpoints", nargs="*", default=DEFAULT_ENDPOINTS, help="Paths to hit")
    p.add_argument("--out", default=os.path.join("/tmp", "codebot-load.json"), help="Output JSON path under /tmp")
    args = p.parse_args(argv if argv is not None else None)

    base = args.base_url.rstrip("/")
    endpoints = [ep if ep.startswith("/") else ("/" + ep) for ep in (args.endpoints or DEFAULT_ENDPOINTS)]

    if aiohttp is not None:
        results = asyncio.run(_run_async(base, int(args.users), int(args.per_user), endpoints))
    else:
        results = _run_sync(base, int(args.users), int(args.per_user), endpoints)

    summary, text = _summarize(results)
    print(text)

    # write output under /tmp only
    out_path = args.out
    if not out_path.startswith("/tmp/") and out_path != "/tmp":
        out_path = os.path.join("/tmp", os.path.basename(out_path))
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Basic SLO assertion: success >= 95%
    if summary.get("success_ratio_percent", 0.0) < 95.0:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

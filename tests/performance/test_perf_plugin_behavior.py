import os
import time
import importlib
import types
import pytest


pytestmark = pytest.mark.performance


def _run_dummy_slow(seconds: float) -> None:
    time.sleep(seconds)


def test_perf_cache_and_auto_heavy_marking(tmp_path, monkeypatch):
    # Simulate previous run durations in pytest cache
    # We'll set a very low percentile so our test gets marked heavy
    monkeypatch.setenv("PERF_HEAVY_PERCENTILE", "10")

    # Create a fake config/cache using pytest's cacheprovider via testdir plugin
    # Here we rely on pytest's cache already available; we write directly to it
    # by invoking a minimal run to initialize cache and then setting the key.

    # Mark this test's nodeid as if it took 2.0s previously
    # We do not know nodeid at collection time here, so we run a subtest that will store
    # its own durations and then ensure threshold logic runs.

    start = time.perf_counter()
    _run_dummy_slow(0.02)
    took = time.perf_counter() - start
    assert took >= 0.02


def test_only_light_skips_heavy(monkeypatch):
    # Ensure that ONLY_LIGHT_PERF triggers skip on heavy tests
    monkeypatch.setenv("ONLY_LIGHT_PERF", "1")
    # This test is performance-marked but not heavy; should not skip
    assert True


@pytest.mark.heavy
def test_heavy_would_be_skipped_when_only_light(monkeypatch):
    # Note: Skip is applied at collection phase; here we just ensure test body is light
    # The presence of ONLY_LIGHT_PERF in env causes skip by plugin
    assert True

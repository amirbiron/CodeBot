import os
import sys
import pytest

# Ensure project root is on sys.path so `import utils` works in tests
PROJECT_ROOT = os.path.dirname(__file__)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def pytest_collection_modifyitems(config, items):
    """Skip heavy performance tests when ONLY_LIGHT_PERF is set.

    Default behavior: run everything. If ONLY_LIGHT_PERF in env is truthy,
    skip tests marked with both `performance` and `heavy`.
    """
    only_light = os.getenv("ONLY_LIGHT_PERF") in ("1", "true", "True")
    if not only_light:
        return

    skip_heavy = pytest.mark.skip(reason="ONLY_LIGHT_PERF set; skipping heavy performance tests")
    for item in items:
        if "performance" in item.keywords and "heavy" in item.keywords:
            item.add_marker(skip_heavy)


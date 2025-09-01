import os
import sys

# Ensure project root is on sys.path so `import utils` works in tests
PROJECT_ROOT = os.path.dirname(__file__)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


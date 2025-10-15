# tests/conftest.py
# Auto-load telegram stubs for all tests and provide minimal sanity env.
import os

# Ensure safe, isolated test environment variables (no external IO)
os.environ.setdefault('DISABLE_ACTIVITY_REPORTER', '1')
os.environ.setdefault('DISABLE_DB', '1')
os.environ.setdefault('BOT_TOKEN', 'x')
os.environ.setdefault('MONGODB_URL', 'mongodb://localhost:27017/test')

# Import stubs so any import of `telegram` succeeds in tests
import tests._telegram_stubs  # noqa: F401

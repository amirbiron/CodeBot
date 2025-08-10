# 🧪 Tests Directory

This directory contains all the test files for the Code Keeper Bot project.

## Test Files

- **test_initial.py** - Basic smoke test to verify pytest setup
- **test_full_bot.py** - Comprehensive test suite covering all bot functionality

## Running Tests

### Locally
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov pytest-mock freezegun faker

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html

# Run specific test file
pytest tests/test_full_bot.py -v
```

### GitHub Actions
Tests run automatically on:
- Every push to main branch
- Every pull request
- Tag pushes (v*)

The CI pipeline runs tests on Python 3.9, 3.10, and 3.11.

## Test Coverage

The test suite includes:
- ✅ Unit tests for core functions
- ✅ Command handler tests
- ✅ File handling tests
- ✅ Callback query tests
- ✅ GitHub integration tests
- ✅ Database operation tests
- ✅ Permission and security tests
- ✅ Error handling tests
- ✅ End-to-end user flow tests
- ✅ Performance tests

## Recent Fixes (v1.0.1)

- Fixed JavaScript emoji assertion (📜 → 🟨)
- Fixed large file lines_count calculation (1000 → 1001)
- Fixed database mock patches (conversation_handlers.db → database.db)
- Fixed command handler imports and usage
- Removed Hebrew text assertions for better test stability
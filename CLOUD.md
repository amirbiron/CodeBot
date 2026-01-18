# CLOUD.md

## Purpose
Quick reference for running and testing this repo in cloud/CI or local dev.

## AI quickstart (project rules)
Do not:
- Use sudo.
- Run long-lived processes (dev servers, watch, etc).
- Run interactive commands (git rebase -i, git add -i, nano).
- Change git config.
- Push to remote unless explicitly requested.

Do:
- Use approved file tools (Read/LS/Grep/Glob) instead of cat/ls/find/grep.
- Use absolute paths.
- Keep edits minimal and follow existing style.
- Do all test/script IO only under /tmp.

## Requirements (common)
- Python 3.11+ (3.12 recommended)
- MongoDB (local or Atlas)
- Telegram bot token (for the bot)

## Run the bot (local/dev)
1) Create env file:
   - `cp .env.example .env`
2) Start:
   - `python main.py`
   - `LOG_LEVEL=DEBUG python main.py` (verbose)

## Run the webapp
Option A (simple local):
- `cd webapp`
- `python app.py`

Option B (Render/production-friendly wrapper):
- `./scripts/start_webapp.sh`

Option C (webapp + AI explain service together):
- `./scripts/run_all.sh`

## Optional push worker + bot
- `./scripts/start_with_worker.sh`
  - Starts the optional Node push worker (if enabled) and then runs `python main.py`.

## Required env (minimum)
Bot:
- `BOT_TOKEN`
- `MONGODB_URL`

Webapp (minimum):
- `SECRET_KEY`
- `MONGODB_URL`
- `BOT_TOKEN`
- `BOT_USERNAME`
- `WEBAPP_URL`

Admin (optional):
- `ADMIN_USER_IDS` (comma-separated Telegram user IDs)

## Tests (pytest)
Quickstart:
1) Set env for tests:
   - `export DISABLE_ACTIVITY_REPORTER=1`
   - `export DISABLE_DB=1`
   - `export BOT_TOKEN=x`
   - `export MONGODB_URL='mongodb://localhost:27017/test'`
2) Install test deps:
   - `pip install -U pytest pytest-asyncio pytest-cov`
3) Run:
   - `pytest -q`

Performance tests:
- `pytest -q -m performance`
- `ONLY_LIGHT_PERF=1 pytest -q -m performance`

Safety rules for tests:
- Use `tmp_path` for file IO.
- Delete only under `/tmp` and only with a safe wrapper.

## Git commits
- Use Conventional Commits: feat | fix | docs | test | refactor | chore | perf
- Prefer heredoc messages, for example:
  - `git commit -m "$(cat <<'EOF'`
  - `docs: short why-oriented message`
  - ``
  - `- Key change`
  - ``
  - `EOF`
  - `)"`

## Optional quality checks
- `pip install pre-commit`
- `pre-commit run --all-files`

## Docs pointers
- `README.md` (bot setup + deployment)
- `webapp/README.md` (webapp setup)
- `docs/testing.rst` (testing guide)
- `docs/performance-tests.rst` (performance tests)

## Rate limiting (quick ref)
- Enable shadow mode first, then move to blocking.
- Key env vars:
  - `RATE_LIMIT_ENABLED=true`
  - `RATE_LIMIT_SHADOW_MODE=true`
  - `RATE_LIMIT_STRATEGY=moving-window` (or `fixed-window`)
  - `ADMIN_USER_IDS=123,456`
  - `REDIS_URL=rediss://...` (prod)

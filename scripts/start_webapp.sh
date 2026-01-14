#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd -P)"
APP_DIR="${ROOT_DIR}/webapp"

log() {
  printf '[webapp-start] %s\n' "$*"
}

trim() {
  local value="${1:-}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

resolve_asset_version() {
  local candidate
  for candidate in \
    "${ASSET_VERSION:-}" \
    "${RENDER_GIT_COMMIT:-}" \
    "${SOURCE_VERSION:-}" \
    "${GIT_COMMIT:-}" \
    "${HEROKU_SLUG_COMMIT:-}"; do
    if [ -n "$candidate" ]; then
      printf '%s\n' "${candidate:0:8}"
      return 0
    fi
  done
  if command -v git >/dev/null 2>&1 && git -C "$ROOT_DIR" rev-parse HEAD >/dev/null 2>&1; then
    git -C "$ROOT_DIR" rev-parse --short=8 HEAD
    return 0
  fi
  date +%s
}

export ASSET_VERSION="${ASSET_VERSION:-$(resolve_asset_version)}"
log "Using ASSET_VERSION=${ASSET_VERSION}"

PORT="${PORT:-5000}"
APP_MODULE="${WEBAPP_WSGI_APP:-app:app}"
log "Starting Gunicorn (${APP_MODULE}) on 0.0.0.0:${PORT}"

cd "$APP_DIR"

# --- Gunicorn concurrency tuning (Render/Prod) ---
# Render (במיוחד Free/Starter) מאוד רגיש לזיכרון בזמן boot.
# יותר מדי workers = הרבה תהליכים שמטעינים את האפליקציה במקביל -> OOM / thrash -> Port Scan timeout.
#
# לכן ברירת המחדל פה היא **שמרנית**: worker יחיד עם gevent (IO-bound concurrency).
# עדיין אפשר override ידני דרך ENV:
# - WEB_CONCURRENCY / WEBAPP_GUNICORN_WORKERS
# - WEBAPP_GUNICORN_THREADS
# - WEBAPP_GUNICORN_WORKER_CLASS (ברירת מחדל: gevent)
# - WEBAPP_GUNICORN_WORKER_CONNECTIONS (רלוונטי ל-gevent בלבד)
# - WEBAPP_GUNICORN_TIMEOUT / WEBAPP_GUNICORN_KEEPALIVE
GUNICORN_WORKERS="$(trim "${WEB_CONCURRENCY:-${WEBAPP_GUNICORN_WORKERS:-1}}")"
GUNICORN_THREADS="$(trim "${WEBAPP_GUNICORN_THREADS:-4}")"
GUNICORN_WORKER_CLASS="$(trim "${WEBAPP_GUNICORN_WORKER_CLASS:-gevent}")"
GUNICORN_WORKER_CONNECTIONS="$(trim "${WEBAPP_GUNICORN_WORKER_CONNECTIONS:-${GUNICORN_WORKER_CONNECTIONS:-100}}")"
# Timeout: allow both WEBAPP_GUNICORN_TIMEOUT (preferred) and GUNICORN_TIMEOUT (compat).
# Default is more generous to survive cold starts / heavy first requests on Render.
GUNICORN_TIMEOUT="$(trim "${WEBAPP_GUNICORN_TIMEOUT:-${GUNICORN_TIMEOUT:-180}}")"
GUNICORN_GRACEFUL_TIMEOUT="$(trim "${WEBAPP_GUNICORN_GRACEFUL_TIMEOUT:-${GUNICORN_GRACEFUL_TIMEOUT:-${GUNICORN_TIMEOUT}}}")"
GUNICORN_KEEPALIVE="$(trim "${WEBAPP_GUNICORN_KEEPALIVE:-2}")"

GUNICORN_ARGS=(
  "$APP_MODULE"
  --bind "0.0.0.0:${PORT}"
  --workers "${GUNICORN_WORKERS}"
  --worker-class "${GUNICORN_WORKER_CLASS}"
  --timeout "${GUNICORN_TIMEOUT}"
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT}"
  --keep-alive "${GUNICORN_KEEPALIVE}"
)

case "${GUNICORN_WORKER_CLASS,,}" in
  *gevent*)
    log "Gunicorn config: workers=${GUNICORN_WORKERS} class=${GUNICORN_WORKER_CLASS} worker_connections=${GUNICORN_WORKER_CONNECTIONS} timeout=${GUNICORN_TIMEOUT}s graceful_timeout=${GUNICORN_GRACEFUL_TIMEOUT}s keepalive=${GUNICORN_KEEPALIVE}s"
    GUNICORN_ARGS+=(--worker-connections "${GUNICORN_WORKER_CONNECTIONS}")
    ;;
  *gthread*)
    log "Gunicorn config: workers=${GUNICORN_WORKERS} class=${GUNICORN_WORKER_CLASS} threads=${GUNICORN_THREADS} timeout=${GUNICORN_TIMEOUT}s graceful_timeout=${GUNICORN_GRACEFUL_TIMEOUT}s keepalive=${GUNICORN_KEEPALIVE}s"
    GUNICORN_ARGS+=(--threads "${GUNICORN_THREADS}")
    ;;
  *)
    log "Gunicorn config: workers=${GUNICORN_WORKERS} class=${GUNICORN_WORKER_CLASS} timeout=${GUNICORN_TIMEOUT}s graceful_timeout=${GUNICORN_GRACEFUL_TIMEOUT}s keepalive=${GUNICORN_KEEPALIVE}s"
    ;;
esac

gunicorn "${GUNICORN_ARGS[@]}" &
APP_PID=$!

cleanup() {
  if kill -0 "$APP_PID" >/dev/null 2>&1; then
    log "Forwarding stop signal to Gunicorn (pid ${APP_PID})"
    kill "$APP_PID"
    wait "$APP_PID" || true
  fi
}
trap cleanup SIGINT SIGTERM

warmup() {
  if [ "${WEBAPP_ENABLE_WARMUP:-1}" = "0" ]; then
    log "Warmup disabled via WEBAPP_ENABLE_WARMUP"
    return 0
  fi
  local warmup_url="${WEBAPP_WARMUP_URL:-}"
  if [ -z "$warmup_url" ]; then
    warmup_url="http://127.0.0.1:${PORT}/healthz"
  fi
  local attempts="${WEBAPP_WARMUP_MAX_ATTEMPTS:-15}"
  local delay="${WEBAPP_WARMUP_DELAY_SECONDS:-2}"
  log "Warmup hitting ${warmup_url} (max ${attempts} attempts)"
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl -fsS --max-time 5 "$warmup_url" >/dev/null 2>&1; then
      log "Warmup succeeded on attempt ${attempt}"
      return 0
    fi
    sleep "$delay"
  done
  log "Warmup did not succeed after ${attempts} attempts (best-effort)"
  return 0
}

warmup || true
wait "$APP_PID"

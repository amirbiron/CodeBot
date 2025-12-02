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
gunicorn "$APP_MODULE" --bind "0.0.0.0:${PORT}" &
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
      warmup_frontend_paths
      return 0
    fi
    sleep "$delay"
  done
  log "Warmup did not succeed after ${attempts} attempts (best-effort)"
  return 0
}

warmup_frontend_paths() {
  local csv="${WEBAPP_WARMUP_PATHS:-}"
  if [ -z "$csv" ]; then
    return 0
  fi
  local base="${WEBAPP_WARMUP_BASE_URL:-http://127.0.0.1:${PORT}}"
  base="${base%/}"
  local timeout="${WEBAPP_WARMUP_REQUEST_TIMEOUT:-2}"
  local IFS=','
  read -r -a warmup_paths <<< "$csv"
  local path trimmed url
  for path in "${warmup_paths[@]}"; do
    trimmed="$(trim "$path")"
    if [ -z "$trimmed" ]; then
      continue
    fi
    if [[ "$trimmed" != /* ]]; then
      trimmed="/${trimmed}"
    fi
    url="${base}${trimmed}"
    if curl -fsS --max-time "$timeout" "$url" >/dev/null 2>&1; then
      log "Warmup: ${trimmed}... OK"
    else
      log "Warmup: ${trimmed}... FAIL (best-effort)"
    fi
  done
}

warmup || true
wait "$APP_PID"

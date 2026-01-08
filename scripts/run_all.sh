#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

log() {
  printf '[run-all] %s\n' "$*"
}

is_true() {
  local v="${1:-}"
  v="$(printf '%s' "$v" | tr '[:upper:]' '[:lower:]')"
  [[ "$v" == "1" || "$v" == "true" || "$v" == "yes" || "$v" == "on" ]]
}

WEBAPP_START_SCRIPT="${WEBAPP_START_SCRIPT:-scripts/start_webapp.sh}"

# Internal AI Explain service (aiohttp) settings
OBS_AI_EXPLAIN_RUN_LOCAL_SERVICE="${OBS_AI_EXPLAIN_RUN_LOCAL_SERVICE:-true}"
OBS_AI_EXPLAIN_INTERNAL_HOST="${OBS_AI_EXPLAIN_INTERNAL_HOST:-127.0.0.1}"
OBS_AI_EXPLAIN_INTERNAL_PORT="${OBS_AI_EXPLAIN_INTERNAL_PORT:-${AI_EXPLAIN_PORT:-11000}}"

# Default the WebApp -> AI URL to localhost when missing.
if [[ -z "${OBS_AI_EXPLAIN_URL:-}" ]]; then
  export OBS_AI_EXPLAIN_URL="http://${OBS_AI_EXPLAIN_INTERNAL_HOST}:${OBS_AI_EXPLAIN_INTERNAL_PORT}/api/ai/explain"
  log "OBS_AI_EXPLAIN_URL not set; defaulting to ${OBS_AI_EXPLAIN_URL}"
fi

AI_PID=""
WEBAPP_PID=""

terminate_children() {
  set +e
  if [[ -n "${WEBAPP_PID:-}" ]] && kill -0 "$WEBAPP_PID" >/dev/null 2>&1; then
    log "Stopping WebApp wrapper (pid ${WEBAPP_PID})"
    kill "$WEBAPP_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${AI_PID:-}" ]] && kill -0 "$AI_PID" >/dev/null 2>&1; then
    log "Stopping AI webserver (pid ${AI_PID})"
    kill "$AI_PID" >/dev/null 2>&1 || true
  fi
  # Best-effort wait
  [[ -n "${WEBAPP_PID:-}" ]] && wait "$WEBAPP_PID" >/dev/null 2>&1 || true
  [[ -n "${AI_PID:-}" ]] && wait "$AI_PID" >/dev/null 2>&1 || true
  set -e
}

trap terminate_children SIGINT SIGTERM

if is_true "$OBS_AI_EXPLAIN_RUN_LOCAL_SERVICE"; then
  log "Starting AI webserver on ${OBS_AI_EXPLAIN_INTERNAL_HOST}:${OBS_AI_EXPLAIN_INTERNAL_PORT}"
  # NOTE: services.webserver prefers PORT over WEB_PORT, so we scope PORT only for this process.
  WEB_HOST="${OBS_AI_EXPLAIN_INTERNAL_HOST}" \
  PORT="${OBS_AI_EXPLAIN_INTERNAL_PORT}" \
  python -m services.webserver &
  AI_PID="$!"

  # Wait for /healthz (best-effort) to reduce startup race (especially on Render)
  if command -v curl >/dev/null 2>&1; then
    for _i in {1..30}; do
      if curl -fsS --max-time 1 "http://${OBS_AI_EXPLAIN_INTERNAL_HOST}:${OBS_AI_EXPLAIN_INTERNAL_PORT}/healthz" >/dev/null 2>&1; then
        log "AI webserver warmup succeeded"
        break
      fi
      sleep 0.2
    done
  fi
else
  log "OBS_AI_EXPLAIN_RUN_LOCAL_SERVICE=false; skipping local AI webserver"
fi

log "Starting WebApp via ${WEBAPP_START_SCRIPT} (PORT=${PORT:-unset})"
bash "$WEBAPP_START_SCRIPT" &
WEBAPP_PID="$!"

# If either process exits, stop the other and exit non-zero (reliability: no silent crash).
set +e
if wait -n "$WEBAPP_PID" ${AI_PID:+$AI_PID}; then
  EXIT_CODE=0
else
  EXIT_CODE=$?
fi
set -e

log "One process exited (code=${EXIT_CODE}); shutting down the rest"
terminate_children
exit "$EXIT_CODE"


#!/usr/bin/env sh
set -euo pipefail

# Load local worker overrides if present (not committed to git)
if [ -f ".env.worker" ]; then
  # shellcheck disable=SC1091
  set -a; . ./.env.worker; set +a
fi

is_true() {
  v="${1:-}"; v=$(printf "%s" "$v" | tr '[:upper:]' '[:lower:]')
  [ "$v" = "1" ] || [ "$v" = "true" ] || [ "$v" = "yes" ] || [ "$v" = "on" ]
}

PUSH_REMOTE_DELIVERY_ENABLED="${PUSH_REMOTE_DELIVERY_ENABLED:-false}"
PUSH_WORKER_PORT="${PUSH_WORKER_PORT:-18080}"

if is_true "$PUSH_REMOTE_DELIVERY_ENABLED"; then
  # Start Node worker bound to localhost with its own env (private key not exposed globally)
  echo "Starting push worker on 127.0.0.1:${PUSH_WORKER_PORT}..."
  PORT="$PUSH_WORKER_PORT" \
  PUSH_DELIVERY_TOKEN="${PUSH_DELIVERY_TOKEN:-}" \
  WORKER_VAPID_PUBLIC_KEY="${WORKER_VAPID_PUBLIC_KEY:-${VAPID_PUBLIC_KEY:-}}" \
  WORKER_VAPID_PRIVATE_KEY="${WORKER_VAPID_PRIVATE_KEY:-}" \
  WORKER_VAPID_SUB_EMAIL="${WORKER_VAPID_SUB_EMAIL:-${VAPID_SUB_EMAIL:-support@example.com}}" \
  node push_worker/index.js &

  # Default URL if missing: use local worker
  if [ -z "${PUSH_DELIVERY_URL:-}" ]; then
    export PUSH_DELIVERY_URL="http://127.0.0.1:${PUSH_WORKER_PORT}"
  fi

  # Do not leak worker secrets to the Python process environment
  unset WORKER_VAPID_PUBLIC_KEY || true
  unset WORKER_VAPID_PRIVATE_KEY || true
  unset WORKER_VAPID_SUB_EMAIL || true

  # Wait for worker readiness to avoid startup race
  echo "Waiting for push worker readiness..."
  i=0
  until curl -fsS "http://127.0.0.1:${PUSH_WORKER_PORT}/healthz" >/dev/null 2>&1; do
    i=$((i+1))
    if [ "$i" -ge 30 ]; then
      echo "Worker not ready after ~6s; continuing anyway" >&2
      break
    fi
    sleep 0.2
  done
fi

# Run Flask app (uses $PORT provided by platform)
exec python main.py

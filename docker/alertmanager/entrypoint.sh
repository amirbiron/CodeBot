#!/usr/bin/env sh
set -e
PORT="${PORT:-9093}"
# Use env var ALERT_WEBHOOK_URL for webhook
# Render passes $PORT and we listen on it
exec /bin/alertmanager \
  --config.file=/etc/alertmanager/alertmanager.render.yml \
  --web.listen-address=0.0.0.0:"${PORT}"

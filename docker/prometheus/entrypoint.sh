#!/usr/bin/env sh
set -e
PORT="${PORT:-9090}"
# Render provides $PORT
exec /bin/prometheus \
  --config.file=/etc/prometheus/prometheus.render.yml \
  --web.listen-address=0.0.0.0:"${PORT}" \
  --web.enable-lifecycle

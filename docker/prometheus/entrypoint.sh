#!/usr/bin/env sh
set -e

# Defaults for Render if not provided (safe fallbacks)
PORT="${PORT:-9090}"
WEBAPP_HOST_DEFAULT="code-keeper-webapp.onrender.com"
ALERTMANAGER_TARGET_DEFAULT="code-keeper-alertmanager.onrender.com:443"

# Use provided env or fallbacks
WEBAPP_HOST_EFFECTIVE="${WEBAPP_HOST:-$WEBAPP_HOST_DEFAULT}"
ALERTMANAGER_TARGET_EFFECTIVE="${ALERTMANAGER_TARGET:-$ALERTMANAGER_TARGET_DEFAULT}"

# Render the final Prometheus config by replacing placeholders in template
TEMPLATE="/etc/prometheus/prometheus.render.yml"
FINAL_CFG="/etc/prometheus/prometheus.yml"

# Basic placeholder substitution without requiring envsubst
sed \
  -e "s|\${WEBAPP_HOST}|${WEBAPP_HOST_EFFECTIVE}|g" \
  -e "s|\${ALERTMANAGER_TARGET}|${ALERTMANAGER_TARGET_EFFECTIVE}|g" \
  "$TEMPLATE" > "$FINAL_CFG"

# Safety net: if placeholders remain, force fallback values
if grep -q "\${WEBAPP_HOST}\|\${ALERTMANAGER_TARGET}" "$FINAL_CFG"; then
  sed -i \
    -e "s|\${WEBAPP_HOST}|${WEBAPP_HOST_DEFAULT}|g" \
    -e "s|\${ALERTMANAGER_TARGET}|${ALERTMANAGER_TARGET_DEFAULT}|g" \
    "$FINAL_CFG"
fi

# Start Prometheus with the rendered config
exec /bin/prometheus \
  --config.file="$FINAL_CFG" \
  --web.listen-address=0.0.0.0:"${PORT}" \
  --web.enable-lifecycle

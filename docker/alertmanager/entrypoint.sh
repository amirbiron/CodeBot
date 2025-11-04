#!/usr/bin/env sh
set -e

# Default listen port provided by Render via $PORT
PORT="${PORT:-9093}"

# Ensure webhook URL is provided and valid (Alertmanager does not expand env vars in YAML)
if [ -z "${ALERT_WEBHOOK_URL:-}" ]; then
  echo "ERROR: ALERT_WEBHOOK_URL is not set" >&2
  exit 1
fi

case "$ALERT_WEBHOOK_URL" in
  http://*|https://*) ;;
  *)
    echo "ERROR: ALERT_WEBHOOK_URL must start with http/https (got: $ALERT_WEBHOOK_URL)" >&2
    exit 1
    ;;
esac

# Render config from template by replacing the placeholder with the actual URL
tmp_cfg="$(mktemp)"
# Escape characters that are special for sed replacement: &, | (delimiter), and \
escaped_url=$(printf '%s' "$ALERT_WEBHOOK_URL" | sed -e 's/[\\&|]/\\&/g')
sed 's|${ALERT_WEBHOOK_URL}|'"$escaped_url"'|g' /etc/alertmanager/alertmanager.render.yml > "$tmp_cfg"

exec /bin/alertmanager \
  --config.file="$tmp_cfg" \
  --web.listen-address=0.0.0.0:"${PORT}"

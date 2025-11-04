# Alertmanager for Render
FROM prom/alertmanager:latest

# Copy config template and entrypoint from repo root (Render build context is repo root)
COPY docker/alertmanager/alertmanager.render.yml /etc/alertmanager/alertmanager.render.yml
COPY --chmod=0755 docker/alertmanager/entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]

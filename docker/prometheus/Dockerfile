# Prometheus for Render
FROM prom/prometheus:latest

# Copy configuration templates from repo root (Render build context is repo root)
COPY docker/prometheus/prometheus.render.yml /etc/prometheus/prometheus.render.yml
COPY docker/prometheus/alerts.yml /etc/prometheus/alerts.yml

# Copy entrypoint from repo root
COPY --chmod=0755 docker/prometheus/entrypoint.sh /entrypoint.sh

# Prometheus will be started by entrypoint with dynamic listen port
ENTRYPOINT ["/entrypoint.sh"]

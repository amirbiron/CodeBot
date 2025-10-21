# Prometheus for Render
FROM prom/prometheus:latest

# Copy configuration templates
COPY prometheus.render.yml /etc/prometheus/prometheus.render.yml
COPY ../prometheus/alerts.yml /etc/prometheus/alerts.yml

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Prometheus will be started by entrypoint with dynamic listen port

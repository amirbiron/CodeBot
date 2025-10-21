# Alertmanager for Render
FROM prom/alertmanager:latest

# Copy config template and entrypoint
COPY alertmanager.render.yml /etc/alertmanager/alertmanager.render.yml
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]

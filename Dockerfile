FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DASHBOARD_HOST=0.0.0.0 \
    FLUENTD_HOST=fluentd \
    QDRANT_HOST=http://qdrant:6333

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ ./scripts/
COPY daemon/daemon.py daemon/config.docker.yaml ./daemon/
COPY frontend/ ./frontend/
COPY docker-entrypoint.sh ./
RUN chmod +x ./docker-entrypoint.sh && mkdir -p ./daemon/logs

EXPOSE 8080
ENTRYPOINT ["/app/docker-entrypoint.sh"]

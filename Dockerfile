FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies (curl for healthcheck, GDAL for geopandas/fiona)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code + data
COPY . .

EXPOSE 8050

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8050/health || exit 1

CMD ["sh", "-c", "gunicorn app:server --bind ${HOST:-0.0.0.0}:${PORT:-8050} --workers ${GUNICORN_WORKERS:-4} --timeout ${GUNICORN_TIMEOUT:-120} --access-logfile - --error-logfile -"]

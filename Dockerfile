# Always-on image (Fly.io / Docker / VPS): API + built React UI + in-process scheduler
# (live candle fetch → scan → lifecycle refresh). PythonAnywhere does NOT use this file.
FROM node:20-alpine AS front
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY backend ./backend
COPY symbols.yaml ./symbols.yaml
COPY scripts ./scripts
COPY --from=front /fe/dist ./frontend/dist
ENV PYTHONPATH=/app/backend \
    TZ=Europe/Paris \
    CACHE_DIR=/data/cache \
    RESULTS_DIR=/data/results \
    ENABLE_SCHEDULER=true \
    ENABLE_FETCH=true
RUN mkdir -p /data/cache /data/results
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/healthz" || exit 1
# ONE worker on purpose: the APScheduler lives in-process and SQLite is single-writer.
CMD ["sh", "-c", "exec uvicorn app.api.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]

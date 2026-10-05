# OB 5-star scanner — API + static frontend
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt mcp

COPY backend ./backend
COPY symbols.yaml ./symbols.yaml
COPY scripts ./scripts
COPY frontend/dist ./frontend/dist

ENV PYTHONPATH=/app/backend
ENV TZ=Europe/Paris
ENV CACHE_DIR=/app/data/cache
ENV RESULTS_DIR=/app/data/results

RUN mkdir -p /app/data/cache /app/data/results

EXPOSE 8000

# Serve API; mount frontend dist via StaticFiles if configured, else reverse-proxy in host
CMD ["uvicorn", "app.api.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]

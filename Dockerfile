# Multi-stage: build React UI, then serve API + static
FROM node:20-alpine AS front
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

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
COPY --from=front /fe/dist ./frontend/dist
ENV PYTHONPATH=/app/backend
ENV TZ=Europe/Paris
ENV CACHE_DIR=/app/data/cache
ENV RESULTS_DIR=/app/data/results
RUN mkdir -p /app/data/cache /app/data/results
EXPOSE 8000
CMD uvicorn app.api.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}

# Stage 1: build WebUI
FROM node:22-alpine AS webui-builder
WORKDIR /app/webui
COPY webui/package.json webui/package-lock.json ./
RUN npm ci
COPY webui ./
RUN npm run build

# Stage 2: runtime
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    BAIDU2API_DATA_DIR=/app/data \
    BAIDU2API_CONFIG_PATH=/app/data/config.toml \
    BAIDU2API_COOKIE_FILE=/app/data/cookies.json

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=webui-builder /app/static/admin /app/static/admin

RUN mkdir -p /app/data \
    && chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]

# Baidu2API

Convert Baidu Wenxin Assistant (`chat.baidu.com` / `wenxin.baidu.com`) into an **OpenAI-compatible API**, with a light-theme React admin console at `/admin`.

Language: [中文](README.md) | [English](README.en.md)

> **Disclaimer**: For research/education only. Follow Baidu ToS and local laws. Authors are not responsible for account bans or any damages.

## Features

- OpenAI-compatible `GET /v1/models` and `POST /v1/chat/completions` (stream / non-stream)
- Admin UI `/admin`: cookies & API keys, API tester, settings (session isolation, context, backup import/export)
- Multi-cookie pool with failover
- Optional API key auth; invalid keys return **401**
- Tool calling (XML → OpenAI `tool_calls`)
- Docker images published to both **GHCR** and **Docker Hub**

## Models

Aligned with live `usableModel` (2026-07):

| API model id | Baidu `modelName` | Notes |
| --- | --- | --- |
| `deepseek-r1` | `DeepSeek-R1` | Forced thinking |
| `deepseek-v4-pro` | `DeepSeek-V4` | Pro + thinking |
| `deepseek-v4-pro-nothinking` | `DeepSeek-V4` | Pro, no thinking |
| `deepseek-v4-flash` | `DeepSeek-V4-Flash` | Flash + thinking |
| `deepseek-v4-flash-nothinking` | `DeepSeek-V4-Flash` | Flash, no thinking |
| `ernie-5.1` / `ERINE-5.1` | `ERINE-5.1` | Wenxin 5.1 + thinking |
| `ernie-5.1-nothinking` / `ERINE-5.1-nothinking` | `ERINE-5.1` | Wenxin 5.1, no thinking |
| `smartmode` | `smartMode` | Smart mode |
| `smartmode-thinking` | `smartMode` | Smart mode + deep search/thinking |

## Quick start

### Docker Compose (recommended)

```bash
cp .env.example .env
# Only mount ./data — first start auto-creates:
#   ./data/config.toml
#   ./data/cookies.json
docker compose up -d
# Local source build for development (must build, do not only up):
# docker compose -f docker-compose-dev.yml up -d --build
```

- API: `http://localhost:8000/v1`
- Admin: `http://localhost:8000/admin` (admin key from `.env` `BAIDU2API_ADMIN_KEY`)
- Data dir: `./data/` (config + cookies persistence)

If base image pulls fail, override mirrors in `.env` then rebuild:

```bash
# .env
NODE_IMAGE=docker.m.daocloud.io/library/node:22-alpine
PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.13-slim

docker compose -f docker-compose-dev.yml build --no-cache --pull
docker compose -f docker-compose-dev.yml up -d
```

### Local

```bash
pip install -r requirements.txt
cd webui && npm ci && npm run build && cd ..
python main.py --config config.toml
```

### Pull images

Repos: `dijiaozhibei-top/baidu2api` (GHCR) / `dijiaozhibei/baidu2api` (Docker Hub)

**Official:**

```bash
docker pull ghcr.io/dijiaozhibei-top/baidu2api:latest
docker pull dijiaozhibei/baidu2api:latest
```

**Without registry prefix (Docker Hub):**

```bash
docker pull dijiaozhibei/baidu2api:latest
```

**China mirrors (Docker Hub):**

```bash
docker pull docker.1ms.run/dijiaozhibei/baidu2api:latest
docker pull gh-proxy.org/docker/dijiaozhibei/baidu2api:latest
```

**China mirrors (GHCR):**

```bash
docker pull ghcr.nju.edu.cn/dijiaozhibei-top/baidu2api:latest
docker pull gh-proxy.org/docker/ghcr.io/dijiaozhibei-top/baidu2api:latest
```

## API example

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-secret-key" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "hello"}],
    "stream": false
  }'
```

When `api_keys` is configured, missing/invalid bearer tokens return **HTTP 401**.

## Config

Docker reads/writes `./data/config.toml` and `./data/cookies.json` (auto-created on first start if missing).  
Template: [`config.default.toml`](config.default.toml). Env vars: [`.env.example`](.env.example).

Key fields: cookies pool (optional — visitor cookies can be auto-fetched), `auth.api_keys`, `auth.admin_key` / `BAIDU2API_ADMIN_KEY`, context limits, cookie persistence.

## Development

```bash
python main.py --port 8000
cd webui && npm run dev   # proxies to :8000
python test_server.py
```

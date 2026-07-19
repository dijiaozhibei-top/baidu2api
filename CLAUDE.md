# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`baidu2api` — reverse-engineered client for Baidu Wenxin Assistant (`chat.baidu.com` / `wenxin.baidu.com`) exposed as an OpenAI-compatible HTTP API, plus a light-theme React admin WebUI at `/admin`.

Requires Python ≥ 3.13. WebUI build requires Node.js 20+.

## Commands

```bash
# Install backend
pip install -r requirements.txt
# or
uv sync

# Build admin WebUI → static/admin
cd webui && npm ci && npm run build && cd ..

# Run server (default 0.0.0.0:8000)
python main.py --config config.toml
python main.py --host 0.0.0.0 --port 8000

# WebUI dev (Vite proxies /admin API + /v1 to :8000)
cd webui && npm run dev

# CLI against Baidu (bypasses Flask)
python baidu_chat.py "query" --model deepseek-v4-flash
python baidu_chat.py "query" --model smartmode-thinking --cookies "BAIDUID=..."

# Tests (mock Flask integration; not pytest)
python test_server.py

# Docker (builds image locally)
cp .env.example .env
docker compose up -d --build
```

No lint/typecheck toolchain. CI (`.github/workflows/docker-publish.yml`) multi-arch builds and pushes to **GHCR** (`ghcr.io/dijiaozhibei-top/baidu2api`) and **Docker Hub** (`dijiaozhibei/baidu2api`). Requires repo secrets `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`.

## Architecture

```
OpenAI client / Admin WebUI
  → main.py (Flask)
      /v1/*          OpenAI surface + optional API-key auth (invalid → 401)
      /admin/*       JWT admin API + static SPA (static/admin)
        → admin_api.AdminState  (cookies, keys, context, password; persists config.toml)
        → client_pool.BaiduClientPool
            → baidu_chat.BaiduChatClient  (token, payload, SSE)
        → tool_calling (message compact + XML tools)
```

### Modules

| Path | Role |
|---|---|
| `main.py` | Flask app, model list/map, auth, stream/sync shaping, runtime reload from admin |
| `admin_api.py` | Admin login/JWT, config/settings/keys CRUD, SPA mount |
| `baidu_chat.py` | Homepage token scrape, `chat_token`, conversation SSE, model wire format |
| `client_pool.py` | Multi-cookie least-inflight pool + failover |
| `tool_calling.py` | Prompt compaction + XML tool_calls parse |
| `webui/` | React + Vite + Tailwind admin (light theme); build outDir `static/admin` |
| `config.toml` | Cookies, auth, context, cookie persistence |
| `test_server.py` | Mocked integration tests |

### Baidu protocol (load-bearing)

- Homepage `GET https://chat.baidu.com` → `token`/`lid` from `<script name="aiTabFrameBaseData">`.
- `chat_token = base64("{token}|{md5(query)}|{ms}|{lid}")-{lid}-3`
- Chat: `POST /aichat/api/conversation` SSE.
- Live models (2026-07 `usableModel`): `smartMode`, `DeepSeek-V4`, `DeepSeek-V4-Flash`, `DeepSeek-R1`, `ERINE-5.1`.
- Wire `usedModel.modelFunction`: `thinkMode` is string `"0"`/`"1"` (not object); when thinkMode present, omit `internetSearch`. `deepSearch` stays `"0"`/`"1"`.
- `isDeepseek` header is `"1"` for any selected model (live client behavior).
- Thinking/content extracted from SSE `message` generators (`markdown-yiyan`, `thinkingSteps`, …) → OpenAI `content` / `reasoning_content`.

### Admin WebUI contract

Minimal admin surface used by the SPA:

- `POST /admin/login` `{admin_key}` → `{success, token, expires_in}`
- `GET /admin/verify` Bearer JWT
- `GET/PUT /admin/settings`, `POST /admin/settings/password`
- `GET /admin/config`, export/import, `POST/DELETE /admin/keys/...`
- `GET /admin/version`
- Static SPA under `/admin/` (production `base: '/admin/'`)

Nav pages: **配置管理** (cookies + API keys), **API 测试**, **设置中心** (security, context, 会话独立拆分, model aliases, backup). No DeepSeek account pool / proxies / Vercel.

### OpenAI surface

- Auth optional: non-empty `[auth].api_keys` requires `Authorization: Bearer`; wrong key → **401**.
- Models: `deepseek-r1`, `deepseek-v4-pro[-nothinking]`, `deepseek-v4-flash[-nothinking]`, `ernie-5.1`/`ERINE-5.1`[+`-nothinking`], `smartmode`, `smartmode-thinking`.
- `fresh_conversation` (default true) opens a new Baidu session per request; multi-turn history compacted locally.

## When changing reverse-engineered behavior

Validate against live `chat.baidu.com` / `usableModel` before changing token algorithm, `usedModel` shape, or SSE extraction. Keep README model tables and `MODEL_LIST`/`MODEL_MAP`/`BaiduChatClient.MODELS` aligned.

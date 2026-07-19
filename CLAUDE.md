# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`wenxin2api` — reverse-engineered client for Baidu Wenxin Assistant (`chat.baidu.com`) exposed as an OpenAI-compatible HTTP API. Pure-algorithm token generation; no browser automation at runtime.

Requires Python ≥ 3.13.

## Commands

```bash
# Install
pip install -r requirements.txt
# or with uv (lockfile present)
uv sync

# Run OpenAI-compatible server (default 0.0.0.0:8000)
python main.py --config config.toml
python main.py --host 0.0.0.0 --port 8000

# Direct CLI against Baidu (bypasses Flask)
python baidu_chat.py "query" --model ernie-4.5
python baidu_chat.py "query" --model deepseek-r1 --deep-search
python baidu_chat.py "query" --model deepseek-v4-pro --cookies "BAIDUID=..."

# Tests (mock-based Flask integration suite; not pytest)
python test_server.py

# Docker
docker compose up -d --build
```

There is no lint/typecheck/format toolchain configured. CI (`.github/workflows/docker-publish.yml`) only builds and pushes the Docker image to GHCR on push to `main`/`master` and on `v*.*.*` tags.

## Architecture

Request path:

```
OpenAI client
  → main.py (Flask: /v1/models, /v1/chat/completions)
    → tool_calling.messages_to_prompt  (flatten OpenAI messages + optional tools prompt)
    → client_pool.BaiduClientPool      (least-inflight cookie selection + failover)
      → baidu_chat.BaiduChatClient     (token, payload, SSE → text/thinking chunks)
    → tool_calling.parse_tool_calls    (XML tool output → OpenAI tool_calls)
  → OpenAI-shaped JSON or SSE response
```

### Modules

| File | Role |
|---|---|
| `main.py` | Flask app, config load, auth, model alias map, stream/sync response shaping |
| `baidu_chat.py` | Reverse-engineered Baidu client: homepage token scrape, `chat_token` algorithm, conversation POST, SSE parse, cookie refresh |
| `client_pool.py` | Multi-cookie pool: pick lowest-inflight client, optional fresh conversation per request, retry across cookies |
| `tool_calling.py` | Message compaction, tool system prompt injection, XML `<tool_calls>` parsing |
| `config.toml` | Cookies, server bind, API keys, context limits, cookie persistence |
| `config/` | Captured minified JS from Baidu front-end (reference for reverse engineering; not imported at runtime) |
| `test_server.py` | Mocks `BaiduChatClient` and exercises Flask routes + tool/auth/context paths |

### Baidu protocol (load-bearing details)

- Homepage `GET https://chat.baidu.com` → extract `token`/`lid` from `<script name="aiTabFrameBaseData">`.
- `chat_token = base64("{token}|{md5(query)}|{ms_timestamp}|{lid}")-{lid}-3`
- Chat: `POST https://chat.baidu.com/aichat/api/conversation` as SSE (`text/event-stream`).
- Model selection is payload-driven (`usedModel.modelName`, `deepSearch`, headers like `isDeepseek`), not a separate endpoint.
- SSE event types: `basedata`, `ping`, `message`. Text is pulled from `message.content.generator` (component-specific shapes: `markdown-yiyan`, `thinkingSteps`, etc.).
- Thinking models use `-think` suffix or `deep_search=True` → mapped to OpenAI `reasoning_content`.
- Timeouts are intentional anti-hang guards (homepage 10s, conversation 30s, SSE stall ~8s).
- 401/403 (and some 400/429 auth markers) trigger cookie refresh + single retry inside the client; pool then fails over to the next cookie.

### OpenAI surface

- Auth: optional. If `config.toml [auth].api_keys` is non-empty, every request needs `Authorization: Bearer <key>`. Empty = open (local default).
- Context: with `fresh_conversation = true` (default), each request opens a new Baidu session; OpenAI multi-turn history is compacted locally (`max_chars` / `max_messages` / `max_message_chars`) into one prompt string.
- Tools: when `tools` is present, a system prompt forces XML tool-call output; server parses it into OpenAI `tool_calls`. Stream mode buffers content until end when tools are enabled so partial XML is not streamed mid-call.
- Model aliases in `main.MODEL_MAP` / `BaiduChatClient.MODEL_ALIASES` accept several names (`baidu-smart`, `baidu-deepseek`, `gpt-4`, etc.) and map to internal keys: `ernie-4.5`, `deepseek-r1`, `deepseek-v4-pro` (+ `-think`).

### Config notes

- Cookies: `[cookies].value` (single) or `.values` (list for pool). Empty → auto-fetch from homepage; optional persist via `[cookie_persistence] cookie_file` (default `cookies.json`, gitignored). Multi-cookie pool writes `cookies.N.json`.
- Docker mounts `./config.toml` (ro) and `./cookies.json`.
- `tomllib` is preferred; `tomli` is a fallback for older Python (project itself requires 3.13).

## When changing reverse-engineered behavior

Baidu front-end/API can change without notice. Prefer validating against live `chat.baidu.com` (or captured assets under `config/`) before rewriting token generation, payload fields, or SSE content extraction. Keep README model tables and `MODEL_LIST`/`MODEL_MAP` in `main.py` aligned when adding models.

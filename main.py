import os
import time
import argparse
import json
from typing import Optional, Dict, Any

from flask import Flask, request, jsonify, Response
from baidu_chat import _log, BaiduChatClient
from client_pool import BaiduClientPool
from tool_calling import messages_to_prompt, parse_tool_calls
from admin_api import admin_state, register_admin_routes


# ------------------------------------------------------------------
# Config loader
# ------------------------------------------------------------------
def load_config(path: str = "config.toml") -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        pass
    try:
        import tomli
        with open(path, "rb") as f:
            return tomli.load(f)
    except Exception:
        pass
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}


# ------------------------------------------------------------------
# Flask App
# ------------------------------------------------------------------
app = Flask(__name__)
app.config["JSON_AS_ASCII"] = True
client: Optional[BaiduClientPool] = None
api_keys: set[str] = set()
context_options: Dict[str, Any] = {
    "context_max_chars": 12000,
    "context_max_messages": 16,
    "context_max_message_chars": 2000,
}
extra_model_aliases: Dict[str, str] = {}


# Canonical public model ids (aligned with chat.baidu.com usableModel, 2026-07)
CANONICAL_MODELS = [
    "deepseek-r1",
    "deepseek-v4-pro",
    "deepseek-v4-pro-nothinking",
    "deepseek-v4-flash",
    "deepseek-v4-flash-nothinking",
    "ernie-5.1",
    "ernie-5.1-nothinking",
    "smartmode",
    "smartmode-thinking",
]

# Also expose exact Baidu-cased ids the user listed
PUBLIC_MODEL_IDS = CANONICAL_MODELS + [
    "ERINE-5.1",
    "ERINE-5.1-nothinking",
]

MODEL_LIST = [
    {"id": mid, "object": "model", "created": int(time.time()), "owned_by": "baidu"}
    for mid in PUBLIC_MODEL_IDS
]

# Map public / alias names -> internal BaiduChatClient keys
MODEL_MAP = {
    "deepseek-r1": "deepseek-r1",
    "deepseek-v4-pro": "deepseek-v4-pro",
    "deepseek-v4-pro-nothinking": "deepseek-v4-pro-nothinking",
    "deepseek-v4-flash": "deepseek-v4-flash",
    "deepseek-v4-flash-nothinking": "deepseek-v4-flash-nothinking",
    "ernie-5.1": "ernie-5.1",
    "ernie-5.1-nothinking": "ernie-5.1-nothinking",
    "ERINE-5.1": "ernie-5.1",
    "ERINE-5.1-nothinking": "ernie-5.1-nothinking",
    "smartmode": "smartmode",
    "smartmode-thinking": "smartmode-thinking",
    "baidu-deepseek-r1": "deepseek-r1",
    "baidu-deepseek-v4-pro": "deepseek-v4-pro",
    "baidu-deepseek-v4-pro-nothinking": "deepseek-v4-pro-nothinking",
    "baidu-deepseek-v4-flash": "deepseek-v4-flash",
    "baidu-deepseek-v4-flash-nothinking": "deepseek-v4-flash-nothinking",
    "baidu-ernie-5.1": "ernie-5.1",
    "baidu-ernie-5.1-nothinking": "ernie-5.1-nothinking",
    "baidu-smartmode": "smartmode",
    "baidu-smartmode-thinking": "smartmode-thinking",
    "baidu-smart": "smartmode",
    "baidu-deepseek": "deepseek-r1",
    "baidu-ds-v4": "deepseek-v4-pro",
    "baidu-dsv4pro": "deepseek-v4-pro",
    "baidu-ds-v4-flash": "deepseek-v4-flash",
    "gpt-3.5-turbo": "deepseek-v4-flash",
    "gpt-4": "deepseek-v4-pro",
    "gpt-4-turbo": "deepseek-v4-pro",
    "gpt-4o": "deepseek-v4-flash",
}


def _error(message: str, status: int = 400, err_type: str = "invalid_request"):
    return jsonify({"error": {"message": message, "type": err_type}}), status


def _resolve_server_config(config: Dict[str, Any], host: str, port: int) -> tuple[str, int]:
    server_cfg = config.get("server", {})
    if isinstance(server_cfg, dict):
        host = server_cfg.get("host", host)
        port = int(server_cfg.get("port", port))
    host = os.environ.get("BAIDU2API_HOST", host)
    if os.environ.get("PORT"):
        port = int(os.environ["PORT"])
    elif os.environ.get("BAIDU2API_PORT"):
        port = int(os.environ["BAIDU2API_PORT"])
    return host, port


def _resolve_client_config(config: Dict[str, Any]) -> Dict[str, Any]:
    cookies_cfg = config.get("cookies", {})
    cookie_values = []
    if isinstance(cookies_cfg, dict):
        values = cookies_cfg.get("values")
        value = cookies_cfg.get("value", "")
        if isinstance(values, list):
            cookie_values.extend(str(item).strip() for item in values if str(item).strip())
        if value:
            cookie_values.append(str(value).strip())
    elif cookies_cfg:
        cookie_values.append(str(cookies_cfg).strip())
    headers_cfg = config.get("headers", {})
    persistence_cfg = config.get("cookie_persistence", {})
    context_cfg = config.get("context", {})

    return {
        "cookie_values": cookie_values,
        "user_agent": headers_cfg.get("user_agent") if isinstance(headers_cfg, dict) else None,
        "cookie_file": (
            persistence_cfg.get("cookie_file")
            if isinstance(persistence_cfg, dict)
            else config.get("cookie_file")
        ) or "cookies.json",
        "auto_save_cookies": (
            persistence_cfg.get("auto_save_cookies")
            if isinstance(persistence_cfg, dict)
            else config.get("auto_save_cookies", True)
        ),
        "context_max_chars": int(context_cfg.get("max_chars", 12000)) if isinstance(context_cfg, dict) else 12000,
        "context_max_messages": int(context_cfg.get("max_messages", 16)) if isinstance(context_cfg, dict) else 16,
        "context_max_message_chars": int(context_cfg.get("max_message_chars", 2000)) if isinstance(context_cfg, dict) else 2000,
        "fresh_conversation": bool(
            context_cfg.get("fresh_conversation", True)
            if isinstance(context_cfg, dict)
            else True
        ),
    }


def _resolve_api_keys(config: Dict[str, Any]) -> set[str]:
    auth_cfg = config.get("auth", {})
    if not isinstance(auth_cfg, dict):
        return set()

    configured = auth_cfg.get("api_keys") or auth_cfg.get("api_key") or []
    if isinstance(configured, str):
        configured = [configured]
    if not isinstance(configured, list):
        return set()
    return {str(key).strip() for key in configured if str(key).strip()}


def _resolve_admin_key(config: Dict[str, Any]) -> str:
    env_key = os.environ.get("BAIDU2API_ADMIN_KEY") or os.environ.get("ADMIN_KEY")
    if env_key:
        return env_key
    auth_cfg = config.get("auth", {})
    if isinstance(auth_cfg, dict) and auth_cfg.get("admin_key"):
        return str(auth_cfg["admin_key"])
    return "baidu2api"


def _resolve_model(model: str) -> str:
    if not model:
        return "deepseek-v4-flash"
    if model in MODEL_MAP:
        return MODEL_MAP[model]
    if model in extra_model_aliases:
        return extra_model_aliases[model]
    lower = {k.lower(): v for k, v in MODEL_MAP.items()}
    if model.lower() in lower:
        return lower[model.lower()]
    alias_lower = {k.lower(): v for k, v in extra_model_aliases.items()}
    if model.lower() in alias_lower:
        return alias_lower[model.lower()]
    if model in BaiduChatClient.MODELS:
        return model
    if model.lower() in {k.lower() for k in BaiduChatClient.MODELS}:
        return next(k for k in BaiduChatClient.MODELS if k.lower() == model.lower())
    return "deepseek-v4-flash"


def _check_auth():
    path = request.path or ""
    if path.startswith("/admin") or path in ("/healthz", "/readyz"):
        return None

    if not api_keys:
        return None

    auth_header = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return _error("Missing Authorization bearer token", 401, "unauthorized")

    token = auth_header[len(prefix):].strip()
    # Accept either a configured OpenAI API key, or a valid admin JWT
    # (admin WebUI loads /v1/models via authFetch with the admin token).
    if token in api_keys:
        return None
    try:
        from admin_api import admin_state
        if admin_state.verify_token(token):
            return None
    except Exception:
        pass
    return _error("Invalid API key", 401, "unauthorized")


@app.before_request
def require_api_key():
    return _check_auth()


@app.route("/v1/models", methods=["GET"])
def list_models():
    _log("INFO", f"GET /v1/models  from {request.remote_addr}")
    return jsonify({"object": "list", "data": MODEL_LIST})


@app.route("/v1/chat/completions", methods=["POST"])
def chat_completions():
    req = request.get_json(force=True, silent=True) or {}
    if not req:
        return _error("Invalid JSON body")

    model = req.get("model", "deepseek-v4-flash")
    messages = req.get("messages", [])
    tools = req.get("tools") or []
    tool_choice = req.get("tool_choice")
    stream = req.get("stream", False)

    baidu_model = _resolve_model(model)
    deep_search = bool(req.get("deep_search", False))
    query = messages_to_prompt(
        messages,
        tools if isinstance(tools, list) else [],
        tool_choice,
        max_chars=int(context_options["context_max_chars"]),
        max_messages=int(context_options["context_max_messages"]),
        max_message_chars=int(context_options["context_max_message_chars"]),
    )

    if not query:
        return _error("No user message found")

    _log(
        "INFO",
        f"POST /v1/chat/completions  model={model}->{baidu_model}  stream={stream}  "
        f"tools={len(tools) if isinstance(tools, list) else 0}  query_len={len(query)}",
    )

    has_tools = isinstance(tools, list) and bool(tools)
    if stream:
        return _handle_stream(query, baidu_model, deep_search, model, has_tools)
    return _handle_sync(query, baidu_model, deep_search, model)


def _handle_stream(query: str, baidu_model: str, deep_search: bool, display_model: str, has_tools: bool = False):
    if not client:
        return _error("Client not initialized", 500, "internal_error")

    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def generate():
        yield _sse({
            "id": "chatcmpl-baidu",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": display_model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        })

        try:
            content_parts = []
            for chunk in client.chat_to_openai_chunks(query, model=baidu_model, deep_search=deep_search):
                content = chunk.get("content")
                if not content:
                    continue
                if chunk["type"] == "content":
                    content_parts.append(content)
                    if not has_tools:
                        yield _sse({
                            "id": "chatcmpl-baidu",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": display_model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": content},
                                "finish_reason": None,
                            }],
                        })
                elif chunk["type"] == "reasoning_content":
                    yield _sse({
                        "id": "chatcmpl-baidu",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": display_model,
                        "choices": [{
                            "index": 0,
                            "delta": {"reasoning_content": content},
                            "finish_reason": None,
                        }],
                    })

            parsed_content, tool_calls = parse_tool_calls("".join(content_parts))
            if tool_calls:
                if parsed_content:
                    yield _sse({
                        "id": "chatcmpl-baidu",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": display_model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": parsed_content},
                            "finish_reason": None,
                        }],
                    })
                for idx, tool_call in enumerate(tool_calls):
                    yield _sse({
                        "id": "chatcmpl-baidu",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": display_model,
                        "choices": [{
                            "index": 0,
                            "delta": {"tool_calls": [{
                                "index": idx,
                                "id": tool_call["id"],
                                "type": "function",
                                "function": tool_call["function"],
                            }]},
                            "finish_reason": None,
                        }],
                    })
                yield _sse({
                    "id": "chatcmpl-baidu",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": display_model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                })
                yield "data: [DONE]\n\n"
                return
            if has_tools and parsed_content:
                yield _sse({
                    "id": "chatcmpl-baidu",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": display_model,
                    "choices": [{
                        "index": 0,
                        "delta": {"content": parsed_content},
                        "finish_reason": None,
                    }],
                })
        except Exception as e:
            _log("ERROR", f"Stream error: {e}")
            yield _sse({"error": {"message": str(e), "type": "internal_error"}})
            return

        yield _sse({
            "id": "chatcmpl-baidu",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": display_model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        })
        yield "data: [DONE]\n\n"

    return Response(generate(), mimetype="text/event-stream")


def _handle_sync(query: str, baidu_model: str, deep_search: bool, display_model: str):
    if not client:
        return _error("Client not initialized", 500, "internal_error")

    try:
        result = client.chat_to_openai_sync(query, model=baidu_model, deep_search=deep_search)
        content, tool_calls = parse_tool_calls(result.get("content", ""))
        message = {
            "role": "assistant",
            "content": content,
        }
        if result.get("reasoning_content"):
            message["reasoning_content"] = result["reasoning_content"]
        finish_reason = "stop"
        if tool_calls:
            message["tool_calls"] = tool_calls
            finish_reason = "tool_calls"
        return jsonify({
            "id": "chatcmpl-baidu",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": display_model,
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }],
        })
    except Exception as e:
        _log("ERROR", f"Sync error: {e}")
        return jsonify({"error": {"message": str(e), "type": "internal_error"}}), 500


def _build_client_pool(cookie_values, user_agent, cookie_file, auto_save_cookies, fresh_conversation) -> BaiduClientPool:
    pool = BaiduClientPool(
        cookie_values=cookie_values,
        user_agent=user_agent,
        cookie_file=cookie_file,
        auto_save_cookies=auto_save_cookies,
        fresh_conversation=fresh_conversation,
    )
    return pool


def _warmup_cookies(pool: BaiduClientPool, force_refresh: bool = False) -> Dict[str, Any]:
    """Fetch visitor cookies at startup / on demand so deploy works without manual cookies."""
    try:
        status = pool.ensure_ready(force_refresh=force_refresh)
        admin_state.set_runtime_cookie_status(status)
        return status
    except Exception as e:
        _log("WARN", f"Cookie auto-fetch failed: {e}")
        status = {
            "source": "none",
            "cookie_count": 0,
            "cookie_names": [],
            "has_token": False,
            "has_lid": False,
            "cookie_string": "",
            "cookie_preview": "",
            "error": str(e),
            "pool_size": 0,
        }
        admin_state.set_runtime_cookie_status(status)
        return status


def _reload_runtime_from_admin():
    """Called when admin WebUI changes config."""
    global client, api_keys, context_options, extra_model_aliases
    with admin_state.lock:
        api_keys = set(admin_state.api_keys)
        context_options = {
            "context_max_chars": admin_state.context_max_chars,
            "context_max_messages": admin_state.context_max_messages,
            "context_max_message_chars": admin_state.context_max_message_chars,
        }
        extra_model_aliases = dict(admin_state.model_aliases)
        client = _build_client_pool(
            cookie_values=list(admin_state.cookie_values),
            user_agent=admin_state.user_agent,
            cookie_file=admin_state.cookie_file,
            auto_save_cookies=admin_state.auto_save_cookies,
            fresh_conversation=admin_state.fresh_conversation,
        )
    # If admin cleared manual cookies, re-warm auto visitor cookies.
    if client and not admin_state.cookie_values:
        _warmup_cookies(client, force_refresh=False)
    else:
        admin_state.set_runtime_cookie_status(client.cookie_status() if client else {})
    _log("INFO", f"Runtime reloaded from admin: keys={len(api_keys)} cookies={len(admin_state.cookie_values)}")


def run_server(host: str = "0.0.0.0", port: int = 8000, config: Optional[Dict[str, Any]] = None, config_path: str = "config.toml"):
    global client, api_keys, context_options, extra_model_aliases
    config = config or {}

    host, port = _resolve_server_config(config, host, port)
    client_cfg = _resolve_client_config(config)
    api_keys = _resolve_api_keys(config)
    context_options = {
        "context_max_chars": client_cfg["context_max_chars"],
        "context_max_messages": client_cfg["context_max_messages"],
        "context_max_message_chars": client_cfg["context_max_message_chars"],
    }
    models_cfg = config.get("models") if isinstance(config.get("models"), dict) else {}
    extra_model_aliases = {str(k): str(v) for k, v in (models_cfg or {}).items()}

    client = _build_client_pool(
        cookie_values=client_cfg["cookie_values"],
        user_agent=client_cfg["user_agent"],
        cookie_file=client_cfg["cookie_file"],
        auto_save_cookies=bool(client_cfg["auto_save_cookies"]),
        fresh_conversation=bool(client_cfg["fresh_conversation"]),
    )

    admin_cfg = config.get("auth", {}) if isinstance(config.get("auth"), dict) else {}
    admin_state.configure(
        config_path=config_path,
        admin_key=_resolve_admin_key(config),
        jwt_expire_hours=int(admin_cfg.get("jwt_expire_hours") or 24),
        api_keys=list(api_keys),
        cookie_values=client_cfg["cookie_values"],
        user_agent=client_cfg["user_agent"],
        cookie_file=client_cfg["cookie_file"],
        auto_save_cookies=bool(client_cfg["auto_save_cookies"]),
        fresh_conversation=bool(client_cfg["fresh_conversation"]),
        context_max_chars=client_cfg["context_max_chars"],
        context_max_messages=client_cfg["context_max_messages"],
        context_max_message_chars=client_cfg["context_max_message_chars"],
        model_aliases=extra_model_aliases,
        version="0.2.0",
        on_config_changed=_reload_runtime_from_admin,
    )
    # Wire admin "auto-fetch cookies" button to the live pool.
    admin_state.set_cookie_fetcher(lambda force=False: _warmup_cookies(client, force_refresh=force) if client else {})
    register_admin_routes(app)

    # Auto-fetch visitor cookies at startup when no manual cookies are configured.
    # This is what makes "deploy without filling cookies" work.
    if not client_cfg["cookie_values"]:
        status = _warmup_cookies(client, force_refresh=False)
        cookie_mode = (
            f"auto-fetch source={status.get('source')} count={status.get('cookie_count')} "
            f"file={client_cfg['cookie_file']}"
        )
        if status.get("error"):
            cookie_mode += f" error={status['error']}"
    else:
        admin_state.set_runtime_cookie_status(client.cookie_status())
        cookie_mode = f"user-provided pool={len(client_cfg['cookie_values'])}"

    _log("INFO", f"Flask server starting at http://{host}:{port}")
    _log("INFO", f"Cookie mode: {cookie_mode}")
    _log("INFO", f"Auth: {'enabled' if api_keys else 'disabled'}")
    _log("INFO", f"Admin WebUI: http://{host}:{port}/admin")
    _log("INFO", "Models: " + ", ".join(CANONICAL_MODELS))
    app.run(host=host, port=port, threaded=True, debug=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Baidu2API OpenAI-compatible server (Flask)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--config", default="config.toml", help="Config file path")
    args = parser.parse_args()

    cfg = load_config(args.config)
    host, port = _resolve_server_config(cfg, args.host, args.port)
    run_server(host=host, port=port, config=cfg, config_path=args.config)

import json
import os
import time
import sys
import socket
import threading
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from main import app, client as main_client
from baidu_chat import BaiduChatClient
from tool_calling import messages_to_prompt


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_flask_server():
    """Test the Flask-based OpenAI-compatible server with a mock Baidu client."""
    port = find_free_port()

    # Create a mock client
    mock_client = BaiduChatClient(cookies=None, cookie_file=None, auto_save_cookies=False)
    mock_client._token = "test_token"
    mock_client._lid = "test_lid"
    mock_client._ori_lid = "test_lid"

    def fake_stream(query, model="smart", deep_search=False, internet_search=False):
        if "<tool_calls>" in query or "Available tools:" in query:
            yield {"type": "text", "content": '<tool_calls><tool_call><name>get_weather</name><arguments>{"city":"北京"}</arguments></tool_call></tool_calls>'}
            yield {"type": "done", "content": ""}
            return
        yield {"type": "text", "content": "Hello"}
        yield {"type": "thinking", "content": "Let me think..."}
        yield {"type": "text", "content": " world!"}
        yield {"type": "done", "content": ""}

    mock_client.chat_stream_text = fake_stream

    def fake_chunks(query, model="smart", deep_search=False, internet_search=False):
        for chunk in fake_stream(query, model, deep_search, internet_search):
            if chunk["type"] == "text":
                yield {"type": "content", "content": chunk["content"]}
            elif chunk["type"] == "thinking":
                yield {"type": "reasoning_content", "content": chunk["content"]}
            elif chunk["type"] == "done":
                break

    mock_client.chat_to_openai_chunks = fake_chunks

    # Patch the global client in main module
    import main as main_mod
    main_mod.client = mock_client
    main_mod.api_keys = set()

    # Configure Flask test client
    app.config["TESTING"] = True
    with app.test_client() as tc:
        results = []

        # Test 1: GET /v1/models
        r = tc.get("/v1/models")
        data = r.get_json()
        results.append({
            "test": "models",
            "status": r.status_code,
            "models": [m["id"] for m in data.get("data", [])]
        })

        # Test 2: POST sync
        r = tc.post("/v1/chat/completions",
                    json={"model": "smartmode", "messages": [{"role": "user", "content": "hello"}], "stream": False})
        data = r.get_json()
        msg = data.get("choices", [{}])[0].get("message", {})
        results.append({
            "test": "chat_sync",
            "status": r.status_code,
            "content": msg.get("content", "")[:50],
            "has_reasoning": msg.get("reasoning_content") is not None,
        })

        # Test 3: POST stream
        r = tc.post("/v1/chat/completions",
                    json={"model": "smartmode", "messages": [{"role": "user", "content": "hello"}], "stream": True})
        raw = r.data.decode("utf-8")
        lines = [ln for ln in raw.strip().split("\n") if ln.startswith("data: ")]
        chunks = []
        for ln in lines:
            payload = ln[6:]
            if payload == "[DONE]":
                chunks.append("[DONE]")
                continue
            try:
                d = json.loads(payload)
                delta = d.get("choices", [{}])[0].get("delta", {})
                if delta.get("content"):
                    chunks.append(delta["content"])
                elif delta.get("role"):
                    chunks.append(f"[role:{delta['role']}]")
                elif d.get("choices", [{}])[0].get("finish_reason"):
                    chunks.append("[finish]")
            except json.JSONDecodeError:
                chunks.append(f"[raw:{payload}]")
        results.append({
            "test": "chat_stream",
            "status": r.status_code,
            "chunks": chunks,
            "full_text": "".join([c for c in chunks if not c.startswith("[")]),
        })

        # Test 4: DeepSeek model
        r = tc.post("/v1/chat/completions",
                    json={"model": "deepseek-r1", "messages": [{"role": "user", "content": "hello"}], "stream": False})
        data = r.get_json()
        msg = data.get("choices", [{}])[0].get("message", {})
        results.append({
            "test": "deepseek_sync",
            "status": r.status_code,
            "has_reasoning": msg.get("reasoning_content") is not None,
            "content": msg.get("content", "")[:50],
        })

        # Test 5: Tool calling sync
        tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get weather by city",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }]
        r = tc.post("/v1/chat/completions",
                    json={
                        "model": "smartmode",
                        "messages": [{"role": "user", "content": "北京天气"}],
                        "tools": tools,
                        "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
                        "stream": False,
                    })
        data = r.get_json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        results.append({
            "test": "tool_call_sync",
            "status": r.status_code,
            "finish_reason": choice.get("finish_reason"),
            "tool_name": msg.get("tool_calls", [{}])[0].get("function", {}).get("name"),
            "arguments": msg.get("tool_calls", [{}])[0].get("function", {}).get("arguments"),
        })

        # Test 6: Tool calling stream
        r = tc.post("/v1/chat/completions",
                    json={"model": "smartmode", "messages": [{"role": "user", "content": "北京天气"}], "tools": tools, "stream": True})
        raw = r.data.decode("utf-8")
        tool_delta = None
        finish_reason = None
        for ln in [ln for ln in raw.strip().split("\n") if ln.startswith("data: ")]:
            payload = ln[6:]
            if payload == "[DONE]":
                continue
            d = json.loads(payload)
            choice = d.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            if delta.get("tool_calls"):
                tool_delta = delta["tool_calls"][0]
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
        results.append({
            "test": "tool_call_stream",
            "status": r.status_code,
            "finish_reason": finish_reason,
            "tool_name": (tool_delta or {}).get("function", {}).get("name"),
        })

        # Test 7: Optional API key auth
        main_mod.api_keys = {"sk-test"}
        r = tc.get("/v1/models")
        results.append({
            "test": "auth_missing",
            "status": r.status_code,
            "error_type": (r.get_json() or {}).get("error", {}).get("type"),
        })
        r = tc.get("/v1/models", headers={"Authorization": "Bearer sk-wrong"})
        results.append({
            "test": "auth_invalid",
            "status": r.status_code,
            "error_type": (r.get_json() or {}).get("error", {}).get("type"),
        })
        r = tc.get("/v1/models", headers={"Authorization": "Bearer sk-test"})
        results.append({
            "test": "auth_valid",
            "status": r.status_code,
        })
        main_mod.api_keys = set()

        compressed = messages_to_prompt(
            [{"role": "user", "content": "old-" + ("x" * 200)}, {"role": "user", "content": "new"}],
            max_chars=80,
            max_messages=2,
            max_message_chars=40,
        )
        results.append({
            "test": "context_compact",
            "contains_new": "new" in compressed,
            "is_limited": len(compressed) <= 80,
        })

    return results


if __name__ == "__main__":
    results = test_flask_server()
    print(json.dumps(results, ensure_ascii=False, indent=2))

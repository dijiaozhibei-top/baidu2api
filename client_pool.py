import threading
from typing import Any, Dict, Generator, List, Optional

from baidu_chat import BaiduChatClient, _log


class BaiduClientPool:
    """Round-robin pool for multiple Baidu cookie sessions."""

    def __init__(
        self,
        cookie_values: Optional[List[str]] = None,
        user_agent: Optional[str] = None,
        cookie_file: Optional[str] = None,
        auto_save_cookies: bool = False,
        fresh_conversation: bool = True,
    ):
        values = [v for v in (cookie_values or []) if v]
        if not values:
            values = [""]

        self._clients = [
            BaiduChatClient(
                cookies=value or None,
                user_agent=user_agent,
                cookie_file=_pool_cookie_file(cookie_file, idx, len(values)),
                auto_save_cookies=auto_save_cookies,
            )
            for idx, value in enumerate(values)
        ]
        self._inflight = [0 for _ in self._clients]
        self._cursor = 0
        self._lock = threading.Lock()
        self._fresh_conversation = fresh_conversation
        _log("INFO", f"Baidu client pool initialized: size={len(self._clients)}")

    def _next_client(self) -> tuple[int, BaiduChatClient]:
        with self._lock:
            total = len(self._clients)
            ordered = [(self._cursor + offset) % total for offset in range(total)]
            idx = min(ordered, key=lambda item: self._inflight[item])
            self._cursor = (idx + 1) % total
            self._inflight[idx] += 1
        return idx, self._clients[idx]

    def _release_client(self, idx: int):
        with self._lock:
            self._inflight[idx] = max(0, self._inflight[idx] - 1)

    def chat_to_openai_chunks(
        self,
        query: str,
        model: str = "deepseek-v4-flash",
        deep_search: bool = False,
        internet_search: bool = False,
    ) -> Generator[Dict[str, str], None, None]:
        last_error: Optional[Exception] = None
        attempts = len(self._clients)

        for _ in range(attempts):
            idx, client = self._next_client()
            try:
                _log("DEBUG", f"Using Baidu client #{idx}")
                if self._fresh_conversation:
                    client.start_new_conversation()
                yield from client.chat_to_openai_chunks(query, model, deep_search, internet_search)
                return
            except Exception as exc:
                last_error = exc
                _log("WARN", f"Baidu client #{idx} failed: {exc}")
            finally:
                self._release_client(idx)

        if last_error:
            raise last_error

    def chat_to_openai_sync(
        self,
        query: str,
        model: str = "deepseek-v4-flash",
        deep_search: bool = False,
        internet_search: bool = False,
    ) -> Dict[str, Any]:
        text_parts = []
        reasoning_parts = []
        for chunk in self.chat_to_openai_chunks(query, model, deep_search, internet_search):
            if chunk["type"] == "content":
                text_parts.append(chunk["content"])
            elif chunk["type"] == "reasoning_content":
                reasoning_parts.append(chunk["content"])
        return {
            "role": "assistant",
            "content": "".join(text_parts),
            "reasoning_content": "".join(reasoning_parts) if reasoning_parts else None,
        }


def _pool_cookie_file(cookie_file: Optional[str], index: int, total: int) -> Optional[str]:
    if not cookie_file:
        return None
    if total <= 1:
        return cookie_file
    if "." not in cookie_file:
        return f"{cookie_file}.{index}"
    stem, suffix = cookie_file.rsplit(".", 1)
    return f"{stem}.{index}.{suffix}"

import re
import sys
import os
import json
import time
import base64
import hashlib
import copy
import requests
import urllib.parse
from typing import Optional, Dict, Any, List, Generator


# ------------------------------------------------------------------
# Color logging (uses colorama installed with Flask)
# ------------------------------------------------------------------
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
except ImportError:
    class _Fore:
        GREEN = YELLOW = RED = CYAN = MAGENTA = BLUE = WHITE = ""
    class _Style:
        BRIGHT = DIM = RESET_ALL = ""
    Fore = _Fore()
    Style = _Style()


def _log(level: str, msg: str):
    ts = time.strftime("%H:%M:%S")
    color_map = {
        "INFO":  Fore.GREEN,
        "WARN":  Fore.YELLOW,
        "ERROR": Fore.RED,
        "DEBUG": Fore.CYAN,
        "TRACE": Fore.MAGENTA,
        "BAIDU": Fore.BLUE,
    }
    c = color_map.get(level, Fore.WHITE)
    line = f"{Fore.WHITE}[{ts}] {c}{Style.BRIGHT}[{level}]{Style.RESET_ALL} {msg}\n"
    try:
        sys.stdout.buffer.write(line.encode("utf-8", "replace"))
    except Exception:
        try:
            sys.stdout.write(line.encode(sys.stdout.encoding or "utf-8", "replace").decode(sys.stdout.encoding or "utf-8", "replace"))
        except Exception:
            pass


class BaiduChatClient:
    """Baidu Chat (chat.baidu.com) API client — pure algorithm + color logging.

    Cookie handling:
    - If user provides cookies via constructor/config, they are used directly.
    - If not provided, cookies are automatically fetched from chat.baidu.com homepage.
    - Session persists cookies across requests; auto-refresh on 401/403.

    Infinite-wait fixes:
    - All network calls have explicit timeouts (10s for home, 30s for SSE, 5s chunk).
    - SSE parser yields a heartbeat sentinel every 8s so the caller can detect stalls.
    - chat() raises RuntimeError on non-2xx after one retry instead of hanging.
    """

    BASE_URL = "https://chat.baidu.com"
    CONVERSATION_API = f"{BASE_URL}/aichat/api/conversation"

    # Captured 2026-07-19 from chat.baidu.com usableModel:
    # smartMode, DeepSeek-V4, DeepSeek-V4-Flash, DeepSeek-R1, ERINE-5.1
    # deepSearch / thinkMode.status control thinking variants.
    MODELS = {
        "deepseek-r1": {
            "usedModel": {
                "modelName": "DeepSeek-R1",
                "modelFunction": {
                    "internetSearch": "1",
                    "deepSearch": "0",
                    "thinkMode": {"status": "1", "disabled": True, "disabledTip": ""},
                },
                "showModelName": "DeepSeek-R1",
            },
            "enter_type": "sidebar_dialog",
            "agt_sess_cnt": 0,
            "anti_ext": {"inputT": None, "ck1": 111, "ck9": 450, "ck10": 346},
            "rank": 1,
            "force_thinking": True,
        },
        "deepseek-v4-pro": {
            "usedModel": {
                "modelName": "DeepSeek-V4",
                "modelFunction": {
                    "internetSearch": "1",
                    "deepSearch": "0",
                    "thinkMode": {"status": "1", "disabled": False, "disabledTip": ""},
                },
                "showModelName": "DeepSeek-V4 Pro",
            },
            "enter_type": "chat_url",
            "agt_sess_cnt": 1,
            "anti_ext": {"inputT": None, "ck1": 117, "ck9": 590, "ck10": 329},
            "rank": 1,
        },
        "deepseek-v4-pro-nothinking": {
            "usedModel": {
                "modelName": "DeepSeek-V4",
                "modelFunction": {
                    "internetSearch": "1",
                    "deepSearch": "0",
                    "thinkMode": {"status": "0", "disabled": False, "disabledTip": ""},
                },
                "showModelName": "DeepSeek-V4 Pro",
            },
            "enter_type": "chat_url",
            "agt_sess_cnt": 1,
            "anti_ext": {"inputT": None, "ck1": 117, "ck9": 590, "ck10": 329},
            "rank": 1,
        },
        "deepseek-v4-flash": {
            "usedModel": {
                "modelName": "DeepSeek-V4-Flash",
                "modelFunction": {
                    "internetSearch": "",
                    "deepSearch": "0",
                    "thinkMode": {"status": "1", "disabled": False, "disabledTip": ""},
                },
                "showModelName": "DeepSeek-V4 Flash",
            },
            "enter_type": "chat_url",
            "agt_sess_cnt": 1,
            "anti_ext": {"inputT": None, "ck1": 117, "ck9": 590, "ck10": 329},
            "rank": 1,
        },
        "deepseek-v4-flash-nothinking": {
            "usedModel": {
                "modelName": "DeepSeek-V4-Flash",
                "modelFunction": {
                    "internetSearch": "",
                    "deepSearch": "0",
                    "thinkMode": {"status": "0", "disabled": False, "disabledTip": ""},
                },
                "showModelName": "DeepSeek-V4 Flash",
            },
            "enter_type": "chat_url",
            "agt_sess_cnt": 1,
            "anti_ext": {"inputT": None, "ck1": 117, "ck9": 590, "ck10": 329},
            "rank": 1,
        },
        "ernie-5.1": {
            "usedModel": {
                "modelName": "ERINE-5.1",
                "modelFunction": {
                    "internetSearch": "1",
                    "deepSearch": "0",
                    "thinkMode": {"status": "1", "disabled": False, "disabledTip": ""},
                },
                "showModelName": "文心5.1",
            },
            "enter_type": "sidebar_dialog",
            "agt_sess_cnt": 0,
            "anti_ext": {"inputT": None, "ck1": 87, "ck9": 353, "ck10": 351},
            "rank": 1,
        },
        "ernie-5.1-nothinking": {
            "usedModel": {
                "modelName": "ERINE-5.1",
                "modelFunction": {
                    "internetSearch": "1",
                    "deepSearch": "0",
                    "thinkMode": {"status": "0", "disabled": False, "disabledTip": ""},
                },
                "showModelName": "文心5.1",
            },
            "enter_type": "sidebar_dialog",
            "agt_sess_cnt": 0,
            "anti_ext": {"inputT": None, "ck1": 87, "ck9": 353, "ck10": 351},
            "rank": 1,
        },
        "smartmode": {
            "usedModel": {
                "modelName": "smartMode",
                "modelFunction": {
                    "internetSearch": "0",
                    "deepSearch": "0",
                    "thinkMode": {"status": "0", "disabled": False, "disabledTip": ""},
                },
                "showModelName": "智能模式",
            },
            "enter_type": "sidebar_dialog",
            "agt_sess_cnt": 0,
            "anti_ext": {"inputT": None, "ck1": 87, "ck9": 353, "ck10": 351},
            "rank": 1,
        },
        "smartmode-thinking": {
            "usedModel": {
                "modelName": "smartMode",
                "modelFunction": {
                    "internetSearch": "0",
                    "deepSearch": "1",
                    "thinkMode": {"status": "1", "disabled": False, "disabledTip": ""},
                },
                "showModelName": "智能模式",
            },
            "enter_type": "sidebar_dialog",
            "agt_sess_cnt": 0,
            "anti_ext": {"inputT": None, "ck1": 864, "ck9": 382, "ck10": 836},
            "rank": 2,
        },
    }
    THINK_OVERRIDES = {
        "usedModel": {
            "modelName": "smartMode",
            "modelFunction": {
                "deepSearch": "1",
                "internetSearch": "0",
                "thinkMode": {"status": "1", "disabled": False, "disabledTip": ""},
            },
        },
        "enter_type": "sidebar_dialog",
        "agt_sess_cnt": 0,
        "anti_ext": {"inputT": None, "ck1": 864, "ck9": 382, "ck10": 836},
        "rank": 2,
    }
    MODEL_ALIASES = {
        "smart": "smartmode",
        "smart-mode": "smartmode",
        "smartmode-think": "smartmode-thinking",
        "smartmode-thinking": "smartmode-thinking",
        "ernie": "ernie-5.1",
        "ernie-5.1": "ernie-5.1",
        "erine-5.1": "ernie-5.1",
        "ERINE-5.1": "ernie-5.1",
        "ERINE-5.1-nothinking": "ernie-5.1-nothinking",
        "wenxin": "ernie-5.1",
        "wenxin-5.1": "ernie-5.1",
        "deepseek": "deepseek-r1",
        "ds-r1": "deepseek-r1",
        "ds-v4": "deepseek-v4-pro",
        "dsv4pro": "deepseek-v4-pro",
        "ds-v4-flash": "deepseek-v4-flash",
        "dsv4flash": "deepseek-v4-flash",
    }

    BASE_URLS = (
        "https://chat.baidu.com",
        "https://wenxin.baidu.com/?enter_type=chat_site",
    )

    def __init__(self, cookies: Optional[str] = None, user_agent: Optional[str] = None,
                 cookie_file: Optional[str] = None, auto_save_cookies: bool = False):
        self.session = requests.Session()
        self._user_cookies = cookies or ""
        self._cookie_file = cookie_file
        self._auto_save = auto_save_cookies
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self._token: Optional[str] = None
        self._lid: Optional[str] = None
        self._ori_lid: Optional[str] = None
        self._last_hint: Optional[str] = None
        self._cookie_source: str = "none"  # user | file | auto | none
        self._headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/event-stream",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://chat.baidu.com/",
            "Origin": "https://chat.baidu.com",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        }

        if self._user_cookies:
            _log("INFO", f"Using user-provided cookies ({len(self._user_cookies)} chars)")
            self._inject_cookie_string(self._user_cookies)
            self._cookie_source = "user"
        else:
            _log("INFO", "No cookies provided — will auto-fetch from chat.baidu.com")

        if self._cookie_file and not self._user_cookies:
            loaded = self._load_cookies_from_file()
            if loaded:
                self._cookie_source = "file"
                _log("INFO", f"Loaded cookies from {self._cookie_file}")

    # ------------------------------------------------------------------
    # Cookie helpers
    # ------------------------------------------------------------------
    def _inject_cookie_string(self, cookie_str: str):
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                self.session.cookies.set(k.strip(), v.strip(), domain="chat.baidu.com", path="/")
                self.session.cookies.set(k.strip(), v.strip(), domain=".baidu.com", path="/")

    def _cookie_string(self) -> str:
        items = []
        for cookie in self.session.cookies:
            items.append(f"{cookie.name}={cookie.value}")
        return "; ".join(items)

    def _save_cookies_to_file(self):
        if not self._cookie_file:
            return
        try:
            data = {
                "cookie_string": self._cookie_string(),
                "timestamp": int(time.time()),
                "token": self._token,
                "lid": self._lid,
            }
            with open(self._cookie_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            _log("INFO", f"Cookies saved → {self._cookie_file}")
        except Exception as e:
            _log("WARN", f"Cookie save failed: {e}")

    def _load_cookies_from_file(self) -> bool:
        if not self._cookie_file or not os.path.exists(self._cookie_file):
            return False
        try:
            with open(self._cookie_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cookie_str = data.get("cookie_string", "")
            if cookie_str:
                self._inject_cookie_string(cookie_str)
                self._token = data.get("token") or self._token
                self._lid = data.get("lid") or self._lid
                return True
        except Exception as e:
            _log("WARN", f"Cookie load failed: {e}")
        return False

    def _ensure_cookies(self):
        if not self.session.cookies or not self._token or not self._lid:
            _log("BAIDU", "Cookie/token missing → fetching homepage for cookies")
            self._get_base_data()

    def _refresh_cookies(self):
        _log("WARN", "Refreshing cookies (clearing old cookies)")
        # Keep user-provided cookies if any; only clear auto/session jar.
        self.session.cookies.clear()
        self._token = None
        self._lid = None
        self._ori_lid = None
        if self._user_cookies:
            self._inject_cookie_string(self._user_cookies)
            self._cookie_source = "user"
        self._get_base_data()

    def start_new_conversation(self):
        self._token = None
        self._lid = None
        self._ori_lid = None
        self._get_base_data()

    def ensure_ready(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Eagerly fetch visitor cookies + token. Safe to call at startup."""
        if force_refresh:
            self._refresh_cookies()
        else:
            self._ensure_cookies()
        return self.cookie_status()

    def cookie_status(self) -> Dict[str, Any]:
        cookie_str = self._cookie_string()
        names = []
        for part in cookie_str.split(";"):
            part = part.strip()
            if "=" in part:
                names.append(part.split("=", 1)[0].strip())
        return {
            "source": self._cookie_source,
            "cookie_count": len(names),
            "cookie_names": names,
            "has_token": bool(self._token),
            "has_lid": bool(self._lid),
            "cookie_string": cookie_str,
            "cookie_preview": (cookie_str[:80] + "...") if len(cookie_str) > 80 else cookie_str,
            "cookie_file": self._cookie_file or "",
            "auto_save": bool(self._auto_save),
            "user_provided": bool(self._user_cookies),
        }

    def _should_refresh_response(self, resp) -> bool:
        if resp.status_code in (401, 403):
            return True
        if resp.status_code not in (400, 429):
            return False
        try:
            body = resp.text[:1000].lower()
        except Exception:
            return False
        markers = ("cookie", "login", "unauthorized", "forbidden", "verify", "captcha", "登录")
        return any(marker in body for marker in markers)

    # ------------------------------------------------------------------
    # Base data (token + lid + auto cookies) — with strict timeout
    # ------------------------------------------------------------------
    def _extract_base_data_from_html(self, html: str) -> Optional[Dict[str, Any]]:
        match = re.search(
            r'<script[^>]*name="aiTabFrameBaseData"[^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            # Some builds embed JSON without the name attribute first.
            match = re.search(
                r'aiTabFrameBaseData["\'\s>]+[^<{]*(\{.*?"token"\s*:\s*".*?".*?\})',
                html,
                re.DOTALL,
            )
            if not match:
                return None
            raw = match.group(1)
        else:
            raw = match.group(1)
        try:
            return json.loads(raw)
        except Exception:
            return None

    def _get_base_data(self) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for url in self.BASE_URLS:
            _log("BAIDU", f"GET {url}  (timeout=10s)")
            try:
                resp = self.session.get(
                    url,
                    headers={
                        **self._headers,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=(5, 10),
                    allow_redirects=True,
                )
            except requests.exceptions.Timeout as e:
                last_error = RuntimeError(f"{url} timed out (10s) — check network / proxy / DNS")
                _log("WARN", str(last_error))
                continue
            except requests.exceptions.ConnectionError as e:
                last_error = RuntimeError(f"Connection error to {url}: {e}")
                _log("WARN", str(last_error))
                continue

            _log(
                "BAIDU",
                f"Homepage status={resp.status_code} final_url={resp.url} cookies_after={len(self.session.cookies)}",
            )
            if not resp.ok:
                last_error = RuntimeError(f"{url} returned {resp.status_code}")
                continue

            data = self._extract_base_data_from_html(resp.text)
            if not data:
                last_error = RuntimeError(
                    "Could not find aiTabFrameBaseData in page HTML — Baidu may have changed the page structure"
                )
                _log("WARN", f"{url}: {last_error}")
                continue

            self._token = data.get("token", "")
            self._lid = data.get("lid", "")
            self._ori_lid = data.get("logParams", {}).get("applid", self._lid)
            if not self._user_cookies:
                self._cookie_source = "auto"
            _log("BAIDU", f"Extracted token={str(self._token)[:20]}... lid={self._lid}")

            # Always try to persist visitor cookies when auto mode is on, so
            # restarts do not need another homepage scrape.
            if self._auto_save:
                self._save_cookies_to_file()
            return data

        if last_error:
            raise last_error
        raise RuntimeError("Failed to auto-fetch Baidu cookies/token from homepage")

    def _generate_chat_token(self, query: str) -> str:
        if not self._token or not self._lid:
            self._get_base_data()
        md5_hash = hashlib.md5(query.encode("utf-8")).hexdigest()
        timestamp = int(time.time() * 1000)
        payload = f"{self._token}|{md5_hash}|{timestamp}|{self._lid}"
        b64 = base64.b64encode(payload.encode()).decode()
        return f"{b64}-{self._lid}-3"

    def _model_spec(self, model: str) -> Dict[str, Any]:
        raw = (model or "deepseek-v4-flash").strip()
        # Support legacy -think suffix as thinking toggle for base models.
        think_suffix = raw.endswith("-think") or raw.endswith("-thinking")
        base_model = raw
        if raw.endswith("-think"):
            base_model = raw[:-6]
        elif raw.endswith("-thinking") and raw not in self.MODELS:
            base_model = raw[:-9]

        model_key = self.MODEL_ALIASES.get(base_model, base_model)
        model_key = self.MODEL_ALIASES.get(model_key, model_key)
        if model_key not in self.MODELS:
            # Case-insensitive fallback
            lower_map = {k.lower(): k for k in self.MODELS}
            model_key = lower_map.get(model_key.lower(), "deepseek-v4-flash")

        spec = copy.deepcopy(self.MODELS.get(model_key, self.MODELS["deepseek-v4-flash"]))
        if think_suffix and not model_key.endswith("-nothinking") and model_key not in (
            "deepseek-r1", "smartmode-thinking",
        ):
            mf = spec["usedModel"]["modelFunction"]
            mf["deepSearch"] = "1"
            if isinstance(mf.get("thinkMode"), dict):
                mf["thinkMode"]["status"] = "1"
            spec["rank"] = max(int(spec.get("rank") or 1), 2)
        return spec

    def _build_message_payload(self, query: str, model: str = "deepseek-v4-flash",
                                 deep_search: bool = False, internet_search: bool = False, rank: Optional[int] = None) -> Dict[str, Any]:
        spec = self._model_spec(model)
        model_cfg = spec["usedModel"]
        if rank is None:
            rank = spec["rank"]
        if deep_search:
            model_cfg["modelFunction"]["deepSearch"] = "1"
            if isinstance(model_cfg["modelFunction"].get("thinkMode"), dict):
                model_cfg["modelFunction"]["thinkMode"]["status"] = "1"
        if internet_search:
            model_cfg["modelFunction"]["internetSearch"] = "1"
        # Live client normalizes usedModel before POST:
        # - thinkMode object -> string "0"/"1"
        # - when thinkMode is present, internetSearch is omitted
        model_cfg = self._normalize_used_model(model_cfg)
        chat_token = self._generate_chat_token(query)
        anti_ext = spec["anti_ext"]
        enter_type = spec["enter_type"]
        agt_sess_cnt = spec["agt_sess_cnt"]
        return {
            "message": {
                "inputMethod": "chat_search",
                "isRebuild": False,
                "content": {
                    "query": "",
                    "agentInfo": {"agent_id": [""], "params": '{"agt_rk":' + str(rank) + ',"agt_sess_cnt":' + str(agt_sess_cnt) + '}'},
                    "agentInfoList": [], "qtype": 0, "extData": {},
                },
                "searchInfo": {
                    "srcid": "", "order": "", "tplname": "", "dqaKey": "",
                    "re_rank": str(rank), "ori_lid": self._ori_lid or "",
                    "sa": "bkb", "enter_type": enter_type,
                    "chatParams": {
                        "setype": "csaitab", "chat_samples": "WISE_NEW_CSAITAB",
                        "chat_token": chat_token, "scene": "",
                    },
                    "isPrivateChat": False, "usedModel": model_cfg,
                    "landingPageSwitch": "", "landingPage": "aitab",
                    "ecomFrom": "", "hasLocPermission": "", "isInnovate": 2,
                    "applid": "", "a_lid": "", "showMindMap": False,
                    "deepDecisionInfo": {"isDeepDecision": 0},
                },
                "from": "", "source": "pc_csaitab",
                "query": [{"type": "TEXT", "data": {"text": {"query": query, "extData": "{}", "text_type": ""}}}],
                "anti_ext": anti_ext,
            },
            "sa": "bkb", "setype": "csaitab", "rank": rank,
        }

    def _normalize_used_model(self, used_model: Dict[str, Any]) -> Dict[str, Any]:
        """Match chat.baidu.com normalizeUsedModelForRequest wire format."""
        out = copy.deepcopy(used_model or {})
        mf = out.get("modelFunction")
        if not isinstance(mf, dict):
            return out
        think = mf.get("thinkMode")
        if isinstance(think, dict):
            status = think.get("status")
            if status in (None, ""):
                status = "0"
            mf["thinkMode"] = str(status)
            mf.pop("internetSearch", None)
        elif think is not None:
            mf["thinkMode"] = str(think)
            mf.pop("internetSearch", None)
        # Keep deepSearch as "0"/"1" strings
        if "deepSearch" in mf and mf["deepSearch"] is not None:
            mf["deepSearch"] = str(mf["deepSearch"])
        if "internetSearch" in mf and mf["internetSearch"] is not None:
            mf["internetSearch"] = str(mf["internetSearch"])
        out["modelFunction"] = mf
        return out

    def _build_headers(self, query: str, model: str, rank: int) -> Dict[str, str]:
        spec = self._model_spec(model)
        anti_ext = json.dumps(spec["anti_ext"], separators=(",", ":"))
        model_name = spec["usedModel"]["modelName"]
        x_chat_msg = (
            f"query:{urllib.parse.quote(query)},"
            f"anti_ext:{urllib.parse.quote(anti_ext)},"
            f"enter_type:{spec['enter_type']},re_rank:{rank},modelName:{model_name},sa:bkb"
        )
        # Live client sets isDeepseek="1" for any selected modelName
        is_deepseek = "1" if model_name else "0"
        return {
            **self._headers, "Content-Type": "application/json",
            "X-Chat-Message": x_chat_msg, "isDeepseek": is_deepseek,
            "landingPageSwitch": "", "personifiedSwitch": "0", "source": "pc_csaitab",
        }

    # ------------------------------------------------------------------
    # SSE parser with stall-guard (heartbeats every 8s so caller can abort)
    # ------------------------------------------------------------------
    def _parse_sse(self, resp) -> Generator[Dict[str, Any], None, None]:
        buffer = ""
        last_data_time = time.time()
        STALL_SECONDS = 8.0
        event_count = 0
        for chunk in resp.iter_content(chunk_size=1024, decode_unicode=True):
            if not chunk:
                # No data in this chunk — check stall
                if time.time() - last_data_time > STALL_SECONDS:
                    _log("WARN", f"SSE stall detected ({STALL_SECONDS}s without data) — aborting parse")
                    return
                continue
            last_data_time = time.time()
            buffer += chunk.replace("\r\n", "\n")
            while "\n\n" in buffer:
                event_text, buffer = buffer.split("\n\n", 1)
                event_lines = event_text.strip().split("\n")
                event_type = ""
                event_data = ""
                for line in event_lines:
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        event_data = line[5:].strip()
                if event_data:
                    event_count += 1
                    try:
                        data = json.loads(event_data)
                    except json.JSONDecodeError:
                        data = {"raw": event_data}
                    # Log first 3 events and any event with message data
                    if event_count <= 3 or event_type == "message":
                        _log("DEBUG", f"SSE event #{event_count} type={event_type} data_keys={list(data.keys())}")
                    yield {"event": event_type, "data": data}
        _log("DEBUG", f"SSE parser exited after {event_count} events")

    def chat(self, query: str, model: str = "deepseek-v4-flash", deep_search: bool = False,
             internet_search: bool = False, rank: Optional[int] = None) -> Generator[Dict[str, Any], None, None]:
        self._ensure_cookies()
        if not self._token or not self._lid:
            self._get_base_data()

        payload = self._build_message_payload(query, model, deep_search, internet_search, rank)
        effective_rank = payload["rank"]
        headers = self._build_headers(query, model, effective_rank)

        _log("DEBUG", f"Request payload: chat_token={payload['message']['searchInfo']['chatParams']['chat_token'][:50]}... rank={effective_rank} model={model}")
        _log("DEBUG", f"Request cookies: {self._cookie_string()[:120]}...")
        _log("BAIDU", f"POST {self.CONVERSATION_API}  model={model}  deep={deep_search}")
        try:
            resp = self.session.post(
                self.CONVERSATION_API, headers=headers, json=payload,
                stream=True, timeout=(5, 30),  # connect 5s, read 30s
            )
        except requests.exceptions.Timeout:
            raise RuntimeError("Baidu conversation API timed out (30s) — check network / cookies / Baidu status")
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"Connection error to Baidu conversation API: {e}")

        # Cookie/auth retry
        if self._should_refresh_response(resp):
            _log("WARN", f"HTTP {resp.status_code} indicates unusable cookies — refreshing and retrying once")
            resp.close()
            self._refresh_cookies()
            payload = self._build_message_payload(query, model, deep_search, internet_search, rank)
            effective_rank = payload["rank"]
            headers = self._build_headers(query, model, effective_rank)
            try:
                resp = self.session.post(
                    self.CONVERSATION_API, headers=headers, json=payload,
                    stream=True, timeout=(5, 30),
                )
            except requests.exceptions.Timeout:
                raise RuntimeError("Retry after 401/403 also timed out")

        if not resp.ok:
            body = resp.text[:500]
            raise RuntimeError(f"Baidu API returned {resp.status_code}: {body}")

        _log("BAIDU", f"SSE connected  status={resp.status_code}  content-type={resp.headers.get('content-type', 'unknown')}")
        yield from self._parse_sse(resp)
        _log("BAIDU", "SSE stream ended normally")

    def chat_stream_text(self, query: str, model: str = "deepseek-v4-flash", deep_search: bool = False,
                           internet_search: bool = False) -> Generator[Dict[str, str], None, None]:
        msg_count = 0
        self._last_hint = None
        for ev in self.chat(query, model, deep_search, internet_search):
            if ev["event"] == "message":
                msg_count += 1
                msg_data = ev["data"]
                data = msg_data.get("data", {})

                # Baidu has two data structures:
                # New: data.message.content.generator.text
                # Old: data.content.generator.text
                message = data.get("message", {})
                if message:
                    content = message.get("content", {})
                    meta = message.get("metaData", {})
                    state = meta.get("state", "")
                else:
                    content = data.get("content", {})
                    state = content.get("state", "")
                    meta = {}

                _log("DEBUG", f"msg#{msg_count} state={state} content_keys={list(content.keys())}")

                # Extract hints/errors
                hints = content.get("hints", {})
                if hints:
                    parts = hints.get("parts", [])
                    for part in parts:
                        hint_text = part.get("text", "")
                        if hint_text:
                            self._last_hint = hint_text
                            _log("WARN", f"Baidu hint: {hint_text}")

                # Extract thinking/reasoning
                thinking = content.get("thinking") or content.get("thinking_content") or content.get("reasoning")
                if thinking:
                    yield {"type": "thinking", "content": thinking}

                # Extract text from generator based on component type
                text = ""
                generator = content.get("generator")
                if isinstance(generator, dict):
                    comp = generator.get("component", "")
                    gen_data = generator.get("data", {})
                    if comp == "markdown-yiyan" and isinstance(gen_data, dict):
                        text = gen_data.get("value", "")
                    elif comp == "thinkingSteps" and isinstance(gen_data, dict):
                        reasoning_arr = gen_data.get("reasoningContentArr", [])
                        if reasoning_arr and isinstance(reasoning_arr, list):
                            text = "".join(str(x) for x in reasoning_arr if x)
                        if text:
                            _log("DEBUG", f"msg#{msg_count} thinking_text={text[:80]}")
                            yield {"type": "thinking", "content": text}
                            text = ""
                    elif comp == "searchResult" and isinstance(gen_data, dict):
                        # Search query info, not text content
                        pass
                    elif comp == "questionClosely":
                        # Recommended follow-up questions, ignore
                        pass
                    if not text:
                        text = generator.get("text") or generator.get("content") or ""
                elif isinstance(generator, str):
                    text = generator
                if not text:
                    text = content.get("text") or content.get("answer") or ""

                if text:
                    _log("DEBUG", f"msg#{msg_count} text_len={len(text)} text_preview={text[:60]}")
                    yield {"type": "text", "content": text}

                if "searchQuery" in content:
                    sq = content["searchQuery"]
                    if isinstance(sq, dict):
                        query_text = sq.get("query", "")
                        if query_text:
                            yield {"type": "search_query", "content": query_text}

                if state in ("completed", "success", "done", "generate-complete") or meta.get("endTurn"):
                    yield {"type": "done", "content": ""}

            elif ev["event"] == "basedata":
                _log("DEBUG", f"basedata: session_id={ev['data'].get('qid', 'n/a')} user={ev['data'].get('user', {}).get('uname', 'n/a')}")
                yield {"type": "metadata", "content": ev["data"]}
            elif ev["event"] == "ping":
                yield {"type": "ping", "content": ""}
        _log("DEBUG", f"chat_stream_text finished, total msg events={msg_count}")

    def chat_to_openai_stream(self, query: str, model: str = "deepseek-v4-flash", deep_search: bool = False,
                               internet_search: bool = False) -> Generator[str, None, None]:
        chunk_count = 0
        for chunk in self.chat_to_openai_chunks(query, model, deep_search, internet_search):
            if chunk["type"] == "content":
                chunk_count += 1
                yield chunk["content"]
        _log("DEBUG", f"chat_to_openai_stream finished, text chunks={chunk_count}")

    def chat_to_openai_chunks(self, query: str, model: str = "deepseek-v4-flash", deep_search: bool = False,
                              internet_search: bool = False) -> Generator[Dict[str, str], None, None]:
        for chunk in self.chat_stream_text(query, model, deep_search, internet_search):
            ct = chunk["type"]
            if ct == "text":
                yield {"type": "content", "content": chunk["content"]}
            elif ct == "thinking":
                yield {"type": "reasoning_content", "content": chunk["content"]}
            elif ct == "done":
                break

    def chat_to_openai_sync(self, query: str, model: str = "deepseek-v4-flash", deep_search: bool = False,
                             internet_search: bool = False) -> Dict[str, Any]:
        text_parts = []
        thinking_parts = []
        for chunk in self.chat_stream_text(query, model, deep_search, internet_search):
            ct = chunk["type"]
            if ct == "text":
                text_parts.append(chunk["content"])
            elif ct == "thinking":
                thinking_parts.append(chunk["content"])

        content = "".join(text_parts)
        reasoning_content = "".join(thinking_parts) if thinking_parts else None
        _log("DEBUG", f"chat_to_openai_sync: text_parts={len(text_parts)} total_len={len(content)}")
        if not content and self._last_hint:
            raise RuntimeError(f"Baidu returned no answer: {self._last_hint}")
        return {
            "role": "assistant", "content": content,
            "reasoning_content": reasoning_content,
        }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Baidu Chat CLI")
    parser.add_argument("query", help="Chat query")
    parser.add_argument(
        "--model",
        default="deepseek-v4-flash",
        choices=[
            "deepseek-r1",
            "deepseek-v4-pro", "deepseek-v4-pro-nothinking",
            "deepseek-v4-flash", "deepseek-v4-flash-nothinking",
            "ernie-5.1", "ernie-5.1-nothinking",
            "smartmode", "smartmode-thinking",
            "smart", "deepseek", "ds-v4", "ds-v4-flash",
        ],
    )
    parser.add_argument("--deep-search", action="store_true")
    parser.add_argument("--internet-search", action="store_true")
    parser.add_argument("--cookies", default="", help="Cookie string (optional)")
    parser.add_argument("--cookie-file", default="", help="Path to save/load cookies")
    args = parser.parse_args()

    client = BaiduChatClient(
        cookies=args.cookies or None,
        cookie_file=args.cookie_file or None,
        auto_save_cookies=bool(args.cookie_file),
    )
    _log("INFO", f"Query: {args.query}  model={args.model}")
    for chunk in client.chat_to_openai_stream(
        args.query, model=args.model, deep_search=args.deep_search, internet_search=args.internet_search
    ):
        print(chunk, end="", flush=True)
    print()

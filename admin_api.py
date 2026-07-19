"""Admin API + static WebUI for baidu2api."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from functools import wraps
from typing import Any, Callable, Dict, Optional, Tuple

from flask import Flask, jsonify, request, send_from_directory
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from baidu_chat import _log


class AdminState:
    """Mutable runtime config shared with the Flask app."""

    def __init__(self):
        self.lock = threading.RLock()
        self.config_path = "config.toml"
        self.admin_key = "baidu2api"
        self.jwt_expire_hours = 24
        self.api_keys: list[str] = []
        self.cookie_values: list[str] = []
        self.user_agent: Optional[str] = None
        self.cookie_file = "cookies.json"
        self.auto_save_cookies = True
        self.fresh_conversation = True
        self.context_max_chars = 12000
        self.context_max_messages = 16
        self.context_max_message_chars = 2000
        self.model_aliases: Dict[str, str] = {}
        self.version = "0.2.0"
        self._serializer: Optional[URLSafeTimedSerializer] = None
        self._secret = secrets.token_hex(32)
        self._on_config_changed: Optional[Callable[[], None]] = None
        self._cookie_fetcher: Optional[Callable[..., Dict[str, Any]]] = None
        self.runtime_cookie_status: Dict[str, Any] = {
            "source": "none",
            "cookie_count": 0,
            "cookie_names": [],
            "has_token": False,
            "has_lid": False,
            "cookie_preview": "",
            "pool_size": 0,
        }

    def set_cookie_fetcher(self, fetcher: Optional[Callable[..., Dict[str, Any]]]):
        with self.lock:
            self._cookie_fetcher = fetcher

    def set_runtime_cookie_status(self, status: Optional[Dict[str, Any]]):
        with self.lock:
            self.runtime_cookie_status = dict(status or {})

    def fetch_cookies_now(self, force: bool = True) -> Dict[str, Any]:
        fetcher = self._cookie_fetcher
        if not fetcher:
            raise RuntimeError("Cookie auto-fetch is not available yet")
        status = fetcher(force)
        self.set_runtime_cookie_status(status)
        return status

    def configure(
        self,
        *,
        config_path: str,
        admin_key: str,
        jwt_expire_hours: int,
        api_keys: list[str],
        cookie_values: list[str],
        user_agent: Optional[str],
        cookie_file: str,
        auto_save_cookies: bool,
        fresh_conversation: bool,
        context_max_chars: int,
        context_max_messages: int,
        context_max_message_chars: int,
        model_aliases: Optional[Dict[str, str]] = None,
        version: str = "0.2.0",
        on_config_changed: Optional[Callable[[], None]] = None,
    ):
        with self.lock:
            self.config_path = config_path
            self.admin_key = admin_key or "baidu2api"
            self.jwt_expire_hours = max(1, int(jwt_expire_hours or 24))
            self.api_keys = list(api_keys or [])
            self.cookie_values = list(cookie_values or [])
            self.user_agent = user_agent
            self.cookie_file = cookie_file or "cookies.json"
            self.auto_save_cookies = bool(auto_save_cookies)
            self.fresh_conversation = bool(fresh_conversation)
            self.context_max_chars = int(context_max_chars)
            self.context_max_messages = int(context_max_messages)
            self.context_max_message_chars = int(context_max_message_chars)
            self.model_aliases = dict(model_aliases or {})
            self.version = version
            self._secret = secrets.token_hex(32)
            self._serializer = URLSafeTimedSerializer(self._secret, salt="baidu2api-admin")
            self._on_config_changed = on_config_changed
            # keep existing cookie fetcher across reconfigure


    def create_token(self) -> Tuple[str, int]:
        assert self._serializer is not None
        expires_in = self.jwt_expire_hours * 3600
        token = self._serializer.dumps({"role": "admin", "iat": int(time.time())})
        return token, expires_in

    def verify_token(self, token: str) -> bool:
        if not token or not self._serializer:
            return False
        try:
            self._serializer.loads(token, max_age=self.jwt_expire_hours * 3600)
            return True
        except (BadSignature, SignatureExpired):
            return False

    def snapshot_config(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "keys": list(self.api_keys),
                "api_keys": [{"key": k, "name": "", "remark": ""} for k in self.api_keys],
                "cookies": list(self.cookie_values),
                "accounts": [],
                "env_backed": False,
                "context": {
                    "fresh_conversation": self.fresh_conversation,
                    "max_chars": self.context_max_chars,
                    "max_messages": self.context_max_messages,
                    "max_message_chars": self.context_max_message_chars,
                },
                "cookie_persistence": {
                    "cookie_file": self.cookie_file,
                    "auto_save_cookies": self.auto_save_cookies,
                },
                "headers": {"user_agent": self.user_agent or ""},
                "model_aliases": dict(self.model_aliases),
                "runtime_cookies": dict(self.runtime_cookie_status),
                "auto_cookie_mode": not bool(self.cookie_values),
            }

    def snapshot_settings(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "admin": {
                    "jwt_expire_hours": self.jwt_expire_hours,
                    "default_password_warning": self.admin_key in ("baidu2api", "change-me", "ds2api", ""),
                },
                "runtime": {
                    "account_max_inflight": 1,
                    "account_max_queue": 1,
                    "global_max_inflight": max(1, len(self.cookie_values) or 1),
                    "token_refresh_interval_hours": 24,
                },
                "responses": {"store_ttl_seconds": 900},
                "embeddings": {"provider": ""},
                "auto_delete": {"mode": "single" if self.fresh_conversation else "none"},
                "current_input_file": {"enabled": False, "min_chars": 0},
                "thinking_injection": {"enabled": False, "prompt": "", "default_prompt": ""},
                "context": {
                    "fresh_conversation": self.fresh_conversation,
                    "max_chars": self.context_max_chars,
                    "max_messages": self.context_max_messages,
                    "max_message_chars": self.context_max_message_chars,
                },
                "cookies": {
                    "values": list(self.cookie_values),
                    "cookie_file": self.cookie_file,
                    "auto_save_cookies": self.auto_save_cookies,
                },
                "runtime_cookies": dict(self.runtime_cookie_status),
                "auto_cookie_mode": not bool(self.cookie_values),
                "model_aliases": dict(self.model_aliases),
                "env_backed": False,
                "needs_vercel_sync": False,
            }

    def apply_settings(self, payload: Dict[str, Any]):
        with self.lock:
            admin = payload.get("admin") or {}
            if "jwt_expire_hours" in admin:
                self.jwt_expire_hours = max(1, int(admin.get("jwt_expire_hours") or 24))

            context = payload.get("context") or {}
            if context:
                if "fresh_conversation" in context:
                    self.fresh_conversation = bool(context.get("fresh_conversation"))
                if "max_chars" in context:
                    self.context_max_chars = int(context.get("max_chars") or 12000)
                if "max_messages" in context:
                    self.context_max_messages = int(context.get("max_messages") or 16)
                if "max_message_chars" in context:
                    self.context_max_message_chars = int(context.get("max_message_chars") or 2000)

            cookies = payload.get("cookies") or {}
            if "values" in cookies and isinstance(cookies["values"], list):
                self.cookie_values = [str(v).strip() for v in cookies["values"] if str(v).strip()]
            if "cookie_file" in cookies:
                self.cookie_file = str(cookies.get("cookie_file") or "cookies.json")
            if "auto_save_cookies" in cookies:
                self.auto_save_cookies = bool(cookies.get("auto_save_cookies"))

            if "model_aliases" in payload and isinstance(payload["model_aliases"], dict):
                self.model_aliases = {
                    str(k): str(v) for k, v in payload["model_aliases"].items() if str(k).strip() and str(v).strip()
                }

            if "keys" in payload and isinstance(payload["keys"], list):
                self.api_keys = [str(k).strip() for k in payload["keys"] if str(k).strip()]

            # Session isolation UI maps to fresh_conversation
            auto_delete = payload.get("auto_delete") or {}
            mode = str(auto_delete.get("mode") or "").lower()
            if mode == "none":
                self.fresh_conversation = False
            elif mode in ("single", "all"):
                self.fresh_conversation = True

            self._persist_config_file()
            cb = self._on_config_changed
        if cb:
            cb()

    def set_password(self, new_password: str):
        with self.lock:
            self.admin_key = new_password
            self._secret = secrets.token_hex(32)
            self._serializer = URLSafeTimedSerializer(self._secret, salt="baidu2api-admin")
            self._persist_config_file()

    def add_key(self, key: str):
        with self.lock:
            key = key.strip()
            if key and key not in self.api_keys:
                self.api_keys.append(key)
                self._persist_config_file()
                cb = self._on_config_changed
            else:
                cb = None
        if cb:
            cb()

    def delete_key(self, key: str):
        with self.lock:
            self.api_keys = [k for k in self.api_keys if k != key]
            self._persist_config_file()
            cb = self._on_config_changed
        if cb:
            cb()

    def export_config(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "version": self.version,
                "admin_key": self.admin_key,
                "jwt_expire_hours": self.jwt_expire_hours,
                "api_keys": list(self.api_keys),
                "cookies": list(self.cookie_values),
                "context": {
                    "fresh_conversation": self.fresh_conversation,
                    "max_chars": self.context_max_chars,
                    "max_messages": self.context_max_messages,
                    "max_message_chars": self.context_max_message_chars,
                },
                "cookie_persistence": {
                    "cookie_file": self.cookie_file,
                    "auto_save_cookies": self.auto_save_cookies,
                },
                "headers": {"user_agent": self.user_agent or ""},
                "model_aliases": dict(self.model_aliases),
            }

    def import_config(self, config: Dict[str, Any], mode: str = "merge"):
        with self.lock:
            if mode == "replace":
                self.api_keys = []
                self.cookie_values = []
                self.model_aliases = {}

            if "api_keys" in config and isinstance(config["api_keys"], list):
                keys = []
                for item in config["api_keys"]:
                    if isinstance(item, dict):
                        k = str(item.get("key") or "").strip()
                    else:
                        k = str(item).strip()
                    if k:
                        keys.append(k)
                if mode == "merge":
                    for k in keys:
                        if k not in self.api_keys:
                            self.api_keys.append(k)
                else:
                    self.api_keys = keys
            elif "keys" in config and isinstance(config["keys"], list):
                keys = [str(k).strip() for k in config["keys"] if str(k).strip()]
                if mode == "merge":
                    for k in keys:
                        if k not in self.api_keys:
                            self.api_keys.append(k)
                else:
                    self.api_keys = keys

            if "cookies" in config:
                cookies = config["cookies"]
                if isinstance(cookies, list):
                    values = [str(v).strip() for v in cookies if str(v).strip()]
                elif isinstance(cookies, dict):
                    values = [str(v).strip() for v in (cookies.get("values") or []) if str(v).strip()]
                    if cookies.get("value"):
                        values.append(str(cookies["value"]).strip())
                else:
                    values = []
                if mode == "merge":
                    for v in values:
                        if v not in self.cookie_values:
                            self.cookie_values.append(v)
                else:
                    self.cookie_values = values

            if "context" in config and isinstance(config["context"], dict):
                ctx = config["context"]
                if "fresh_conversation" in ctx:
                    self.fresh_conversation = bool(ctx["fresh_conversation"])
                if "max_chars" in ctx:
                    self.context_max_chars = int(ctx["max_chars"])
                if "max_messages" in ctx:
                    self.context_max_messages = int(ctx["max_messages"])
                if "max_message_chars" in ctx:
                    self.context_max_message_chars = int(ctx["max_message_chars"])

            if "model_aliases" in config and isinstance(config["model_aliases"], dict):
                aliases = {str(k): str(v) for k, v in config["model_aliases"].items()}
                if mode == "merge":
                    self.model_aliases.update(aliases)
                else:
                    self.model_aliases = aliases

            if "admin_key" in config and str(config["admin_key"]).strip():
                self.admin_key = str(config["admin_key"]).strip()
                self._secret = secrets.token_hex(32)
                self._serializer = URLSafeTimedSerializer(self._secret, salt="baidu2api-admin")

            self._persist_config_file()
            cb = self._on_config_changed
        if cb:
            cb()

    def _persist_config_file(self):
        """Best-effort rewrite of config.toml with current runtime values."""
        path = self.config_path
        try:
            lines = [
                "# Baidu2API Configuration (auto-managed by admin WebUI)",
                "",
                "[cookies]",
            ]
            if self.cookie_values:
                lines.append("values = [")
                for v in self.cookie_values:
                    escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                    lines.append(f'  "{escaped}",')
                lines.append("]")
            else:
                lines.append('value = ""')

            lines.extend([
                "",
                "[server]",
                'host = "0.0.0.0"',
                "port = 8000",
                "",
                "[auth]",
            ])
            if self.api_keys:
                lines.append("api_keys = [")
                for k in self.api_keys:
                    escaped = k.replace("\\", "\\\\").replace('"', '\\"')
                    lines.append(f'  "{escaped}",')
                lines.append("]")
            else:
                lines.append("api_keys = []")

            admin_escaped = self.admin_key.replace("\\", "\\\\").replace('"', '\\"')
            lines.extend([
                f'admin_key = "{admin_escaped}"',
                f"jwt_expire_hours = {self.jwt_expire_hours}",
                "",
                "[headers]",
            ])
            ua = (self.user_agent or "").replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'user_agent = "{ua}"')
            lines.extend([
                "",
                "[cookie_persistence]",
                f'cookie_file = "{self.cookie_file}"',
                f"auto_save_cookies = {'true' if self.auto_save_cookies else 'false'}",
                "",
                "[context]",
                f"fresh_conversation = {'true' if self.fresh_conversation else 'false'}",
                f"max_chars = {self.context_max_chars}",
                f"max_messages = {self.context_max_messages}",
                f"max_message_chars = {self.context_max_message_chars}",
                "",
                "[options]",
                'default_model = "deepseek-v4-flash"',
                "stream = true",
                "",
            ])
            if self.model_aliases:
                lines.append("[models]")
                for k, v in self.model_aliases.items():
                    kk = k.replace("\\", "\\\\").replace('"', '\\"')
                    vv = v.replace("\\", "\\\\").replace('"', '\\"')
                    lines.append(f'{kk} = "{vv}"')
                lines.append("")

            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            _log("INFO", f"Admin config persisted → {path}")
        except Exception as exc:
            _log("WARN", f"Failed to persist admin config: {exc}")


admin_state = AdminState()


def _extract_bearer() -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


def require_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        token = _extract_bearer()
        if not admin_state.verify_token(token):
            return jsonify({"error": {"message": "Unauthorized", "type": "unauthorized"}, "detail": "Unauthorized"}), 401
        return fn(*args, **kwargs)

    return wrapper


def register_admin_routes(app: Flask):
    import mimetypes

    # Windows/Python may map .js to text/plain; browsers reject ES modules with wrong MIME.
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("application/javascript", ".mjs")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("image/svg+xml", ".svg")
    mimetypes.add_type("application/wasm", ".wasm")

    static_admin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "admin")

    @app.route("/admin/login", methods=["POST"])
    def admin_login():
        body = request.get_json(force=True, silent=True) or {}
        key = str(body.get("admin_key") or body.get("password") or "").strip()
        if not key or key != admin_state.admin_key:
            return jsonify({"success": False, "detail": "管理员密钥错误"}), 401
        token, expires_in = admin_state.create_token()
        payload = {"success": True, "token": token, "expires_in": expires_in}
        if admin_state.admin_key in ("baidu2api", "change-me", "ds2api"):
            payload["message"] = "当前使用默认管理员密钥，请尽快在设置中修改"
        return jsonify(payload)

    @app.route("/admin/verify", methods=["GET"])
    def admin_verify():
        token = _extract_bearer()
        if admin_state.verify_token(token):
            return jsonify({"success": True, "ok": True})
        return jsonify({"success": False, "detail": "invalid token"}), 401

    @app.route("/admin/config", methods=["GET"])
    @require_admin
    def admin_config():
        return jsonify(admin_state.snapshot_config())

    @app.route("/admin/config", methods=["PUT", "POST"])
    @require_admin
    def admin_config_update():
        body = request.get_json(force=True, silent=True) or {}
        admin_state.apply_settings(body)
        return jsonify({"success": True, **admin_state.snapshot_config()})

    @app.route("/admin/config/export", methods=["GET"])
    @require_admin
    def admin_config_export():
        data = admin_state.export_config()
        raw = json.dumps(data, ensure_ascii=False)
        import base64
        return jsonify({"success": True, "config": data, "raw": raw, "base64": base64.b64encode(raw.encode()).decode()})

    @app.route("/admin/config/import", methods=["POST"])
    @require_admin
    def admin_config_import():
        body = request.get_json(force=True, silent=True) or {}
        mode = str(request.args.get("mode") or body.get("mode") or "merge")
        config = body.get("config") or body
        if not isinstance(config, dict):
            return jsonify({"detail": "invalid config"}), 400
        admin_state.import_config(config, mode=mode)
        return jsonify({"success": True, **admin_state.snapshot_config()})

    @app.route("/admin/export", methods=["GET"])
    @require_admin
    def admin_export_alias():
        return admin_config_export()

    @app.route("/admin/import", methods=["POST"])
    @require_admin
    def admin_import_alias():
        return admin_config_import()

    @app.route("/admin/settings", methods=["GET"])
    @require_admin
    def admin_settings_get():
        return jsonify(admin_state.snapshot_settings())

    @app.route("/admin/settings", methods=["PUT"])
    @require_admin
    def admin_settings_put():
        body = request.get_json(force=True, silent=True) or {}
        admin_state.apply_settings(body)
        return jsonify({"success": True, **admin_state.snapshot_settings()})

    @app.route("/admin/settings/password", methods=["POST"])
    @require_admin
    def admin_password():
        body = request.get_json(force=True, silent=True) or {}
        new_password = str(body.get("new_password") or "").strip()
        if len(new_password) < 4:
            return jsonify({"detail": "密码至少 4 位"}), 400
        admin_state.set_password(new_password)
        return jsonify({"success": True})

    @app.route("/admin/keys", methods=["POST"])
    @require_admin
    def admin_keys_add():
        body = request.get_json(force=True, silent=True) or {}
        key = str(body.get("key") or body.get("api_key") or "").strip()
        if not key:
            key = "sk-" + secrets.token_hex(16)
        admin_state.add_key(key)
        return jsonify({"success": True, "key": key})

    @app.route("/admin/keys/<path:key>", methods=["DELETE"])
    @require_admin
    def admin_keys_delete(key: str):
        admin_state.delete_key(key)
        return jsonify({"success": True})

    @app.route("/admin/keys/<path:key>", methods=["PUT"])
    @require_admin
    def admin_keys_update(key: str):
        # Metadata only — keep key string stable.
        return jsonify({"success": True, "key": key})

    @app.route("/admin/cookies/status", methods=["GET"])
    @require_admin
    def admin_cookies_status():
        return jsonify({"success": True, "runtime_cookies": admin_state.runtime_cookie_status, "auto_cookie_mode": not bool(admin_state.cookie_values)})

    @app.route("/admin/cookies/auto-fetch", methods=["POST"])
    @require_admin
    def admin_cookies_auto_fetch():
        body = request.get_json(force=True, silent=True) or {}
        force = bool(body.get("force", True))
        try:
            status = admin_state.fetch_cookies_now(force=force)
            return jsonify({"success": True, "runtime_cookies": status, "auto_cookie_mode": not bool(admin_state.cookie_values)})
        except Exception as e:
            return jsonify({"success": False, "detail": str(e)}), 500

    @app.route("/admin/version", methods=["GET"])
    @require_admin
    def admin_version():
        return jsonify({
            "current_tag": f"v{admin_state.version}",
            "latest_tag": f"v{admin_state.version}",
            "has_update": False,
            "release_url": "https://github.com/dijiaozhibei-top/baidu2api/releases/latest",
        })

    @app.route("/healthz", methods=["GET"])
    def healthz():
        return jsonify({"status": "ok"})

    @app.route("/admin", methods=["GET"])
    @app.route("/admin/", methods=["GET"])
    def admin_index():
        index = os.path.join(static_admin, "index.html")
        if os.path.exists(index):
            return send_from_directory(static_admin, "index.html")
        return jsonify({"detail": "WebUI not built. Run: cd webui && npm install && npm run build"}), 404

    @app.route("/admin/<path:asset>", methods=["GET"])
    def admin_assets(asset: str):
        from flask import Response

        root = os.path.abspath(static_admin)
        file_path = os.path.abspath(os.path.join(static_admin, asset))
        if not (file_path == root or file_path.startswith(root + os.sep)):
            return jsonify({"detail": "not found"}), 404
        if os.path.isfile(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            mime_map = {
                ".js": "application/javascript; charset=utf-8",
                ".mjs": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
                ".json": "application/json",
                ".map": "application/json",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".ttf": "font/ttf",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".ico": "image/x-icon",
                ".html": "text/html; charset=utf-8",
            }
            mime = mime_map.get(ext)
            # Always stream JS ourselves so Content-Type cannot be rewritten to text/plain.
            if ext in (".js", ".mjs", ".css", ".svg", ".json", ".map", ".html"):
                with open(file_path, "rb") as f:
                    data = f.read()
                return Response(
                    data,
                    mimetype=mime or "application/octet-stream",
                    headers={"Cache-Control": "no-cache", "X-Baidu2-Static": "1"},
                )
            return send_from_directory(static_admin, asset)
        index = os.path.join(static_admin, "index.html")
        if os.path.exists(index):
            return send_from_directory(static_admin, "index.html")
        return jsonify({"detail": "not found"}), 404
        if os.path.isfile(file_path):
            # Force correct MIME types. On Windows, mimetypes often maps .js → text/plain,
            # and browsers refuse to execute ES modules served as text/plain.
            ext = os.path.splitext(file_path)[1].lower()
            mime = {
                ".js": "application/javascript; charset=utf-8",
                ".mjs": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
                ".json": "application/json",
                ".map": "application/json",
                ".woff": "font/woff",
                ".woff2": "font/woff2",
                ".ttf": "font/ttf",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".ico": "image/x-icon",
                ".html": "text/html; charset=utf-8",
            }.get(ext, None)
            resp = send_from_directory(static_admin, asset)
            if mime:
                resp.headers["Content-Type"] = mime
            resp.headers["X-Baidu2-Static"] = "1"
            # Werkzeug may re-sniff; force via direct Response for js
            if ext in (".js", ".mjs"):
                from flask import Response
                with open(file_path, "rb") as f:
                    data = f.read()
                return Response(data, mimetype="application/javascript; charset=utf-8", headers={"X-Baidu2-Static":"1","Cache-Control":"no-cache"})
            return resp
        # SPA fallback
        index = os.path.join(static_admin, "index.html")
        if os.path.exists(index):
            return send_from_directory(static_admin, "index.html")
        return jsonify({"detail": "not found"}), 404

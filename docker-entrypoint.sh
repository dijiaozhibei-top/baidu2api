#!/bin/sh
set -eu

DATA_DIR="${BAIDU2API_DATA_DIR:-/app/data}"
CONFIG_PATH="${BAIDU2API_CONFIG_PATH:-$DATA_DIR/config.toml}"
COOKIE_FILE="${BAIDU2API_COOKIE_FILE:-$DATA_DIR/cookies.json}"
DEFAULT_CONFIG="${BAIDU2API_DEFAULT_CONFIG:-/app/config.default.toml}"

mkdir -p "$DATA_DIR"

if [ ! -f "$CONFIG_PATH" ]; then
  if [ -f "$DEFAULT_CONFIG" ]; then
    # Rewrite cookie_file path to the runtime data location.
    sed "s#cookie_file = \".*\"#cookie_file = \"$COOKIE_FILE\"#" "$DEFAULT_CONFIG" > "$CONFIG_PATH"
  else
    cat > "$CONFIG_PATH" <<EOF
# Baidu2API Configuration (auto-created)

[cookies]
value = ""

[server]
host = "0.0.0.0"
port = 8000

[auth]
api_keys = []
admin_key = "baidu2api"
jwt_expire_hours = 24

[headers]
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

[cookie_persistence]
cookie_file = "$COOKIE_FILE"
auto_save_cookies = true

[context]
fresh_conversation = true
max_chars = 12000
max_messages = 16
max_message_chars = 2000

[options]
default_model = "deepseek-v4-flash"
stream = true
EOF
  fi
  echo "[entrypoint] created $CONFIG_PATH"
fi

if [ ! -f "$COOKIE_FILE" ]; then
  printf '{}\n' > "$COOKIE_FILE"
  echo "[entrypoint] created $COOKIE_FILE"
fi

# Allow BAIDU2API_ADMIN_KEY env to override config at runtime without editing file.
export BAIDU2API_ADMIN_KEY="${BAIDU2API_ADMIN_KEY:-}"

HOST="${BAIDU2API_HOST:-0.0.0.0}"
PORT="${PORT:-${BAIDU2API_PORT:-8000}}"

exec python main.py --host "$HOST" --port "$PORT" --config "$CONFIG_PATH"

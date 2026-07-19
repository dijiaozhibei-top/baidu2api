#!/usr/bin/env bash
# 服务器本地构建脚本：先用镜像站拉基础镜像，再 tag 成官方名，最后 compose build
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

NODE_IMAGE="${NODE_IMAGE:-docker.m.daocloud.io/library/node:22-alpine}"
PYTHON_IMAGE="${PYTHON_IMAGE:-docker.m.daocloud.io/library/python:3.13-slim}"

echo "[build-dev] pull base images"
echo "  NODE_IMAGE=$NODE_IMAGE"
echo "  PYTHON_IMAGE=$PYTHON_IMAGE"

docker pull "$NODE_IMAGE"
docker pull "$PYTHON_IMAGE"

# 统一 tag 成 Dockerfile 默认名，避免 ARG 解析差异
docker tag "$NODE_IMAGE" node:22-alpine
docker tag "$PYTHON_IMAGE" python:3.13-slim

export NODE_IMAGE=node:22-alpine
export PYTHON_IMAGE=python:3.13-slim

COMPOSE=(docker compose)
if ! docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
fi

echo "[build-dev] compose build"
"${COMPOSE[@]}" -f docker-compose-dev.yml build --no-cache

echo "[build-dev] compose up"
"${COMPOSE[@]}" -f docker-compose-dev.yml up -d

echo "[build-dev] done"
"${COMPOSE[@]}" -f docker-compose-dev.yml ps

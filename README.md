# Baidu2API

将百度文心助手（`chat.baidu.com` / `wenxin.baidu.com`）对话能力转换为 **OpenAI 兼容 API**，并提供浅色 React 管理台（`/admin`）。

语言 / Language: [中文](README.md) | [English](README.en.md)

> **免责声明**：仅供学习研究，请遵守百度服务条款与当地法律法规。作者不对账号封禁、数据损失或任何后果负责。

## 功能

- OpenAI 兼容：`GET /v1/models`、`POST /v1/chat/completions`（流式 / 非流式）
- 管理台 `/admin`：Cookie / API Key 配置、API 测试、设置（会话独立拆分、上下文、备份导入导出）
- 多 Cookie 池 + 故障切换
- 可选 API Key 鉴权；错误密钥返回 **401**
- Tool Calling（XML → OpenAI `tool_calls`）
- Docker 一键部署，镜像同时发布到 **GHCR** 与 **Docker Hub**

## 支持的模型

与 2026-07 线上 `usableModel` 对齐：

| API 模型 ID | 百度 `modelName` | 说明 |
| --- | --- | --- |
| `deepseek-r1` | `DeepSeek-R1` | 深度思考（强制） |
| `deepseek-v4-pro` | `DeepSeek-V4` | V4 Pro + 思考 |
| `deepseek-v4-pro-nothinking` | `DeepSeek-V4` | V4 Pro 关闭思考 |
| `deepseek-v4-flash` | `DeepSeek-V4-Flash` | Flash + 思考 |
| `deepseek-v4-flash-nothinking` | `DeepSeek-V4-Flash` | Flash 关闭思考 |
| `ernie-5.1` / `ERINE-5.1` | `ERINE-5.1` | 文心 5.1 + 思考 |
| `ernie-5.1-nothinking` / `ERINE-5.1-nothinking` | `ERINE-5.1` | 文心 5.1 关闭思考 |
| `smartmode` | `smartMode` | 智能模式 |
| `smartmode-thinking` | `smartMode` | 智能模式 + 深度搜索/思考 |

## 快速开始

### 1）Docker Compose（推荐）

```bash
cp .env.example .env
# 只需挂载 ./data；首次启动会自动创建：
#   ./data/config.toml
#   ./data/cookies.json
docker compose up -d
# 本地源码构建开发镜像：
# docker compose -f docker-compose-dev.yml up -d --build
```

- API: `http://localhost:8000/v1`
- 管理台: `http://localhost:8000/admin`（默认管理员密钥见 `.env` 的 `BAIDU2API_ADMIN_KEY`）
- 数据目录：`./data/`（配置与 Cookie 持久化）

### 2）本地运行

```bash
pip install -r requirements.txt
# 构建 WebUI（可选，管理台需要）
cd webui && npm ci && npm run build && cd ..
python main.py --config config.toml
```

### 3）拉取镜像

仓库：`dijiaozhibei-top/baidu2api`（GHCR） / `dijiaozhibei/baidu2api`（Docker Hub）

**原版镜像：**

```bash
docker pull ghcr.io/dijiaozhibei-top/baidu2api:latest
docker pull dijiaozhibei/baidu2api:latest
```

**不带前缀（Docker Hub）：**

```bash
docker pull dijiaozhibei/baidu2api:latest
```

**国内镜像加速（Docker Hub）：**

```bash
docker pull docker.1ms.run/dijiaozhibei/baidu2api:latest
docker pull gh-proxy.org/docker/dijiaozhibei/baidu2api:latest
```

**国内镜像加速（GHCR）：**

```bash
docker pull ghcr.nju.edu.cn/dijiaozhibei-top/baidu2api:latest
docker pull gh-proxy.org/docker/ghcr.io/dijiaozhibei-top/baidu2api:latest
```

运行示例：

```bash
mkdir -p data
docker run -d --name baidu2api -p 8000:8000 \
  -v $PWD/data:/app/data \
  -e BAIDU2API_ADMIN_KEY=change-me \
  dijiaozhibei/baidu2api:latest
# 首次启动自动创建 /app/data/config.toml 与 /app/data/cookies.json
```

## API 示例

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-secret-key" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

配置了 `api_keys` 时，错误或缺失的 Bearer 令牌会返回 **HTTP 401**。

## 配置说明

Docker 默认读写 `./data/config.toml` 与 `./data/cookies.json`（不存在时由入口脚本自动创建）。  
模板见 [`config.default.toml`](config.default.toml)，环境变量见 [`.env.example`](.env.example)。

| 项 | 说明 |
| --- | --- |
| `[cookies].value` / `values` | 百度 Cookie；多值启用池；可留空自动获取访客 Cookie |
| `[auth].api_keys` | OpenAI API 密钥列表；空=不鉴权 |
| `[auth].admin_key` | WebUI 管理员密钥（也可用环境变量 `BAIDU2API_ADMIN_KEY`） |
| `[context].fresh_conversation` | 每次请求新百度会话（默认 true，对应设置里的「会话独立拆分」） |
| `[cookie_persistence]` | Cookie 自动落盘路径（Docker 下为 `data/cookies.json`） |

## 开发

```bash
# 后端
python main.py --port 8000

# 前端开发（代理到 8000）
cd webui && npm run dev

# 测试（mock 集成）
python test_server.py
```

## License

仅供学习交流。使用本项目即表示你自行承担全部风险。

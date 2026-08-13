# Personal AI Assistant

企业级 Personal AI Assistant —— 基于 FastAPI + LangGraph 的 Agent 后端、Next.js 前端，以及完整的
**评估（Evaluation） / 可观测性（Observability） / 生产部署（Production Deployment）** 能力。

- **frontend**: Next.js 15 + TypeScript + Tailwind CSS
- **backend**: Python 3.12 + FastAPI + LangGraph + SQLAlchemy 2.0 (async) + Alembic
- **postgres**: PostgreSQL 16 + pgvector（RAG 向量检索）
- **nginx**: 反向代理（前端 + `/api` + SSE 流式聊天）

> 本仓库为 **Production 阶段**：补齐评估、可观测性与生产部署，不新增 Agent 业务功能。

---

## 项目架构

```
┌────────────┐     ┌────────────┐     ┌──────────────────┐
│  Browser   │────▶│   nginx    │────▶│  Next.js Frontend│  (/)
│            │     │  (proxy)   │     └──────────────────┘
│  (SSE)     │     │            │────▶│  FastAPI Backend │  (/api, /health, /ready)
└────────────┘     └────────────┘     └────────┬─────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │ PostgreSQL  │  (pgvector)
                                        │  + volumes  │
                                        └─────────────┘
```

Agent 执行链路（LangGraph）：

```
user_message ──▶ build_context (memory+conversation retrieval)
                  │
                  ▼
            LLM (tool-calling) ──▶ tool_call (create_task / query_calendar / save_memory / search_knowledge …)
                  │                      │
                  │                      ▼
                  │                 ToolGateway (risk gating → Human Approval)
                  ▼
            streamed response (SSE)
```

每一次运行都会通过 `app/observability/tracking.py` 写入 **agent_runs / trace_events / run_metrics**，
供 Admin Runs 页面与 `/api/v1/admin/runs` 查询。

---

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Next.js 15 (App Router), TypeScript, Tailwind CSS |
| 后端 | FastAPI, LangGraph, SQLAlchemy 2.0 async, Pydantic v2 |
| LLM | OpenAI 兼容接口（Volcano Ark / OpenAI 等） |
| 向量检索 | pgvector + 可选 Volcano Ark Embedding（无凭据时回退确定性向量） |
| 数据库 | PostgreSQL 16 + pgvector |
| 迁移 | Alembic |
| 可观测性 | structlog (JSON) + agent_runs / trace_events / run_metrics |
| 部署 | Docker + docker compose + nginx |
| 评估 | golden dataset + 指标评估器（`evaluation/`） |

---

## 目录结构（Production 关键部分）

```
.
├── docker-compose.yml            # nginx + frontend + backend + postgres(pgvector)
├── .env.example                  # 环境变量模板（禁止提交真实 Secret）
├── nginx/
│   ├── Dockerfile
│   └── nginx.conf                # 前端代理 + /api 代理 + SSE 关闭 buffering
├── docker/postgres/init.sql      # CREATE EXTENSION vector
├── backend/
│   ├── Dockerfile                # 多阶段生产构建
│   ├── docker-entrypoint.sh       # 等待 PG + alembic upgrade head
│   ├── alembic.ini / alembic/     # migrations（含 0008_observability）
│   ├── evaluation/
│   │   ├── runner.py             # 运行器：uv run python -m evaluation.runner
│   │   ├── evaluators.py         # 4 项指标评估器
│   │   ├── datasets/golden.json  # Golden Dataset
│   │   └── reports/              # 生成的 JSON 报告（git-ignored）
│   └── app/
│       ├── api/routes/
│       │   ├── health.py         # GET /health, /ready（检查 PG）
│       │   ├── runs.py           # GET /api/v1/admin/runs[/run_id]
│       │   └── chat.py           # SSE 流式聊天（接入 run 生命周期）
│       ├── observability/
│       │   ├── __init__.py       # 结构化 JSON 日志 + Secret 脱敏
│       │   └── tracking.py       # run / trace event / metric 写入
│       ├── models/observability.py # AgentRun / TraceEvent / RunMetric
│       ├── repositories/run_repository.py
│       ├── security/auth.py       # Admin JWT
│       └── main.py                # 优雅关闭（engine.dispose）
└── frontend/
    ├── Dockerfile                # 多阶段生产构建
    └── src/app/admin/runs/       # 运维观测页面（列表 + 详情）
```

---

## 本地启动

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # 填写 DATABASE_URL / OPENAI_API_KEY / JWT_SECRET

# 数据库迁移（生产标准方式，禁止依赖 create_all）
alembic upgrade head

# 启动（生产用，不用 --reload）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 前端

```bash
cd frontend
npm install
cp .env.example .env.local       # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
npm run dev                       # 开发；npm run build && npm run start 为生产
```

---

## Docker 启动（生产）

```bash
# 1. 准备环境变量（必填：POSTGRES_PASSWORD / JWT_SECRET / OPENAI_API_KEY）
cp .env.example .env
#   编辑 .env，填入真实值（.env 已被 .gitignore 忽略）

# 2. 构建并启动完整系统
docker compose up --build

# 3. 访问
#    前端:        http://localhost/        (nginx :80)
#    后端 API:    http://localhost/api/v1/...
#    健康检查:    http://localhost/health
#    就绪探针:    http://localhost/ready
#    Swagger:     http://localhost/api/docs
```

服务组成（`docker-compose.yml`）：

| 服务 | 镜像 | 说明 |
| --- | --- | --- |
| `nginx` | nginx:1.27-alpine | 反向代理，SSE 关闭 buffering |
| `frontend` | 本地构建 (Next.js) | 生产构建，监听 3000 |
| `backend` | 本地构建 (FastAPI) | 启动时等待 PG 并执行迁移 |
| `postgres` | pgvector/pgvector:0.7.4-pg16 | 启用 vector 扩展，数据持久化于 `postgres_data` 卷 |

PostgreSQL 数据通过命名卷 `postgres_data` 持久化；pgvector 扩展由 `docker/postgres/init.sql` 自动创建。

---

## 环境变量

`.env.example` 为模板，复制为 `.env` 后填写（**禁止提交真实 Secret**）。

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | 异步连接串 `postgresql+asyncpg://user:pass@postgres:5432/db` |
| `LLM_API_KEY` | LLM API Key（生产必填） |
| `LLM_BASE_URL` / `LLM_MODEL` | LLM 端点与模型 |
| `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | 可选 Embedding 配置 |
| `JWT_SECRET` | Admin API 的 JWT 签名密钥（生产必填，长随机串） |
| `APP_ENV` | `development` \| `production`（生产为 `production`） |
| `LOG_LEVEL` | 日志级别（默认 `INFO`） |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | 数据库凭据（Docker） |
| `NEXT_PUBLIC_API_BASE_URL` | 前端使用的后端地址 |

日志会输出 **JSON**，并自动脱敏 `password / token / api_key / secret / authorization` 等字段。

---

## 数据库迁移（Alembic）

生产环境 **禁止** 依赖 `Base.metadata.create_all()`（仅保留为开发便捷）。

```bash
cd backend

# 应用全部迁移
alembic upgrade head

# 生成新迁移（模型变更后）
alembic revision --autogenerate -m "describe change"

# 回滚一步
alembic downgrade -1
```

可观测性相关表由迁移 `0008_observability` 创建：`agent_runs`、`trace_events`、`run_metrics`。

---

## 评估（Evaluation）

Golden Dataset 覆盖：普通对话（不调用工具）、`create_task`、`list_tasks`、calendar 查询/创建、
memory 保存/检索、knowledge 检索。

指标：

* **Tool Selection Accuracy** —— 工具选择是否正确（含“无需工具”判断）
* **Tool Argument Correctness** —— 抽取参数是否正确
* **Task Success Rate** —— 实际执行工具是否成功（无 DB 时标记为「未评估」）
* **Knowledge Retrieval Accuracy** —— RAG 召回是否命中预期内容

运行：

```bash
cd backend

# 使用已配置 LLM 进行真实评估（需 LLM_API_KEY）
uv run python -m evaluation.runner

# 未配置 LLM 时自动回退到基于规则的基线选择器，仍会生成报告（backend=rule_based）
```

生成的 JSON 报告写入 `backend/evaluation/reports/`（时间戳文件 + `latest.json`），同时打印汇总到终端。

---

## 生产部署方式

1. 复制并填写 `.env`（尤其 `JWT_SECRET`、`POSTGRES_PASSWORD`、`LLM_API_KEY`）。
2. `docker compose up --build` 启动 4 个服务。
3. 后端入口脚本会：`pg_isready` 等待 PG → `alembic upgrade head` 应用迁移 → 启动 uvicorn。
4. 通过 `http://localhost/ready` 确认后端就绪后再接入流量（nginx 直接转发）。
5. Admin 观测：浏览器打开 `/admin/runs`，或调用：
   * `GET /api/v1/admin/token` 获取 Admin JWT
   * `GET /api/v1/admin/runs` 运行列表
   * `GET /api/v1/admin/runs/{run_id}` 单次运行详情（时间线 / 工具调用 / Token / 错误）

---

## 优雅关闭

* FastAPI 关闭时通过 `await engine.dispose()` 释放数据库连接池。
* SSE 流式聊天在客户端断开时捕获 `CancelledError`，将对应 Run 标记为 `cancelled`，
  避免产生悬挂（orphaned）的运行记录。

---

## 已知限制

* **评估的 LLM 选择器是离线代理**：真实 Agent 在 LangGraph 内部路由，评估器用独立的 LLM 路由调用
  衡量「工具选择质量」，二者不完全等同；评分反映的是路由提示词与模型的综合能力。
* **Task Success Rate / Knowledge Retrieval Accuracy** 仅在 **有可用数据库** 时真实可测；
  无 DB 环境下相关用例标记为「未评估」并从比率分母中剔除。
* RAG 召回准确率依赖知识库是否已导入文档（见 `POST /api/v1/knowledge/documents`）。
* Admin API 当前使用单一共享 JWT 密钥；多租户/细粒度权限需另行扩展。
* 日志脱敏基于关键字匹配，极度非标准的敏感字段名可能漏脱（建议配合外部日志平台脱敏）。

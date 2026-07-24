# CS Gap Assist

CS Gap Assist 是一个面向计算机科学论文的研究规划助手。它把论文上传、论文问答、研究路线规划、复现实验规划、引用图谱和个人知识库放在一个本地 MVP 应用里，帮助你从已有论文出发，整理可执行的研究方向。

稳定版本维护在 `main` 分支；功能开发请在独立分支完成，并通过 Pull Request 合并到 `main`。

## 主要功能

| 模块 | 用途 | 主要接口 |
| --- | --- | --- |
| 论文问答 | 上传论文后，基于选中文档回答问题并返回段落级来源 | `POST /api/v1/reading/qa` |
| 研究路线规划 | 用一个有步骤记录的 Agent 串联目标理解、知识检索、Gap 分析、实验建议、论文推荐和最终执行卡片 | `POST /api/v1/research-plan-agent/run` |
| 复现实验室 | 针对一篇已上传论文，提取复现目标、数据集、指标、基线、算法 notes、风险和安全模板 | `POST /api/v1/reproduction-agent/run` |
| 引用图谱 | 输入技术关键词，生成 D3 可用的引用演化图 | `GET /api/v1/citations/graph` |
| 知识库 | 管理论文、笔记、标签、收藏，并统一搜索论文、笔记、chunks、Gap 历史和实验历史 | `/api/v1/knowledge/*` |
| 兼容 API | 保留独立 Research Gap 和 Experiment Suggestion 能力，供前端或 Agent 复用 | `/api/v1/gaps/*`, `/api/v1/experiments/*` |

## 技术栈

- Backend: FastAPI, Pydantic, SQLite, optional Chroma mirror, pytest
- Frontend: React, Vite, TypeScript, D3
- Model layer: DeepSeek chat provider, OpenAI/local embedding options, deterministic mock fallback
- Literature sources: arXiv by default; OpenAlex is optional for citation graph expansion

Semantic Scholar 已废弃，不用于新的文献检索或引用图谱流程。

## 快速开始

### 1. 准备环境

需要：

- Python 3.11+
- Node.js 和 npm

克隆仓库后进入项目根目录：

```powershell
git clone https://github.com/terryzero000-create/cs-gap-assist.git
cd cs-gap-assist
```

复制环境变量文件：

```powershell
copy .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

没有真实 API key 也可以运行。缺少 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 时，系统会使用本地 mock provider 并返回 warning。

### 2. 安装依赖

后端：

```powershell
python -m pip install -e ".[dev,rag,xfyun]"
```

前端：

```powershell
npm install --prefix frontend
```

### 3. 启动开发服务

Windows:

```powershell
.\start-dev.ps1
```

macOS/Linux:

```bash
chmod +x start-dev.sh stop-dev.sh
./start-dev.sh
```

打开：

```text
http://localhost:5173
```

开发脚本默认启动：

- Backend: `http://127.0.0.1:8002`
- Frontend: `http://localhost:5173`
- Vite proxy: `/api` -> `http://127.0.0.1:8002`

停止服务：

```powershell
.\stop-dev.ps1
```

macOS/Linux:

```bash
./stop-dev.sh
```

## 常用命令

运行后端测试：

```powershell
python -m pytest backend/tests -q
```

运行前端类型检查：

```powershell
npm test --prefix frontend
```

构建前端：

```powershell
npm run build --prefix frontend
```

## API 速览

| Endpoint | 说明 |
| --- | --- |
| `GET /api/v1/health` | 健康检查 |
| `GET /api/v1/config/models` | 查看可用模型和 fallback 状态 |
| `POST /api/v1/papers/upload` | 上传 PDF，返回 `doc_id` 和 chunk 数量 |
| `GET /api/v1/papers` | 列出已上传论文 |
| `POST /api/v1/reading/qa` | 对选中论文提问 |
| `POST /api/v1/research-plan-agent/run` | 生成研究路线规划 |
| `POST /api/v1/reproduction-agent/run` | 生成复现实验辅助报告 |
| `GET /api/v1/citations/graph?keyword=...&max_nodes=...` | 生成引用图谱 |
| `POST /api/v1/gaps/analyze` | 独立 Research Gap 分析 |
| `GET /api/v1/gaps/history` | Gap 历史 |
| `POST /api/v1/experiments/suggest` | 独立实验建议 |
| `GET /api/v1/experiments/history` | 实验建议历史 |
| `GET /api/v1/knowledge/search` | 知识库搜索 |
| `GET /api/v1/vector-index/status` | 查看向量索引、缺失 chunks 和最近迁移状态 |

上传论文示例：

```powershell
curl.exe -F "file=@paper.pdf" http://127.0.0.1:8002/api/v1/papers/upload
```

引用图谱示例：

```powershell
Invoke-RestMethod "http://127.0.0.1:8002/api/v1/citations/graph?keyword=retrieval%20augmented%20generation&max_nodes=15"
```

## 环境变量

常用变量在 `.env.example` 中已经列出：

| 变量 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek chat model key |
| `OPENAI_API_KEY` | OpenAI embedding key |
| `SQLITE_URL` | 本地 SQLite 数据库路径，默认 `data/app.db` |
| `CHROMA_DIR` | Chroma 本地目录，默认 `data/chroma` |
| `DEFAULT_CHAT_PROVIDER` | 默认聊天模型 provider |
| `DEFAULT_CHAT_MODEL` | 默认聊天模型 |
| `DEFAULT_EMBEDDING_PROVIDER` | 默认 embedding provider |
| `LOCAL_BGE_M3_BASE_URL` | 本地 BGE-M3 embedding 服务地址 |
| `ENABLE_OPENALEX` | 是否启用 OpenAlex 引用扩展 |
| `OPENALEX_API_KEY` | OpenAlex API key |
| `EXTERNAL_SEARCH_TIMEOUT_SECONDS` | 外部检索超时时间 |
| `EXTERNAL_NETWORK_ENABLED` | 是否允许 arXiv 等外部网络检索；测试环境应设为 `false` |

`data/` 会被 Git 忽略，里面是本地运行状态，不要当作源码提交。

## 向量索引维护

向量索引以 SQLite chunks 为可重建的数据源。真实 embedding 服务失败时不会把 fallback 向量写入真实 collection；上传会返回 503，查询会降级为 SQLite 词法检索。

查看迁移计划（默认只读，不迁移）：

```powershell
python -m backend.scripts.migrate_vector_index
```

执行或继续无损迁移：

```powershell
python -m backend.scripts.migrate_vector_index --apply
```

只验证当前状态：

```powershell
python -m backend.scripts.migrate_vector_index --verify-only
```

迁移使用稳定的 collection 名、chunk ID 和内容哈希，可以重复执行。成功切换后仍保留 legacy collection，不会自动删除旧向量。

## 项目结构

```text
backend/
  api/                 FastAPI routers
  core/                settings and unified errors
  llm/                 model providers and chains
  models/              Pydantic schemas
  rag/                 embedding and vector store wrappers
  repositories/        SQLite store
  services/            feature services and agents
  tests/               pytest tests
frontend/
  src/                 React app, typed API client, components
  vite.config.ts       dev server and API proxy
docs/
  PROJECT_STATUS.md    project status and module map
  BRANCH_HANDOFF.md    branch handoff notes
  LOCAL_SETUP.md       local setup notes
```

## 当前限制

- 这是本地 MVP，不是生产部署。
- 多数外部模型和文献服务都有 deterministic fallback，方便无 key 开发。
- 真实 DeepSeek、OpenAI、OpenAlex 行为仍需要 API key 和集成测试。
- RAG ranking 仍偏简单，适合开发验证，不适合作为最终学术质量判断。
- Chroma 是可选依赖；不可用时查询会降级到 SQLite 词法检索。不要手工删除 legacy collection，应使用迁移命令检查和重建索引。
- 复现实验室只生成辅助报告和模板，不执行代码，不承诺复现论文指标。

## 更多文档

- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- [`docs/BRANCH_HANDOFF.md`](docs/BRANCH_HANDOFF.md)
- [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md)

# CS Gap Assist

CS Gap Assist 是一个面向计算机科学论文的研究规划助手。它把论文上传、论文问答、研究路线规划、复现实验规划、引用图谱和个人知识库放在一个本地 MVP 应用里，帮助你从已有论文出发，整理可执行的研究方向。

当前 hardening 分支：`codex/p0-p2-hardening`。

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
- Model layer: DeepSeek/optional OpenAI chat providers, XFYUN Spark embedding；测试模式可显式使用 synthetic provider
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

先在 `.env` 设置一个只供本机使用的 `APP_API_KEY`。前端首次打开时会要求输入该 token，并且只写入当前标签页的 `sessionStorage`。缺少真实模型凭据时，生产/开发环境不会伪造可信研究结论；`mock` 仅限 `APP_ENV=test` 或显式 `ALLOW_SYNTHETIC_MODE=true`。

### 2. 安装依赖

后端：

```powershell
python -m pip install -e ".[dev,rag,xfyun]"
```

可选 OCR 与 cross-encoder：

```powershell
python -m pip install -e ".[pdf-advanced,rerank]"
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

运行前端组件测试与类型检查：

```powershell
npm test --prefix frontend
npm run typecheck --prefix frontend
```

构建前端：

```powershell
npm run build --prefix frontend
```

## API 速览

| Endpoint | 说明 |
| --- | --- |
| `GET /health/live`（兼容 `/api/v1/health/live`） | 无鉴权进程存活检查 |
| `GET /health/ready`（兼容 `/api/v1/health/ready`） | 无鉴权依赖与 active index readiness |
| `GET /api/v1/config/models` | 查看可用模型和 fallback 状态 |
| `POST /api/v1/paper-uploads` | 需要 `Idempotency-Key`，异步接收 PDF，返回 202 |
| `GET /api/v1/paper-uploads/{upload_id}` | 查询上传阶段和结构化错误 |
| `POST /api/v1/paper-uploads/{upload_id}/retry` | 重试 retryable 失败 |
| `POST /api/v1/papers/upload` | 一个版本周期内保留的受限同步兼容接口 |
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
| `GET /api/v1/vector-index/status` | 查看 v4 索引、missing/orphan 和迁移状态 |
| `GET /api/v1/metrics` | 仅返回耗时/计数/P95 等聚合统计 |

异步上传示例：

```powershell
curl.exe -X POST `
  -H "Authorization: Bearer $env:APP_API_KEY" `
  -H "Idempotency-Key: paper-20260730-001" `
  -F "file=@paper.pdf;type=application/pdf" `
  http://127.0.0.1:8002/api/v1/paper-uploads
```

引用图谱示例：

```powershell
Invoke-RestMethod `
  -Headers @{ Authorization = "Bearer $env:APP_API_KEY" } `
  "http://127.0.0.1:8002/api/v1/citations/graph?keyword=retrieval%20augmented%20generation&max_nodes=15"
```

## 环境变量

常用变量在 `.env.example` 中已经列出：

| 变量 | 用途 |
| --- | --- |
| `APP_ENV` | `development`、`test` 或 `production`；test 完全忽略本地 `.env` |
| `APP_API_KEY` | 除 health 外所有 API 的 Bearer token |
| `ALLOW_SYNTHETIC_MODE` | 仅显式开发测试时开启，默认 false |
| `DEEPSEEK_API_KEY` | DeepSeek chat model key |
| `OPENAI_API_KEY` | 可选 OpenAI chat provider key；不用于 embedding |
| `SQLITE_URL` | 本地 SQLite 数据库路径，默认 `data/app.db` |
| `CHROMA_DIR` | Chroma 本地目录，默认 `data/chroma` |
| `DOCUMENT_DIR` | 按 doc/revision 保存原始 PDF 的目录 |
| `DEFAULT_CHAT_PROVIDER` | 默认聊天模型 provider |
| `DEFAULT_CHAT_MODEL` | 默认聊天模型 |
| `DEFAULT_EMBEDDING_PROVIDER` | 默认 embedding provider，正式配置为 `xfyun-spark` |
| `DEFAULT_EMBEDDING_MODEL` | 查询使用 `query`；论文入库时自动切换为 `para` |
| `XFYUN_SPARK_APP_ID` | 讯飞 Spark Embedding app ID |
| `XFYUN_SPARK_API_KEY` | 讯飞 Spark Embedding API key |
| `XFYUN_SPARK_API_SECRET` | 讯飞 Spark Embedding API secret |
| `XFYUN_SPARK_EMBEDDING_URL` | 讯飞 Spark Embedding 服务地址 |
| `LOCAL_BGE_M3_BASE_URL` | 本地 BGE-M3 embedding 服务地址 |
| `ENABLE_OPENALEX` | 是否启用 OpenAlex 引用扩展 |
| `OPENALEX_API_KEY` | OpenAlex API key |
| `EXTERNAL_SEARCH_TIMEOUT_SECONDS` | 外部检索超时时间 |
| `EXTERNAL_NETWORK_ENABLED` | 是否允许 arXiv 等外部网络检索；测试环境应设为 `false` |

`data/` 会被 Git 忽略，里面是本地运行状态，不要当作源码提交。

## 向量索引维护

向量索引以 active revision 的 SQLite chunks 为可重建数据源。真实 embedding 服务失败时不会写入 fallback vector；异步任务进入 `failed + retryable + EMBEDDING_UNAVAILABLE`，查询明确降级到 FTS5/BM25。v4 collection 使用完整 profile fingerprint 和 cosine metric，不按维度信任 legacy collection。

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

迁移先输出 profile、稳定 chunk ID、内容哈希清单；apply 前自动备份 SQLite 与 Chroma。只有 profile、内容哈希、missing 和检索 smoke test 都通过才切换。任何 `reupload_required` 论文都会阻止迁移激活。成功后仍保留 legacy collection，不自动删除旧向量。

经审批的旧数据隔离命令（默认仅 dry-run，严格校验 14/21/6/4 计数）：

```powershell
python -m backend.scripts.harden_legacy_data
python -m backend.scripts.harden_legacy_data --apply
```

RAG 评测需要在保留论文重传后人工标注 36–50 条问题。模板和 release gate 位于 `backend/evals/`：

```powershell
python -m backend.evals.evaluate_rag --dataset path/to/reviewed-rag-corpus.json
```

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

- 这是绑定 `127.0.0.1` 的本机单用户部署，不包含多用户账号体系。
- 真实 DeepSeek、讯飞 Spark Embedding、OpenAlex smoke test 需要凭据，只能手动运行，不进入默认离线 CI。
- OCR 与 cross-encoder 是可选增强；OCR 缺失时扫描件返回 retryable `OCR_REQUIRED`，不会成功入库为空论文。
- 保留的 4 篇旧论文在原始 PDF 重传前保持 `reupload_required`，其 legacy chunks 和 vectors 不进入正常检索。
- 完美数学公式识别不在本轮范围；无法确认的公式不做猜测。
- 复现实验室只生成辅助报告和模板，不执行代码，不承诺复现论文指标。

## 更多文档

- [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)
- [`docs/BRANCH_HANDOFF.md`](docs/BRANCH_HANDOFF.md)
- [`docs/LOCAL_SETUP.md`](docs/LOCAL_SETUP.md)

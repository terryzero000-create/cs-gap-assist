# CS Gap Assist Project Status

Last updated: 2026-06-02

## Purpose

CS Gap Assist is a research gap analysis assistant for computer science papers. Users upload papers they have read, enter a research direction, and the system should retrieve related literature, identify research gaps, suggest evidence-backed experiments, visualize citation evolution, and manage a personal research knowledge base.

## Current Progress

Overall first-version product progress: about 30%.

Foundation progress: about 70%.

Citation Graph branch MVP progress: 100% for isolated branch handoff.

The project has a working repository foundation and one isolated branch per feature module. The current implementation is still an MVP scaffold: several external integrations use deterministic mock/fallback behavior so development can continue without API keys or quota.

## Branch Structure

- `codex/foundation`
  - Shared backend and frontend foundation.
  - FastAPI app, `/api/v1` prefix, async route contract, unified error shape, PDF upload, SQLite metadata store, Chroma-style vector store wrapper with memory fallback, model provider abstraction, frontend TypeScript/Vite skeleton.
- `codex/reading-qa`
  - Paper reading Q&A module.
  - Adds `/api/v1/reading/qa` and returns answer plus paragraph-level sources.
- `codex/research-gap`
  - Research Gap analysis module.
  - Adds `/api/v1/gaps/analyze` with high/mid value gaps and evidence papers.
- `codex/experiment-suggest`
  - Experiment suggestion module.
  - Adds `/api/v1/experiments/suggest` with datasets, metrics, baselines, steps, risks, and 3-5 support papers.
- `codex/citation-graph`
  - Citation evolution graph module.
  - Adds `/api/v1/citations/graph` with D3-ready `nodes` and `links`, node caps, key-node scoring, optional OpenAlex expansion, and a usable keyword search UI.
- `codex/knowledge-base`
  - Personal knowledge base module.
  - Adds paper listing, note creation/listing, and unified search.

## Shared Contracts

- All backend APIs use `/api/v1/`.
- All backend route handlers under `/api/v1` must be `async`.
- PDF upload returns a `doc_id` UUID string.
- Follow-up operations reference uploaded papers by `doc_id`.
- Unified error response shape: `{"error": "message", "code": 400}`.
- Python code should use type annotations and docstrings.
- Frontend TypeScript uses strict mode and should not introduce `any`.
- API keys must come from `.env`; do not hardcode keys.
- Missing model keys should degrade to mock providers with explicit warnings.
- Semantic Scholar is deprecated for this project and must not be used for new citation or literature retrieval work.

## Foundation Capabilities

- FastAPI app in `backend/main.py`.
- API routers in `backend/api/`.
- Pydantic schemas in `backend/models/schemas.py`.
- Configuration in `backend/core/config.py`.
- Error handling in `backend/core/errors.py`.
- PDF parsing in `backend/services/pdf_parser.py`.
- SQLite metadata store in `backend/repositories/sqlite_store.py`.
- Embedding provider abstraction in `backend/rag/embedder.py`.
- Vector store abstraction in `backend/rag/vector_store.py`.
- Chat provider abstraction in `backend/llm/llm_service.py`.
- Frontend skeleton and typed API client in `frontend/src/`.

## Model Policy

- Default chat provider: DeepSeek.
- Default chat model: `deepseek-v4-pro`.
- Alternate DeepSeek model exposed: `deepseek-v4-flash`.
- Default embedding provider: OpenAI.
- Default embedding model: `text-embedding-3-small`.
- If `DEEPSEEK_API_KEY` or `OPENAI_API_KEY` is missing, the system should still run using mock providers and return warnings.

## External Literature Policy

- Semantic Scholar is deprecated and should stay disabled/unused in this codebase.
- Citation graph expansion should use OpenAlex only when explicitly enabled with `ENABLE_OPENALEX=true` and configured with `OPENALEX_API_KEY`.
- OpenAlex must remain optional; missing API key, missing network access, empty results, or API failures should return explicit warnings and deterministic fallback graph data.
- arXiv may still be used by branches that already depend on it, with deterministic fallback behavior for local development.

## Storage Policy

- SQLite stores paper metadata, gap history, experiment suggestions, favorite state, tags, and notes.
- Chroma is represented by `ChromaVectorStore`; if Chroma is unavailable, it falls back to an in-memory mirror.
- Vector filtering must support `doc_id`, `tags`, and `module_source`.
- `data/` is ignored by Git and should be treated as local runtime state.

## Test Commands

Run from repository root:

```powershell
python -m pytest backend/tests -q
npm test --prefix frontend
```

Current foundation verification at the time of this document:

- Backend: `9 passed`
- Frontend: `tsc --noEmit` passed

## Known MVP Limitations

- Module branches are isolated and have not yet been merged into one integrated application branch.
- OpenAlex and arXiv behavior is optional and mostly deterministic mock/fallback code.
- Some feature branch frontends are skeletons, but `codex/citation-graph` now has a keyword search workflow.
- RAG ranking is simple and designed for local development, not production retrieval quality.
- DeepSeek and OpenAI real calls need real API keys and further integration testing.
- Chroma is optional in tests; the memory mirror preserves local behavior.
- There is no deployment configuration yet.

## Recommended New Conversation Startup Prompt

Use this when opening a new conversation:

```text
Please read docs/PROJECT_STATUS.md and docs/BRANCH_HANDOFF.md first.
Then switch to <branch-name> and continue that branch's next steps.
Do not assume prior chat context.
```

Replace `<branch-name>` with one of:

- `codex/foundation`
- `codex/reading-qa`
- `codex/research-gap`
- `codex/experiment-suggest`
- `codex/citation-graph`
- `codex/knowledge-base`


# CS Gap Assist Project Status

Last updated: 2026-06-02

## Purpose

CS Gap Assist is a research gap analysis assistant for computer science papers. Users upload papers they have read, enter a research direction, and the system should retrieve related literature, identify research gaps, suggest evidence-backed experiments, visualize citation evolution, and manage a personal research knowledge base.

## Current Progress

Overall first-version product progress: about 65%.

Foundation progress: about 70%.

Integration MVP progress: complete for the first combined branch.

Reading QA branch MVP progress: 100% for isolated branch handoff.

Research Gap branch MVP progress: 100% for isolated branch handoff.

Experiment Suggestion branch MVP progress: 100% for isolated branch handoff.

Citation Graph branch MVP progress: 100% for isolated branch handoff.

Knowledge Base branch MVP progress: 100% for isolated branch handoff.

The project has a working repository foundation, one feature branch per module, and an integrated MVP branch that combines Reading QA, Research Gap, Experiment Suggestion, Citation Graph, and Knowledge Base behind one frontend navigation. The current implementation is still an MVP scaffold: several external integrations use deterministic mock/fallback behavior so development can continue without API keys or quota.

## Branch Structure

- `codex/foundation`
  - Shared backend and frontend foundation.
  - FastAPI app, `/api/v1` prefix, async route contract, unified error shape, PDF upload, SQLite metadata store, Chroma-style vector store wrapper with memory fallback, model provider abstraction, frontend TypeScript/Vite skeleton.
- `codex/integration-mvp`
  - Combined MVP branch created from `codex/foundation`.
  - Merges `codex/reading-qa`, `codex/research-gap`, `codex/experiment-suggest`, `codex/citation-graph`, and `codex/knowledge-base` in order.
  - Registers all feature routers in one FastAPI app.
  - Provides unified frontend tabs for Reading QA, Research Gap, Experiment Suggest, Citation Graph, and Knowledge Base.
- `codex/reading-qa`
  - Paper reading Q&A module.
  - Adds `/api/v1/reading/qa` and returns answer plus paragraph-level sources.
- `codex/research-gap`
  - Research Gap analysis module.
  - Adds `/api/v1/gaps/analyze` with high/mid value gaps and evidence papers.
  - Adds `/api/v1/gaps/history` for persisted gap history.
  - Adds `/api/v1/papers` for persisted paper selection after page refresh.
  - Includes a usable frontend Research Gap workbench with upload, paper selection, topic input, warnings, gap evidence, and history refresh.
- `codex/experiment-suggest`
  - Experiment suggestion module.
  - Adds `/api/v1/experiments/suggest` with datasets, metrics, baselines, steps, risks, and 3-5 support papers.
  - Adds `/api/v1/experiments/history` for persisted experiment plan history.
  - Adds a usable frontend Experiment Suggestion workbench that loads stored Gaps and suggests experiments for the selected Gap.
  - Uses arXiv as the external literature source with deterministic fallback; Semantic Scholar is deprecated and not used.
  - Repairs fenced/prose-wrapped or invalid model JSON and falls back to deterministic experiment plans when needed.
- `codex/citation-graph`
  - Citation evolution graph module.
  - Adds `/api/v1/citations/graph` with D3-ready `nodes` and `links`, node caps, key-node scoring, optional OpenAlex expansion, and a usable keyword search UI.
- `codex/knowledge-base`
  - Personal knowledge base module.
  - Adds paper listing, note creation/listing, tag/favorite updates, and unified search across papers, notes, chunks, Gap history, and experiment history.
  - Adds a usable frontend knowledge-base workbench with upload, search, filters, note creation, tag editing, and favorite toggling.

## Shared Contracts

- All backend APIs use `/api/v1/`.
- All backend route handlers under `/api/v1` must be `async`.
- PDF upload returns a `doc_id` UUID string.
- Follow-up operations reference uploaded papers by `doc_id`.
- Unified error response shape: `{"error": "message", "code": 400}`.
- Python code should use type annotations and docstrings.
- Frontend TypeScript uses strict mode and should not introduce `any`.
- Active API keys must come from `.env`; do not hardcode keys.
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

- arXiv is the default external literature source and does not require an API key.
- Semantic Scholar is deprecated and is not used by the Research Gap or Experiment Suggestion branches.
- External literature failures degrade to deterministic fallback evidence with warnings.
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
npm run build --prefix frontend
```

Current `codex/integration-mvp` verification at the time of this document:

- Backend: `36 passed`
- Frontend: `tsc --noEmit` passed
- Frontend build passed

## Known MVP Limitations

- The integrated branch is an MVP, not a production deployment.
- Some external literature behavior still uses deterministic fallback when live services are unavailable.
- OpenAlex and arXiv behavior is optional and mostly deterministic mock/fallback code.
- Reading QA, Research Gap, Experiment Suggestion, Citation Graph, and Knowledge Base have usable MVP workflows on their feature branches.
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
- `codex/integration-mvp`
- `codex/reading-qa`
- `codex/research-gap`
- `codex/experiment-suggest`
- `codex/citation-graph`
- `codex/knowledge-base`


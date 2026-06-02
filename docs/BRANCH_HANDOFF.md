# Branch Handoff Guide

Last updated: 2026-06-02

## How To Use This File

Each new conversation should read this file and `docs/PROJECT_STATUS.md` before doing work. Treat this file as the branch-specific handoff checklist. Do not rely on previous chat history.

Before working on a branch:

```powershell
git status --short --branch
git checkout <branch-name>
python -m pytest backend/tests -q
npm test --prefix frontend
```

If a branch does not contain the latest foundation hardening commit, merge or rebase `codex/foundation` first only after checking the diff and resolving conflicts intentionally.

## codex/foundation

Goal: shared project foundation used by all feature branches.

Current commits:

- `3f2d93b feat: scaffold shared foundation`
- `ffa00fe feat: harden shared foundation contracts`

Implemented:

- FastAPI app with `/api/v1` route prefix.
- Unified error response.
- Async route contract test.
- PDF upload and parsing fallback.
- SQLite metadata store for papers, gaps, experiment suggestions, favorites, tags, and notes.
- Chroma-style vector store wrapper with in-memory fallback.
- Vector filtering by `doc_id`, `tags`, and `module_source`.
- DeepSeek chat provider abstraction with mock fallback.
- OpenAI embedding provider abstraction with mock fallback.
- React/Vite/TypeScript frontend skeleton and typed API client.

Next steps:

- Add development docs for local setup.
- Add real Chroma integration tests behind an optional marker.
- Add stricter lint/type tooling for Python if desired.
- Create an integration branch when feature branches are ready to combine.

Verification:

```powershell
python -m pytest backend/tests -q
npm test --prefix frontend
```

Expected baseline:

- Backend: `9 passed`
- Frontend: TypeScript check passes.

## codex/reading-qa

Goal: paper intensive reading Q&A.

Implemented:

- `/api/v1/reading/qa`
- Question over uploaded `doc_ids`.
- Retrieves source chunks.
- Returns answer plus `sources` with `doc_id`, `chunk_id`, `page`, `text`, and `score`.
- Basic frontend component: `frontend/src/components/PaperUpload/ReadingQA.tsx`.

Known limitations:

- Depends on branch-local version of foundation before `ffa00fe`; merge latest `codex/foundation` before continuing.
- Answer generation uses provider fallback unless real DeepSeek key is configured.
- Source highlighting in the PDF UI is not implemented.

Next steps:

- Merge latest `codex/foundation`.
- Add frontend upload/question workflow.
- Add page/paragraph source display and citation jump behavior.
- Improve retrieval prompts and answer format.

Verification on branch:

```powershell
python -m pytest backend/tests/test_foundation.py backend/tests/test_reading_qa.py -q
npm test --prefix frontend
```

## codex/research-gap

Goal: Research Gap analysis from a topic and uploaded papers.

Current status: isolated branch MVP complete.

Key commits after foundation merge:

- `90e130e Merge branch 'codex/foundation' into codex/research-gap`
- `b42965b feat: advance research gap workflow`
- `8053e0b feat: add research gap history`
- `108b6e8 feat: load persisted papers`
- `9dcacd8 chore: disable semantic scholar by default`

Implemented:

- `/api/v1/gaps/analyze`
- Returns `gaps` with `gap_id`, `title`, `value_level`, `description`, `evidence_papers`, and `created_at`.
- `/api/v1/gaps/history`
- `/api/v1/papers`
- Real arXiv Atom response parsing with deterministic fallback.
- Semantic Scholar client remains available as optional code, but is disabled by default with `ENABLE_SEMANTIC_SCHOLAR=false`.
- Model JSON repair and validation for fenced/prose-wrapped JSON, unsupported `value_level`, missing evidence, and malformed items.
- Persists gaps in SQLite.
- Usable frontend Research Gap workbench:
  - Upload PDF.
  - Refresh persisted papers.
  - Select uploaded papers.
  - Enter topic.
  - Run analysis.
  - Display warnings, high/mid gaps, evidence papers, and persisted gap history.

Known limitations:

- Branch is still isolated and has not been merged into an integration branch.
- arXiv can fail in restricted or offline networks; deterministic fallback keeps the workflow usable.
- DeepSeek/OpenAI real behavior needs API keys and quality evaluation.
- Gap ranking and evidence quality are MVP-level and should be evaluated against real papers before production use.

Next steps:

- Create or update an integration branch when combining feature modules.
- Run real-key evaluation with `DEEPSEEK_API_KEY` and `OPENAI_API_KEY`.
- Optionally enable Semantic Scholar only in environments where it is reachable:
  - `ENABLE_SEMANTIC_SCHOLAR=true`
  - `SEMANTIC_SCHOLAR_API_KEY=<key>`
- Add browser-level QA when a browser automation dependency is available.

Verification on branch:

```powershell
python -m pytest backend/tests -q
npm run build --prefix frontend
```

Expected baseline:

- Backend: `16 passed`
- Frontend: production build succeeds.

## codex/experiment-suggest

Goal: generate literature-supported experiment plans for each Gap.

Implemented:

- `/api/v1/experiments/suggest`
- Returns experiment objective, datasets, metrics, baselines, steps, risks, and support papers.
- Ensures 3-5 support papers in the test path.
- Basic frontend component: `frontend/src/components/ExperimentSuggest/ExperimentPlanCard.tsx`.

Known limitations:

- Depends on branch-local version of foundation before `ffa00fe`; merge latest `codex/foundation` before continuing.
- Literature retrieval is mocked.
- Experiment plans are not yet persisted to SQLite on this branch.

Next steps:

- Merge latest `codex/foundation`.
- Persist experiment suggestions with `SQLiteStore.save_experiment`.
- Connect suggestions to real Gap records.
- Add frontend flow from selected Gap to experiment suggestions.

Verification on branch:

```powershell
python -m pytest backend/tests/test_foundation.py backend/tests/test_experiment_suggest.py -q
npm test --prefix frontend
```

## codex/citation-graph

Goal: visualize citation evolution for a technical keyword.

Implemented:

- `/api/v1/citations/graph?keyword=...`
- Returns D3-compatible `nodes` and `links`.
- Marks key nodes with `importance_score` and `is_key`.
- Basic D3 force graph component: `frontend/src/components/CitationGraph/CitationForceGraph.tsx`.

Known limitations:

- Depends on branch-local version of foundation before `ffa00fe`; merge latest `codex/foundation` before continuing.
- Graph data is deterministic MVP data, not real citation API data.
- Frontend graph lacks controls, loading state, and large-graph handling.

Next steps:

- Merge latest `codex/foundation`.
- Add real citation expansion through Semantic Scholar when available.
- Add graph size caps and key-node scoring policy.
- Add keyword search UI.

Verification on branch:

```powershell
python -m pytest backend/tests/test_foundation.py backend/tests/test_citation_graph.py -q
npm test --prefix frontend
```

## codex/knowledge-base

Goal: personal knowledge base for papers, notes, tags, favorites, and history.

Implemented:

- `/api/v1/knowledge/papers`
- `/api/v1/knowledge/notes`
- `/api/v1/knowledge/search`
- Lists uploaded papers.
- Creates and searches notes.
- Searches chunks from the vector store.
- Basic frontend component: `frontend/src/components/KnowledgeBase/KnowledgeBasePanel.tsx`.

Known limitations:

- Depends on branch-local version of foundation before `ffa00fe`; merge latest `codex/foundation` before continuing.
- Favorite/tag update API is not yet exposed on this branch.
- Gap and experiment history are not yet surfaced through knowledge search.

Next steps:

- Merge latest `codex/foundation`.
- Add favorite/tag update endpoints.
- Include gaps and experiments in unified search.
- Build a real frontend knowledge-base page with filters.

Verification on branch:

```powershell
python -m pytest backend/tests/test_foundation.py backend/tests/test_knowledge_base.py -q
npm test --prefix frontend
```

## Integration Strategy

Recommended order:

1. Keep `codex/foundation` as the source of shared contracts.
2. For each module branch, merge or rebase latest `codex/foundation`.
3. Resolve conflicts in shared files deliberately, especially:
   - `backend/main.py`
   - `backend/models/schemas.py`
   - `backend/repositories/sqlite_store.py`
   - `backend/rag/vector_store.py`
   - `frontend/src/types/index.ts`
   - `frontend/src/api/client.ts`
4. Create a new integration branch, for example `codex/integration-mvp`.
5. Merge module branches one by one and run tests after each merge.

Do not merge all feature branches at once. The branches intentionally touch some shared files, so one-at-a-time integration will be much easier to debug.


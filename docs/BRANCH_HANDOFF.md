# Branch Handoff Guide

Last updated: 2026-05-27

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

Implemented:

- `/api/v1/gaps/analyze`
- Returns `gaps` with `gap_id`, `title`, `value_level`, `description`, `evidence_papers`, and `created_at`.
- Mock Semantic Scholar and arXiv search clients.
- Persists gaps in SQLite.
- Basic frontend component: `frontend/src/components/GapAnalysis/GapList.tsx`.

Known limitations:

- Depends on branch-local version of foundation before `ffa00fe`; merge latest `codex/foundation` before continuing.
- External literature retrieval is mocked.
- Gap ranking and evidence quality need real model/retrieval evaluation.

Next steps:

- Merge latest `codex/foundation`.
- Replace mock external search with real Semantic Scholar/arXiv clients.
- Add frontend topic input and uploaded-paper selector.
- Add schema repair/validation around model JSON output.

Verification on branch:

```powershell
python -m pytest backend/tests/test_foundation.py backend/tests/test_research_gap.py -q
npm test --prefix frontend
```

## codex/experiment-suggest

Goal: generate literature-supported experiment plans for each Gap.

Current status: isolated branch MVP complete.

Key commits after foundation merge:

- `240dcef Merge branch 'codex/foundation' into codex/experiment-suggest`
- `bb2b3bc feat: advance experiment suggestion workflow`
- `43a0657 feat: add experiment history workflow`
- `b812a19 feat: add arxiv-backed experiment evidence`

Implemented:

- `/api/v1/experiments/suggest`
- Returns experiment objective, datasets, metrics, baselines, steps, risks, and support papers.
- Ensures 3-5 support papers in the test path.
- Persists generated experiment plans with `SQLiteStore.save_experiment`.
- Resolves a stored Gap by `gap_id` when topic context is omitted, using the Gap title and description for experiment planning.
- `/api/v1/experiments/history`
- `/api/v1/gaps/history` for selecting stored Gaps on this branch.
- arXiv search client with Atom parsing and deterministic fallback.
- Semantic Scholar client with live response parsing and deterministic fallback.
- Semantic Scholar is disabled by default through `ENABLE_SEMANTIC_SCHOLAR=false`; arXiv is the default external literature source.
- Semantic Scholar access does not require or use an API key on this branch.
- Model JSON repair and validation for fenced/prose-wrapped JSON, invalid JSON, missing `experiments`, malformed items, and missing required experiment fields.
- Deterministic fallback experiment generation when model output cannot be repaired.
- Usable frontend Experiment Suggestion workbench:
  - Loads stored Gaps.
  - Selects a Gap or accepts a manual Gap ID.
  - Loads saved experiment plans for the active Gap.
  - Generates new experiment suggestions.
  - Displays warnings, datasets, metrics, baselines, risks, steps, and support papers.
- Vite dev proxy for `/api` to `http://127.0.0.1:8000`.

Known limitations:

- Branch is still isolated and has not been merged into an integration branch.
- arXiv can fail in restricted or offline networks; deterministic fallback keeps the workflow usable.
- Semantic Scholar is optional, keyless, and disabled by default because access can be unreliable in mainland China.
- The workbench depends on stored Gap records from local SQLite history; full Gap generation is still on `codex/research-gap`.
- Real DeepSeek behavior needs API keys and quality evaluation.
- Experiment-plan quality is MVP-level and should be evaluated against real papers before production use.

Next steps:

- Create or update an integration branch when combining feature modules.
- Add experiment-plan quality evaluation against real Gap records and papers.
- Add browser-level QA after integration with the Research Gap module.

Verification on branch:

```powershell
python -m pytest backend/tests -q
npm test --prefix frontend
npm run build --prefix frontend
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


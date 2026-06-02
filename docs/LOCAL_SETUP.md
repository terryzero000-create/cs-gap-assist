# Local Setup

Last updated: 2026-06-02

## Required Runtime

- Python 3.11+
- Node.js and npm

## Backend Setup

Run from the repository root:

```powershell
python -m pip install -e .[dev]
```

Optional PDF/vector dependencies:

```powershell
python -m pip install -e .[dev,rag]
```

## Frontend Setup

```powershell
npm install --prefix frontend
```

## Environment

Copy `.env.example` to `.env` and set the keys available in your environment.

Required for real model behavior:

```env
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
```

The app still runs without these keys by using deterministic mock providers with explicit warnings.

Default external literature behavior:

```env
ENABLE_SEMANTIC_SCHOLAR=false
EXTERNAL_SEARCH_TIMEOUT_SECONDS=3
```

Semantic Scholar is disabled by default because access can be unreliable in mainland China. arXiv does not require an API key and is used as the default external literature source, with deterministic fallback behavior when unavailable.

## Run Locally

Backend:

```powershell
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
npm run dev --prefix frontend -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`.

## Verify

```powershell
python -m pytest backend/tests -q
npm run build --prefix frontend
```

Expected on `codex/research-gap` after the 2026-06-02 handoff:

- Backend: `16 passed`
- Frontend: production build succeeds.

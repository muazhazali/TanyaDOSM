# AskDOSM

AskDOSM is a local natural-language analytics assistant for five curated Malaysian public-statistics datasets. A React interface streams a sanitized view of its LangGraph workflow while FastAPI, local Ollama, and deterministic Pandas/DuckDB operations produce source-grounded results.

## Requirements and setup

- Windows with Python 3.14.x (developed against Python 3.14.6)
- Node.js 24 and pnpm 10.15.0 (managed through Corepack)
- [`uv`](https://docs.astral.sh/uv/)
- [Ollama for Windows](https://ollama.com/download)

```powershell
uv sync
ollama pull qwen3:8b
ollama pull embeddinggemma
Copy-Item .env.example .env
corepack enable
corepack install --global pnpm@10.15.0
pnpm --dir frontend install --frozen-lockfile
```

The package rejects interpreters outside Python 3.14. Python dependencies are captured in `uv.lock`; frontend dependencies are captured in `frontend/pnpm-lock.yaml`. Do not generate npm or Yarn lockfiles.

Start the API and Vite development server in separate terminals:

```powershell
uv run uvicorn askdosm.api.app:app --reload
pnpm --dir frontend dev
```

Open `http://localhost:5173`. Vite proxies `/api` to FastAPI on port 8000. Activation of `.venv` is unnecessary when commands are run through `uv run`.

For a local production-style build, compile the frontend and start FastAPI from the repository root. FastAPI serves `frontend/dist` at `/`:

```powershell
pnpm --dir frontend build
uv run uvicorn askdosm.api.app:app --host 127.0.0.1 --port 8000
```

The verified Python 3.14.6 environment resolves FastAPI, Uvicorn, aiosqlite, LangGraph, LangChain Ollama, DuckDB, Pandas, PyArrow, NumPy, and Pydantic versions in `uv.lock`.

## Supported data

| Dataset | Grain | Typical questions |
|---|---|---|
| `population_malaysia` | Annual, national | Malaysia population lookups and growth |
| `population_state` | Annual, state | State comparisons, trends, and rankings |
| `lfs_month` | Monthly, national | National unemployment and participation trends |
| `lfs_qtr_state` | Quarterly, state | State unemployment comparisons |
| `cpi_state_inflation` | Monthly, state | State inflation comparisons and trends |

Source files are downloaded from official DOSM Parquet URLs. They are validated before replacing the last usable file under `.askdosm-cache/datasets`. Catalogue embeddings are cached separately; statistical rows are never embedded.

## Architecture

```text
React/Vite
   -> FastAPI run queue + durable SSE events
   -> parse intent (structured Ollama output)
   -> hybrid catalogue search (aliases + metadata embeddings)
   -> select and inspect registered dataset
   -> constrained structured query plan
   -> allow-listed filtering and deterministic calculation
   -> validation with at most two replans
   -> deterministic answer, visualization specification, source, execution trace
```

The LLM cannot generate executable Python or SQL. Dataset IDs, columns, metrics, filters, and operations are checked against `data/catalogue.json`. Population and CPI sources apply default `overall` filters unless the question explicitly asks for a breakdown.

Each question is standalone. Questions, sanitized events, and results are retained in SQLite for seven days so a run can be reopened, but earlier questions are never supplied to the graph. One run is processed at a time to keep local CPU inference responsive.

The browser receives node status and approved structured artifacts over Server-Sent Events. DataFrames, API keys, prompts, raw model output, and hidden reasoning are never emitted or stored. Event sequence IDs allow a browser to replay progress after a refresh.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Check catalogue, SQLite, and Ollama readiness |
| `GET` | `/api/datasets` | List the five public dataset definitions |
| `POST` | `/api/runs` | Queue an independent question (maximum 500 characters) |
| `GET` | `/api/runs` | List recent runs |
| `GET` | `/api/runs/{id}` | Read a run snapshot and final answer |
| `GET` | `/api/runs/{id}/events` | Stream and replay sanitized SSE events |
| `DELETE` | `/api/runs/{id}` | Delete a completed, failed, or interrupted run |

Runs move through `queued`, `running`, `completed`, `failed`, or `interrupted`. A process restart marks unfinished work as interrupted rather than executing it again unexpectedly.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ASKDOSM_CHAT_MODEL` | `qwen3:8b` | Local intent and query-plan model |
| `ASKDOSM_EMBEDDING_MODEL` | `embeddinggemma` | Local catalogue metadata embeddings |
| `ASKDOSM_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama service endpoint |
| `ASKDOSM_REQUEST_TIMEOUT` | `30` | Reserved request timeout in seconds |
| `ASKDOSM_CACHE_DIR` | `.askdosm-cache` | Local public-data cache |
| `ASKDOSM_CACHE_TTL_HOURS` | `24` | Refresh interval |
| `ASKDOSM_RUN_DB_PATH` | `.askdosm-cache/runs.sqlite3` | SQLite run and event store |
| `ASKDOSM_RUN_RETENTION_DAYS` | `7` | Run-history retention |
| `ASKDOSM_MAX_CONCURRENT_RUNS` | `1` | Documented run concurrency; the MVP queue is single-worker |
| `ASKDOSM_MAX_QUESTION_LENGTH` | `500` | API question limit |
| `ASKDOSM_CORS_ORIGINS` | local Vite origins | Comma-separated development origins |

## Testing and evaluation

```powershell
uv run pytest
uv run python -c "import fastapi, langgraph, duckdb, pandas, pyarrow, aiosqlite; print('imports ok')"
uv run python evals/evaluate.py
pnpm --dir frontend test
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend build
pnpm --dir frontend test:e2e
```

To verify all five current remote schemas explicitly:

```powershell
$env:ASKDOSM_RUN_LIVE_TESTS = "1"
uv run pytest -m integration
```

Ordinary tests use in-memory fixtures and mocked model responses. Tests marked `integration` may access live DOSM or the local Ollama service and are not part of the default offline suite.

The benchmark in `evals/questions.json` contains 50 cases. `evals/evaluate.py` validates its structure and category distribution; running live model scoring is intentionally opt-in because it incurs API calls.

## Data interpretation and limitations

- Population values are in thousands of people and may vary slightly when detailed categories are summed because of rounding.
- Labour-force figures cross a population-benchmark break in 2025; the UI exposes this dataset provenance, but users must interpret cross-break trends cautiously.
- CPI is representative of an average consumer basket, not an individual's exact experienced inflation.
- Only one of the five registered datasets may be used per question.
- GDP, crime, district population, forecasting, multi-dataset joins, conversational context, downloads, public hosting, and authentication are out of scope.
- If a source changes schema, returns no matching records, or cannot support a requested period, AskDOSM fails explicitly instead of inventing a value.

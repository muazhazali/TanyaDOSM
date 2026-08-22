# AskDOSM

AskDOSM is a local natural-language analytics assistant for five curated Malaysian public-statistics datasets. It uses local Ollama models for structured intent and planning, LangGraph for validation/retry routing, and deterministic Pandas/DuckDB-compatible operations for every numeric result.

## Requirements and setup

- Windows with Python 3.14.x (developed against Python 3.14.6)
- [`uv`](https://docs.astral.sh/uv/)
- [Ollama for Windows](https://ollama.com/download)

```powershell
uv sync
ollama pull qwen3:8b
ollama pull embeddinggemma
Copy-Item .env.example .env
uv run streamlit run app.py
```

The package rejects interpreters outside Python 3.14. Run all project commands through `uv run` to use the pinned environment. Dependency versions are captured in `uv.lock`.

The verified Python 3.14.6 environment resolves Streamlit, LangGraph, LangChain Ollama, DuckDB, Pandas, PyArrow, Plotly, NumPy, and Pydantic versions in `uv.lock`.

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
Streamlit
   -> parse intent (structured Ollama output)
   -> hybrid catalogue search (aliases + metadata embeddings)
   -> select and inspect registered dataset
   -> constrained structured query plan
   -> allow-listed filtering and deterministic calculation
   -> validation with at most two replans
   -> deterministic answer, Plotly/table, source, execution trace
```

The LLM cannot generate executable Python or SQL. Dataset IDs, columns, metrics, filters, and operations are checked against `data/catalogue.json`. Population and CPI sources apply default `overall` filters unless the question explicitly asks for a breakdown.

Each question is standalone. The UI keeps messages only to display the current browser session; earlier messages are not supplied to the graph.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ASKDOSM_CHAT_MODEL` | `qwen3:8b` | Local intent and query-plan model |
| `ASKDOSM_EMBEDDING_MODEL` | `embeddinggemma` | Local catalogue metadata embeddings |
| `ASKDOSM_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama service endpoint |
| `ASKDOSM_REQUEST_TIMEOUT` | `30` | Reserved request timeout in seconds |
| `ASKDOSM_CACHE_DIR` | `.askdosm-cache` | Local public-data cache |
| `ASKDOSM_CACHE_TTL_HOURS` | `24` | Refresh interval |

## Testing and evaluation

```powershell
uv run pytest
uv run python -c "import streamlit, langgraph, duckdb, pandas, pyarrow, plotly; print('imports ok')"
uv run python evals/evaluate.py
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
- GDP, crime, district population, forecasting, multi-dataset joins, persistent context, downloads, hosting, and authentication are out of scope.
- If a source changes schema, returns no matching records, or cannot support a requested period, AskDOSM fails explicitly instead of inventing a value.

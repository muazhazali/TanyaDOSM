# AGENTS.md

Natural-language analytics assistant for official DOSM statistics. The catalogue in `data/catalogue.json` currently holds **169 curated datasets** across 12 domains (demography, labour markets, prices, national accounts, households, education, environment, economic sectors, public safety, statistical indicators, data dictionaries, metadata). FastAPI + LangGraph backend (`src/askdosm`), React 19/Vite frontend (`frontend`). The README documents the project; this file only records what an agent is likely to get wrong.

## Environment (strict)

- Python **must be 3.14.x** (`requires-python = ">=3.14,<3.15"`); the package rejects other interpreters (`src/askdosm/runtime.py`).
- Frontend: Node 24 + **pnpm 10.15.0 via Corepack**. Lockfile is `frontend/pnpm-lock.yaml` — never generate npm/Yarn lockfiles.
- Python deps via `uv` (`uv.lock`). Run everything with `uv run ...`; do not activate `.venv`.
- `.env` (from `.env.example`) needs `ASKDOSM_OLLAMA_API_KEY`; Cloudflare vars are optional (falls back to lexical catalogue search).
- `corepack enable` may fail writing shims to `C:\Program Files\nodejs` without admin. If so, set `COREPACK_HOME` to a user-writable dir and invoke `corepack pnpm@10.15.0 <cmd>`; the global `pnpm` on PATH may be a different version.

## Commands

```powershell
uv sync
pnpm --dir frontend install --frozen-lockfile
uv run uvicorn askdosm.api.app:app --reload   # API on :8000
pnpm --dir frontend dev                      # Vite on :5173, proxies /api -> :8000
```

Verification (all offline by default):

```powershell
uv run pytest                                # in-memory fixtures, mocked providers
pnpm --dir frontend test / typecheck / lint / build
```

- Frontend `build` runs `tsc -b` first — type errors fail the build.
- Live tests are opt-in and hit real DOSM/Ollama Cloud/Cloudflare: `$env:ASKDOSM_RUN_LIVE_TESTS="1"; uv run pytest -m integration`.
- `uv run python evals/evaluate.py` validates the 50-question benchmark structure; live scoring is intentionally not wired in (costs API calls). `evals/score.py` and `evals/diagnose*.py` are opt-in helpers.

## Architecture invariants (do not break)

- **The LLM never emits executable code/SQL.** It produces structured intent + a constrained query plan; everything (dataset IDs, columns, metrics, filters, ops) is validated against `data/catalogue.json`. Validation allows at most two replans (`ASKDOSM_MAX_RETRIES`).
- **One dataset per question for the default path.** Multi-dataset questions (enabled by default, `ASKDOSM_ENABLE_MULTI_DATASET`) go through a separate declarative DAG: the LLM emits a `MultiPlan` of `fetch`/`combine` steps (never code), which `validate_multi` checks against the catalogue and the **join whitelist** `data/joins.json`. Only whitelisted dataset pairs may be joined; steps are capped at `ASKDOSM_MAX_PLAN_STEPS`. Adding a dataset means editing `data/catalogue.json` (dimensions, measures, units, filters, aliases, schema) — new catalogue discoveries are "awaiting review" and must never be auto-registered.
- **Privacy boundary:** DataFrames, API keys, prompts, raw model output, and hidden reasoning must never appear in SSE events or the SQLite run store. Only sanitized events go to the browser (`src/askdosm/api`).
- One run at a time (`ASKDOSM_MAX_CONCURRENT_RUNS=1`); each question is standalone — prior runs are never fed to the graph. Restart marks unfinished runs `interrupted`.
- Population/CPI sources apply default `overall` filters unless a breakdown is explicitly requested.
- Fail explicitly (no invented values) when schemas change or no records match.

## Question routing (three intent lanes)

`QuestionIntent.kind` (`src/askdosm/models.py`) selects the path from `parse_question` (`src/askdosm/agent/graph.py`):

- `data` (default) — a statistics question: search catalogue → select → inspect → plan → execute → validate → answer.
- `capability` — greetings / "what data do you have": `answer_capability` lists catalogue domains from metadata.
- `project` — questions about the assistant itself ("what model are you", "where does the data come from", "is this accurate"): `answer_project` answers **only** from curated `data/assistant-facts.json` (EN/MS). Unmatched project questions fall back to the capability answer. Project/capability replies are rephrased by the LLM from the curated facts (`ASKDOSM_NATURAL_PROJECT_ANSWERS`, default on) with a grounding guard that rejects any number not present in the facts and falls back to the curated text. Never free-generate project facts — add/edit entries in that JSON file instead.

Matching strictness is tunable: `ASKDOSM_MIN_MATCH_SCORE` (default `0.10`) is the floor for a plausible dataset match; `ASKDOSM_CLARIFICATION_GAP` (default `0.03`) controls when a cross-domain near-tie asks for clarification. Vague-but-answerable questions proceed with an **assumptions** note on the answer payload rather than being refused. Filler words are filtered in `catalogue.search_lexical` (`STOPWORDS`).

## Naming gotcha

Project is branded **TanyaDOSM**, but the Python package is `askdosm`, env vars are prefixed `ASKDOSM_`, and the cache dir is `.askdosm-cache/`. These are retained for backward compatibility — do not rename them.

## Other notes

- `.askdosm-cache/` holds dataset Parquet caches, catalogue-monitor state, and the runs SQLite DB; it is runtime state, not source. The `.pytest-tmp-*` directories at the repo root are leftovers from test runs and can be deleted.
- Deployment: systemd unit at `deploy/tanyadosm.service`; needs only outbound HTTPS to `api.ollama.com` / `api.cloudflare.com` (no GPU).

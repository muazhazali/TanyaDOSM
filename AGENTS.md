# AGENTS.md

Natural-language analytics assistant for 5 curated DOSM datasets. FastAPI + LangGraph backend (`src/askdosm`), React 19/Vite frontend (`frontend`). The README is thorough; this file only records what an agent is likely to get wrong.

## Environment (strict)

- Python **must be 3.14.x** (`requires-python = ">=3.14,<3.15"`); the package rejects other interpreters.
- Frontend: Node 24 + **pnpm 10.15.0 via Corepack**. Lockfile is `frontend/pnpm-lock.yaml` — never generate npm/Yarn lockfiles.
- Python deps via `uv` (`uv.lock`). Run everything with `uv run ...`; do not activate `.venv`.
- `.env` (from `.env.example`) needs `ASKDOSM_GROQ_API_KEY`; Cloudflare vars are optional (falls back to lexical search).

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
- Live tests are opt-in and hit real DOSM/Groq/Cloudflare: `$env:ASKDOSM_RUN_LIVE_TESTS="1"; uv run pytest -m integration`.
- `uv run python evals/evaluate.py` validates the 50-question benchmark structure; live scoring is intentionally not wired in (costs API calls).

## Architecture invariants (do not break)

- **The LLM never emits executable code/SQL.** It produces structured intent + a constrained query plan; everything (dataset IDs, columns, metrics, filters, ops) is validated against `data/catalogue.json`. Validation allows at most two replans.
- Only **one of the five registered datasets** per question. Adding a dataset means editing `data/catalogue.json` (dimensions, measures, units, filters, aliases, schema) — new catalogue discoveries are "awaiting review" and must never be auto-registered.
- **Privacy boundary:** DataFrames, API keys, prompts, raw model output, and hidden reasoning must never appear in SSE events or the SQLite run store. Only sanitized events go to the browser (`src/askdosm/api`).
- One run at a time (`ASKDOSM_MAX_CONCURRENT_RUNS=1`); each question is standalone — prior runs are never fed to the graph. Restart marks unfinished runs `interrupted`.
- Population/CPI sources apply default `overall` filters unless a breakdown is explicitly requested.
- Fail explicitly (no invented values) when schemas change or no records match.

## Naming gotcha

Project is branded **TanyaDOSM**, but the Python package is `askdosm`, env vars are prefixed `ASKDOSM_`, and the cache dir is `.askdosm-cache/`. These are retained for backward compatibility — do not rename them.

## Other notes

- `.askdosm-cache/` holds dataset Parquet caches, catalogue-monitor state, and the runs SQLite DB; it is runtime state, not source. The `.pytest-tmp-*` directories at the repo root are leftovers from test runs and can be deleted.
- Deployment: systemd unit at `deploy/tanyadosm.service`; needs only outbound HTTPS to `api.groq.com` / `api.cloudflare.com` (no GPU/Ollama).

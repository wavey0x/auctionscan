# Auctionscan

Auctionscan is a SQLite-backed Dutch auction indexer, API, and React UI.

## Layout

- `backend`: indexer and FastAPI application
- `ui`: React frontend
- `artifacts`: pinned ABI and source references for supported contracts
- `scripts`: utility scripts

## Setup

```bash
cp .env.example .env
uv python install 3.11
uv sync --project backend --locked --extra test
```

Backend commands run through `uv`; no manual virtualenv activation is needed.

## Run

API:

```bash
uv --project backend run uvicorn backend.api.app:app --host 127.0.0.1 --port 8001
```

Indexer:

```bash
uv --project backend run python -m backend.indexer.app --network ethereum --watch --log-level INFO
```

UI:

```bash
cd ui
npm ci
npm run dev
```

Tests:

```bash
uv --project backend run pytest
```

## Notes

- One long-running indexer process per network.
- SQLite is the system of record.
- `--reproject` rebuilds projected state from stored facts.
- Public round links use `/round/{chain_id}/{auction_address}/{round_id}`.
  Round numbers are derived from indexed kick history; corrections to earlier
  history can renumber rounds, so these links follow the current numbering.
  API responses retain exact event occurrences for take selection and live-price
  snapshot checks. Round detail uses `/api/rounds/{chain_id}/{auction_address}/{round_id}`.

## API contract and locked builds

Use the uv version pinned in `backend/pyproject.toml` locally, in CI, and on the deployment host.
Install backend dependencies with `uv sync --project backend --locked` (add
`--extra test` for development). Deploy the matching UI and API together.

After changing API models or routes, run `npm --prefix ui run generate:api`.
The generator exports local OpenAPI without a server, database, or RPC connection.
Commit `ui/src/shared/types/generated.ts`; CI checks it with `npm --prefix ui run check:api`.
The small fetch wrapper uses the generated request and response types.

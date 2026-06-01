<!-- Agent: Claude | Phase: post-5 | Depends on: backend (all), docker dev stack -->

# Testing strategy

The backend's automated safety net. Born from a real incident (2026-06-01): the
`fetch_market_data` job failed daily with `RateLimitError('twelve_data rate limit
exhausted')`, which masked a second bug (fetching `today..today` before the US session
has a settled bar). Both are now locked by regression tests so they cannot come back.

## Layout

```
conftest.py                      # repo root — repoints DATABASE_URL at the test DB
pyproject.toml                   # pytest / ruff / mypy / coverage config
backend/requirements-dev.txt     # pytest, pytest-asyncio, respx, time-machine, ruff, mypy
backend/tests/
├── conftest.py                  # fixtures (db_session, clean_db, api_client)
├── factories.py                 # DTO builders + DB-row seeders
├── unit/                        # pure logic — no DB, no network (fast)
├── integration/                 # real test DB and/or respx-mocked providers
└── regression/                  # one test per previously-fixed bug
```

Markers: `unit`, `integration`, `regression` (a test may carry both `regression` and
`unit` when it is DB-free).

## How to run

Tests run **inside the `trader-api` container** (Python 3.12 + deps live there; the Pi
host is 3.10). The test database is a **separate** database, `autonomous_trader_test`,
on the same TimescaleDB server as dev — never touches dev/prod data.

```bash
make test          # full suite (installs dev deps, creates+migrates test DB, pytest)
make test-unit     # pure logic only — fast, no DB
make test-int      # DB-backed integration
make test-reg      # regression guards
make cov           # full suite + coverage report
make lint          # ruff
make typecheck     # mypy
make install-hooks # pre-push hook -> runs (unit + regression) before every push
```

Under the hood: [scripts/test.sh](../../scripts/test.sh) `docker exec`s into the
container, installs [backend/requirements-dev.txt](../../backend/requirements-dev.txt),
runs [scripts/setup-test-db.sh](../../scripts/setup-test-db.sh) (idempotent
create + `alembic upgrade head`), then pytest.

## DB isolation — two strategies

The strategy depends on how the code under test gets its session:

- **`db_session` → rollback.** For code that *receives* a session (queries,
  `PaperBroker`, `PortfolioManager`). A session is bound to an open transaction with
  `join_transaction_mode="create_savepoint"`; the transaction is rolled back after the
  test, so even committed work vanishes.
- **`clean_db` → truncate.** For **jobs**, which open their *own* `async_session()` and
  commit — those can't be rolled back, so every table is `TRUNCATE`d afterwards. Job
  tests seed what they need (jobs trade every active portfolio, etc.).
- **`api_client`.** `httpx.ASGITransport` over the FastAPI app with
  `get_session` overridden to the rollback `db_session`, so endpoint writes roll back too.

> Each test runs on its own event loop (pytest-asyncio), so the DB fixtures
> `await engine.dispose()` on teardown — otherwise a pooled connection bound to a
> closed loop raises `RuntimeError: Event loop is closed`.

## Rules

- **No test touches the real network.** Provider HTTP (Yahoo, Twelve Data) is mocked
  with `respx`. Live contract tests against the real APIs are intentionally out of
  scope for now.
- **Nothing hardcoded that the app reads from config/env** — tests set env via
  `monkeypatch`.
- A regression test must **fail if its fix is reverted** — that's the point. Verified
  for both 2026-06-01 bugs.

## What's covered today

- **unit**: indicators (RSI/MA/ATR), composite scorer + ranker, risk sizing,
  performance metrics, validation, calendar/schedule + market-hours, provider helpers,
  provider HTTP behaviour (retry/backoff/429-classification) via respx, the per-symbol
  fallback, and trailing-stop maths (pct / ATR distance / VIX regime).
- **integration**: idempotent upsert, market/watchlist queries, `PaperBroker` fills &
  ledger cash, `fetch_market_data` end-to-end, the `protective_sell` job (pct + ATR
  paths, market-closed skip), API health/status/watchlist.
- **regression**: incremental trailing window; fallback only fetches the gap.

## Not yet (future)

Frontend (vitest/Playwright), cloud CI, `PortfolioManager`/`run_analysis`/
`execute_paper_trades` integration depth, a coverage gate (`--cov-fail-under`).

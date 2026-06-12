#!/usr/bin/env bash
# Run the backend test suite in a THROWAWAY container with the working tree
# bind-mounted (Python 3.12 + deps live in the app image; the host is 3.10).
#
# The live stack is the production compose: trader-api runs the BAKED image with no
# bind-mount and no test harness (no root conftest.py, no scripts/), so exec-ing into
# it would test the deployed code, not your edits. A fresh container from the same
# image with `-v repo:/app` tests exactly what you have on disk.
#
# DB-backed suites reach TimescaleDB through the compose network (trader-db, host
# `db`) and use the separate `autonomous_trader_test` database (setup-test-db.sh).
# Optional first arg is a marker: unit | integration | regression.
#
#   scripts/test.sh                 # everything
#   scripts/test.sh unit            # fast, no DB
#   scripts/test.sh "unit or regression"
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${TEST_IMAGE:-docker-api:latest}"
NETWORK="${TEST_NETWORK:-docker_default}"
MARKER="${1:-}"

# Pure-unit runs don't need the database; skip the (slower) DB setup for them.
NEEDS_DB=1
case "$MARKER" in
  unit) NEEDS_DB=0 ;;
esac

PYTEST="python -m pytest"
[ -n "$MARKER" ] && PYTEST="$PYTEST -m \"$MARKER\""

SETUP=""
DOCKER_ARGS=(--rm -v "$REPO_DIR":/app -w /app)
if [ "$NEEDS_DB" -eq 1 ]; then
  SETUP="sh scripts/setup-test-db.sh && "
  DOCKER_ARGS+=(--network "$NETWORK" --env-file "$REPO_DIR/.env")
else
  # conftest imports the engine at collection; any syntactically valid URL works.
  DOCKER_ARGS+=(-e DATABASE_URL='postgresql+asyncpg://test:test@localhost:5/test')
fi

docker run "${DOCKER_ARGS[@]}" "$IMAGE" sh -c "
  pip install -q -r backend/requirements-dev.txt &&
  ${SETUP}${PYTEST}
"

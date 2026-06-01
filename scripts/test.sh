#!/usr/bin/env bash
# Run the backend test suite INSIDE the running api container (Python 3.12 + deps live
# there; the host is 3.10). Installs dev deps (idempotent), ensures the test DB exists,
# then runs pytest. Optional first arg is a marker: unit | integration | regression.
#
#   scripts/test.sh                 # everything
#   scripts/test.sh unit            # fast, no DB
#   scripts/test.sh "unit or regression"
set -euo pipefail

CONTAINER="${TEST_CONTAINER:-trader-api}"
MARKER="${1:-}"

# Pure-unit runs don't need the database; skip the (slower) DB setup for them.
NEEDS_DB=1
case "$MARKER" in
  unit) NEEDS_DB=0 ;;
esac

PYTEST="python -m pytest"
[ -n "$MARKER" ] && PYTEST="$PYTEST -m \"$MARKER\""

SETUP=""
[ "$NEEDS_DB" -eq 1 ] && SETUP="sh scripts/setup-test-db.sh && "

docker exec "$CONTAINER" sh -lc "
  pip install -q -r backend/requirements-dev.txt &&
  ${SETUP}${PYTEST}
"

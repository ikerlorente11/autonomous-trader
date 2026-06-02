#!/usr/bin/env bash
# Deploy the latest origin/main onto this Raspberry Pi.
#
# The live stack runs the DEV compose with the source bind-mounted (..:/app), so a
# `git pull` IS the deploy: uvicorn runs with --reload (api picks up automatically),
# the Vite frontend has HMR, and only the scheduler (APScheduler, no --reload) needs
# a restart. We therefore:
#   1. fast-forward the live working tree to origin/master,
#   2. rebuild the image ONLY when deps / Dockerfile changed,
#   3. run the full test suite against the new code,
#   4. ROLL BACK to the previous commit if the suite fails, so the running app is
#      never LEFT on red code.
#
# Caveat (inherent to bind-mounts + --reload): between the reset and the test result
# the live api is already serving the new code. The rollback guarantees the end state
# is always tested, not that there is zero exposure window. For zero exposure you'd
# need an ephemeral test stack on a temp checkout — heavier on the Pi's RAM.
#
# Run manually:  APP_DIR=/home/raspberry/projects/autonomous-trader ./scripts/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/home/raspberry/projects/autonomous-trader}"

# Reproduce EXACTLY how the live stack was launched: from the docker/ dir with both
# compose files, which yields compose project name "docker" (matches the running
# containers). Running compose from anywhere else would spawn a duplicate stack.
dc() { ( cd "$APP_DIR/docker" && docker compose -f docker-compose.yml -f docker-compose.dev.yml "$@" ); }

cd "$APP_DIR"

PREV="$(git rev-parse HEAD)"
git fetch --prune origin
git checkout main
git reset --hard origin/main
NEW="$(git rev-parse HEAD)"

if [ "$PREV" = "$NEW" ]; then
  echo "Already at ${NEW:0:8} — nothing to deploy."
  exit 0
fi

echo "Deploying ${PREV:0:8} -> ${NEW:0:8}"
CHANGED="$(git diff --name-only "$PREV" "$NEW")"

rollback() {
  echo "::error::Tests failed — rolling back to ${PREV:0:8}"
  git reset --hard "$PREV"
  dc up -d
  dc restart scheduler >/dev/null 2>&1 || true
}

# Runtime deps / Dockerfile changes are not picked up by the bind-mount + --reload
# (those only ship source), so the image must be rebuilt.
if echo "$CHANGED" | grep -qE '(^|/)requirements.*\.txt$|^docker/Dockerfile$|^pyproject\.toml$'; then
  echo "Deps / Dockerfile changed — rebuilding the app image."
  dc up -d --build
else
  dc up -d
fi

# Gate: run the suite against the new code; roll back if it fails.
if ! ./scripts/test.sh; then
  rollback
  exit 1
fi

# Apply code that does NOT hot-reload: the scheduler.
dc restart scheduler

# Frontend deps changed → its container reinstalls on start (npm install on launch).
if echo "$CHANGED" | grep -qE '^frontend/package(-lock)?\.json$'; then
  echo "Frontend deps changed — restarting frontend to reinstall."
  dc restart frontend
fi

echo "Deploy OK — now at ${NEW:0:8}"

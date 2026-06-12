#!/usr/bin/env bash
# Deploy the latest origin/main onto this Raspberry Pi — PRODUCTION stack.
#
# The live stack runs the base compose file only (docker/docker-compose.yml): the
# image bakes the source AND the built SvelteKit frontend (FastAPI serves it on the
# subdomain port, 8030), so EVERY change requires an image rebuild — there are no
# bind-mounts in production. The flow is:
#   1. fast-forward the working tree to origin/main (abort if the tree is dirty,
#      so an unattended run can never wipe in-progress local work),
#   2. docker compose build  — old containers keep serving while this runs,
#   3. docker compose up -d  — init re-runs migrations, api/scheduler swap over,
#   4. health-check the api;  on ANY failure roll back to the previous commit,
#      rebuild and restore it, so the running app never stays on broken code.
#
# Tests are NOT run here: the GitHub-hosted CI (ci.yml) gates every PR/push to main
# with the full suite, and the production image has neither dev deps nor the test
# harness (those came from the dev bind-mount). CI is the gate; this is the deploy.
#
# Triggered automatically by .github/workflows/deploy.yml (self-hosted runner on
# this Pi, on every push/merge to main) and by a cron fallback. Run manually:
#   ./scripts/deploy.sh           # deploy if origin/main moved
#   ./scripts/deploy.sh --force   # rebuild + restart even with no new commits
set -euo pipefail

APP_DIR="${APP_DIR:-/home/raspberry/projects/autonomous-trader}"
# Last successfully deployed commit — the dedupe key for unattended runs. Comparing
# against this (not HEAD) means a work-in-progress branch checked out locally never
# makes cron think there is something new to deploy.
STATE_FILE="${STATE_FILE:-$HOME/.local/state/autonomous-trader/deployed-sha}"

# Same launch shape as the live stack: from docker/ so the compose project name is
# "docker" (matches the existing containers + the postgres_data volume).
# --env-file ../.env is REQUIRED: compose interpolates ${API_PORT}/${DB_PORT} in the
# `ports:` blocks from its own env file, NOT from the services' env_file.
dc() { ( cd "$APP_DIR/docker" && docker compose --env-file ../.env -f docker-compose.yml "$@" ); }

API_PORT="$(grep -E '^API_PORT=' "$APP_DIR/.env" | tail -1 | cut -d= -f2)"
HEALTH_URL="http://localhost:${API_PORT:-8030}/api/health"

health_check() {
  for _ in $(seq 1 18); do
    if curl -fsS --max-time 5 "$HEALTH_URL" >/dev/null 2>&1; then return 0; fi
    sleep 5
  done
  return 1
}

# Never overlap two deploys (Actions queues its own runs, but the cron fallback or a
# manual run could race them).
exec 9>"/tmp/autonomous-trader-deploy.lock"
if ! flock -n 9; then
  echo "Another deploy is in progress — skipping."
  exit 0
fi

cd "$APP_DIR"

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "::error::Working tree has uncommitted changes — refusing to deploy over them."
  exit 1
fi

git fetch --prune origin
NEW="$(git rev-parse origin/main)"
DEPLOYED="$(cat "$STATE_FILE" 2>/dev/null || true)"

if [ "$DEPLOYED" = "$NEW" ] && [ "${1:-}" != "--force" ]; then
  echo "Already deployed ${NEW:0:8} — nothing to do."
  exit 0
fi

PREV="${DEPLOYED:-$(git rev-parse HEAD)}"
git checkout -q main
git reset --hard "$NEW"
echo "Deploying ${PREV:0:8} -> ${NEW:0:8}"

rollback() {
  echo "::error::Deploy of ${NEW:0:8} failed — rolling back to ${PREV:0:8}"
  git reset --hard "$PREV"
  dc build
  dc up -d --remove-orphans
  if health_check; then
    mkdir -p "$(dirname "$STATE_FILE")"
    echo "$PREV" >"$STATE_FILE"
    echo "Rollback OK — serving ${PREV:0:8}."
  else
    echo "::error::Rollback health check ALSO failed — manual intervention needed."
  fi
}

if ! dc build; then
  # Old containers were never touched; just restore the working tree.
  echo "::error::Image build failed — containers still on ${PREV:0:8}."
  git reset --hard "$PREV"
  exit 1
fi

if ! dc up -d --remove-orphans || ! health_check; then
  rollback
  exit 1
fi

# Drop dangling layers from the superseded image (Pi disk budget).
docker image prune -f >/dev/null 2>&1 || true

mkdir -p "$(dirname "$STATE_FILE")"
echo "$NEW" >"$STATE_FILE"
echo "Deploy OK — now at ${NEW:0:8}, healthy at ${HEALTH_URL}"

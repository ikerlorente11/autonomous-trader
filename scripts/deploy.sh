#!/usr/bin/env bash
# Deploy the latest origin/main onto this Raspberry Pi — PRODUCTION stack.
#
# The live stack runs the base compose file only (docker/docker-compose.yml): the
# image bakes the source AND the built SvelteKit frontend (FastAPI serves it on the
# subdomain port, 8030), so EVERY change needs a new image — there are no
# bind-mounts in production. The CI (ci.yml) builds it, one tag per commit, in
# ghcr.io/ikerlorente11/autonomous-trader; the Pi no longer builds. The flow is:
#   1. fast-forward the working tree to the commit to deploy (abort if the tree is
#      dirty, so an unattended run can never wipe in-progress local work),
#   2. docker compose pull  — that commit's image; old containers keep serving,
#   3. docker compose up -d  — init re-runs migrations, api/scheduler swap over,
#   4. health-check the api;  on ANY failure roll back to the previous commit's
#      image, so the running app never stays on broken code.
#
# Tests are NOT run here: the CI gates every PR/push to main with the full suite and
# only publishes the image when it passes. CI is the gate; this is the deploy.
#
# Triggered automatically by .github/workflows/deploy.yml (self-hosted runner on
# this Pi, once the CI of a push to main has succeeded: DEPLOY_SHA is that commit)
# and by a cron fallback. Run manually:
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
# The app's services (the db's image is pinned apart and never pulled here). `pull` of a commit with no image
# (its CI not finished, or failed) fails, and nothing is touched.
APP_SERVICES=(init api scheduler)
use_image() { export TRADER_IMAGE_TAG="$1"; dc pull --quiet "${APP_SERVICES[@]}"; }

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
NEW="${DEPLOY_SHA:-$(git rev-parse origin/main)}"
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
  # The commits before the CI built images have none: build that one here.
  use_image "$PREV" || dc build
  dc up -d --remove-orphans
  if health_check; then
    mkdir -p "$(dirname "$STATE_FILE")"
    echo "$PREV" >"$STATE_FILE"
    echo "Rollback OK — serving ${PREV:0:8}."
  else
    echo "::error::Rollback health check ALSO failed — manual intervention needed."
  fi
}

if ! use_image "$NEW"; then
  # Old containers were never touched; just restore the working tree.
  echo "::error::No image for ${NEW:0:8} in GHCR (its CI not finished or failed?) — containers still on ${PREV:0:8}."
  git reset --hard "$PREV"
  exit 1
fi

if ! dc up -d --remove-orphans || ! health_check; then
  rollback
  exit 1
fi

# Drop dangling layers from the superseded image (Pi disk budget).
docker image prune -f >/dev/null 2>&1 || true
# And the other commits' images: only the one now serving stays (Pi disk budget).
docker images ghcr.io/ikerlorente11/autonomous-trader --format '{{.Tag}}' | grep -vxF -e "$NEW" -e latest   | xargs -r -I{} docker rmi "ghcr.io/ikerlorente11/autonomous-trader:{}" >/dev/null 2>&1 || true

mkdir -p "$(dirname "$STATE_FILE")"
echo "$NEW" >"$STATE_FILE"
echo "Deploy OK — now at ${NEW:0:8}, healthy at ${HEALTH_URL}"

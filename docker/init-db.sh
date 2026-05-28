#!/usr/bin/env bash
# One-shot DB initializer. Waits for TimescaleDB to accept connections, then
# applies Alembic migrations (TimescaleDB hypertables are created by the
# migration scripts). Idempotent: `alembic upgrade head` is a no-op once the DB
# is already at head, so this is safe to re-run on every `docker compose up`.
#
# IMPORTANT (CLAUDE.md overrides the launch prompt): this script does NOT seed
# any watchlist symbols. The watchlist is populated at runtime and hardcoding
# symbols is forbidden. An operator may optionally point WATCHLIST_SEED_FILE at
# a file they provide; if unset or the file is absent, nothing is seeded.
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL must be set}"

# Alembic env.py reads DATABASE_URL itself and uses the async (asyncpg) driver,
# the same URL the app uses — no separate sync URL is needed for migrations.
# alembic.ini lives at backend/db/migrations/alembic.ini with
# script_location=%(here)s and prepend_sys_path=../../.. (-> /app), so we run
# from the repo root and point -c at the ini.
ALEMBIC_INI="backend/db/migrations/alembic.ini"

# --- wait for the database to accept TCP connections -----------------------
# Parse host:port out of the URL (postgresql+asyncpg://user:pass@host:port/db).
db_hostport="${DATABASE_URL#*@}"     # strip scheme + creds
db_hostport="${db_hostport%%/*}"     # strip /dbname and query
db_host="${db_hostport%%:*}"
db_port="${db_hostport##*:}"
[ "$db_port" = "$db_host" ] && db_port=5432

echo "init-db: waiting for ${db_host}:${db_port} ..."
for _ in $(seq 1 60); do
  if python -c "import socket,sys; s=socket.socket(); s.settimeout(2); sys.exit(0 if s.connect_ex(('${db_host}', ${db_port}))==0 else 1)"; then
    echo "init-db: database is reachable"
    break
  fi
  sleep 2
done

# --- apply migrations (creates tables + hypertables) -----------------------
echo "init-db: running alembic upgrade head"
alembic -c "${ALEMBIC_INI}" upgrade head
echo "init-db: migrations applied"

# --- optional, operator-provided seed (empty/absent by default) ------------
if [ -n "${WATCHLIST_SEED_FILE:-}" ] && [ -s "${WATCHLIST_SEED_FILE}" ]; then
  echo "init-db: WATCHLIST_SEED_FILE set; this is operator-provided and NOT committed."
  echo "init-db: no built-in seeding logic — provide your own loader if needed."
fi

echo "init-db: done"

#!/usr/bin/env sh
# Idempotent: create the isolated test database on the same server as DATABASE_URL,
# then bring it to head with alembic. Meant to run INSIDE the api container (asyncpg +
# alembic available there). Safe to re-run.
set -e

TEST_DB_NAME=autonomous_trader_test

python - "$TEST_DB_NAME" <<'PY'
import asyncio, os, sys
from urllib.parse import urlsplit

name = sys.argv[1]
p = urlsplit(os.environ["DATABASE_URL"])

async def main():
    import asyncpg
    conn = await asyncpg.connect(
        host=p.hostname, port=p.port or 5432,
        user=p.username, password=p.password, database="postgres",
    )
    exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", name)
    if not exists:
        await conn.execute(f'CREATE DATABASE "{name}"')
        print(f"created database {name}")
    else:
        print(f"database {name} already present")
    await conn.close()

asyncio.run(main())
PY

TEST_URL=$(python - "$TEST_DB_NAME" <<'PY'
import os, sys
from urllib.parse import urlsplit, urlunsplit
p = urlsplit(os.environ["DATABASE_URL"])
print(urlunsplit(p._replace(path="/" + sys.argv[1])))
PY
)

# alembic env.py reads DATABASE_URL from the environment; point it at the test DB.
cd "$(dirname "$0")/../backend/db/migrations"
DATABASE_URL="$TEST_URL" alembic upgrade head
echo "test DB at head"

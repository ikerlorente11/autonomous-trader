"""Root conftest — runs before any test module is imported.

Critical ordering: backend/db/session.py builds the async engine from DATABASE_URL
*at import time*, so we must repoint DATABASE_URL at the isolated test database
(autonomous_trader_test) here, before any `backend.*` import happens. Same server,
separate DB name — never touches dev/prod data.
"""

import os
from urllib.parse import urlsplit, urlunsplit

TEST_DB_NAME = "autonomous_trader_test"


def _to_test_url(url: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{TEST_DB_NAME}"))


_base = os.environ.get("DATABASE_URL")
if _base and not urlsplit(_base).path.endswith(TEST_DB_NAME):
    os.environ["DATABASE_URL"] = _to_test_url(_base)

# Never let a test reach the real scheduler job store.
os.environ.pop("SCHEDULER_DB_URL", None)

# The suite runs with the operator's --env-file .env, so live tuning must not decide
# test outcomes. The freshness gate is the sharp one: fixtures seed bars at fixed past
# dates, and a production MAX_BAR_STALENESS_DAYS would silently drop every symbol from
# scoring. Tests that exercise the gate set it themselves via monkeypatch.
os.environ["MAX_BAR_STALENESS_DAYS"] = "0"

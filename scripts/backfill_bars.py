"""Backfill daily bars for the active watchlist over a long window.

One-shot operational tool (idempotent upsert — safe to re-run):
    docker run --rm -v "$PWD":/app -w /app --network docker_default \
      --env-file .env docker-api:latest python scripts/backfill_bars.py [--days 1155]

The analysis jobs only keep ~400 days warm; the backtester wants years. This walks
the provider symbol-by-symbol through the standard ingest path (validation +
idempotent upsert), so it respects throttles and writes exactly like the daily job.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt

from backend.data_ingestion.ingest import ingest_daily_bars
from backend.db.queries.portfolio_queries import get_active_watchlist
from backend.db.session import async_session


async def main(days: int) -> None:
    async with async_session() as session:
        watchlist = await get_active_watchlist(session)
        symbols = sorted(w.symbol for w in watchlist)
        end = dt.date.today()
        start = end - dt.timedelta(days=days)
        print(f"backfilling {len(symbols)} symbols {start} -> {end}", flush=True)
        report = await ingest_daily_bars(session, symbols, start, end)
        await session.commit()
        print(f"done: {report}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3 * 365 + 60)
    args = parser.parse_args()
    asyncio.run(main(args.days))

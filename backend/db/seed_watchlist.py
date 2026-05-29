"""Seed the watchlist from a CSV file — only when the table is empty.

Bootstrap convenience: symbols live as data (CLAUDE.md forbids hardcoding them in
analysis logic) and stay editable via the API. Idempotent — if the watchlist
already has any row this is a no-op, so removed symbols are not resurrected.
"""
import asyncio
import csv
import os
import sys

from sqlalchemy import func, select

from backend.db.models import Watchlist
from backend.db.session import async_session


def _read_rows(path: str) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        lines = [ln for ln in fh if not ln.lstrip().startswith("#")]
    for raw in csv.DictReader(lines):
        symbol = (raw.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        rows.append(
            {
                "symbol": symbol,
                "sector": (raw.get("sector") or "").strip() or None,
                "asset_class": (raw.get("asset_class") or "").strip() or None,
            }
        )
    return rows


async def seed(path: str) -> int:
    rows = _read_rows(path)
    if not rows:
        print(f"seed-watchlist: {path} has no symbols; nothing to do")
        return 0
    async with async_session() as session:
        existing = await session.scalar(select(func.count()).select_from(Watchlist))
        if existing:
            print(f"seed-watchlist: watchlist already has {existing} rows; skipping")
            return 0
        session.add_all(
            Watchlist(
                symbol=r["symbol"],
                sector=r["sector"],
                asset_class=r["asset_class"],
                active=True,
            )
            for r in rows
        )
        await session.commit()
    print(f"seed-watchlist: inserted {len(rows)} symbols from {path}")
    return len(rows)


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("WATCHLIST_SEED_FILE")
    if not path:
        print("seed-watchlist: no path and WATCHLIST_SEED_FILE unset; nothing to do")
        return
    if not os.path.isfile(path):
        print(f"seed-watchlist: {path} not found; nothing to do")
        return
    asyncio.run(seed(path))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Reconstruct daily portfolio NAV from the trade ledger + stored bars, to CSV.

Recovery tool for 2026-08-31: the pre-reset archive was taken with
``pg_dump --data-only -t portfolio_nav``, which dumps the empty PARENT of a
TimescaleDB hypertable — 0 rows — and the reset then deleted the real chunks. The
ledger survived intact, so the curves can be rebuilt from it.

Writes CSV. Deliberately NOT into ``portfolio_nav``: those books were reset on
purpose, and re-inserting their old history would put the pre-reset regime back into
the common-window leaderboard and undo the equalization.

    ./scripts/rebuild_nav_from_ledger.py \\
        --ledger ~/.local/state/autonomous-trader/archive/pre-reset-trade_orders.tsv \\
        --cash   ~/.local/state/autonomous-trader/archive/pre-reset-cash_movements.tsv \\
        --out    ~/.local/state/autonomous-trader/archive/pre-reset-nav-rebuilt.csv

APPROXIMATION — state it wherever these numbers are used: positions are marked at
each session's OWN close, while the live job ran at 08:15 UTC and marked at the last
available close (the previous session's). The curve is therefore shifted by roughly
one session against the original, and dividends/splits are not modelled. Totals at
entry and exit dates, and the trade ledger itself, are exact.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import pathlib
import subprocess
import sys
from decimal import Decimal

TRADE_COLS = "id symbol side qty price status reason strategy_version ts portfolio_id commission".split()
CASH_COLS = "id portfolio_id kind amount ts note".split()


def read_tsv(path: pathlib.Path, columns: list[str]) -> list[dict[str, str]]:
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        values = line.split("\t")
        rows.append(dict(zip(columns, values)))
    return rows


def dec(raw: str) -> Decimal:
    return Decimal(raw) if raw not in ("", "\\N") else Decimal(0)


def day_of(raw: str) -> dt.date:
    return dt.date.fromisoformat(raw[:10])


def load_closes(container: str, db: str, user: str) -> dict[tuple[str, dt.date], Decimal]:
    """Every stored daily close, straight from the DB (bars were never touched)."""
    sql = "\\COPY (SELECT symbol, ts::date, close FROM market_bars) TO STDOUT WITH CSV"
    proc = subprocess.run(
        ["docker", "exec", "-i", container, "psql", "-U", user, "-d", db, "-c", sql],
        capture_output=True, text=True, check=True,
    )
    closes: dict[tuple[str, dt.date], Decimal] = {}
    for symbol, day, close in csv.reader(proc.stdout.splitlines()):
        closes[(symbol, dt.date.fromisoformat(day))] = Decimal(close)
    return closes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True, type=pathlib.Path)
    ap.add_argument("--cash", required=True, type=pathlib.Path)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--db-container", default="trader-db")
    ap.add_argument("--db", default="autonomous_trader")
    ap.add_argument("--db-user", default="trader")
    args = ap.parse_args()

    trades = [t for t in read_tsv(args.ledger, TRADE_COLS) if t["status"] == "filled"]
    movements = read_tsv(args.cash, CASH_COLS)
    if not trades:
        print("no filled trades in the ledger", file=sys.stderr)
        return 1
    closes = load_closes(args.db_container, args.db, args.db_user)

    sessions = sorted({day for _, day in closes})
    by_portfolio: dict[int, list[dict]] = collections.defaultdict(list)
    for t in trades:
        by_portfolio[int(t["portfolio_id"])].append(t)
    cash_by_portfolio: dict[int, list[dict]] = collections.defaultdict(list)
    for m in movements:
        cash_by_portfolio[int(m["portfolio_id"])].append(m)

    rows = []
    for pid, fills in sorted(by_portfolio.items()):
        fills.sort(key=lambda t: t["ts"])
        movements_p = sorted(cash_by_portfolio.get(pid, []), key=lambda m: m["ts"])
        first = day_of(min(fills[0]["ts"], movements_p[0]["ts"] if movements_p else fills[0]["ts"]))
        last = day_of(fills[-1]["ts"])
        window = [d for d in sessions if first <= d <= last]

        qty: dict[str, Decimal] = collections.defaultdict(Decimal)
        cash = Decimal(0)
        fi = mi = 0
        last_close: dict[str, Decimal] = {}
        for day in window:
            while mi < len(movements_p) and day_of(movements_p[mi]["ts"]) <= day:
                m = movements_p[mi]
                amount = dec(m["amount"])
                cash += amount if m["kind"] == "deposit" else -amount
                mi += 1
            while fi < len(fills) and day_of(fills[fi]["ts"]) <= day:
                f = fills[fi]
                notional = dec(f["qty"]) * dec(f["price"])
                if f["side"] == "buy":
                    qty[f["symbol"]] += dec(f["qty"])
                    cash -= notional
                else:
                    qty[f["symbol"]] -= dec(f["qty"])
                    cash += notional
                cash -= dec(f["commission"])
                fi += 1

            equity = Decimal(0)
            for symbol, held in qty.items():
                if held == 0:
                    continue
                price = closes.get((symbol, day)) or last_close.get(symbol)
                if price is None:
                    continue
                last_close[symbol] = price
                equity += held * price
            rows.append(
                {
                    "portfolio_id": pid,
                    "day": day.isoformat(),
                    "cash": f"{cash:.6f}",
                    "equity": f"{equity:.6f}",
                    "total": f"{cash + equity:.6f}",
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["portfolio_id", "day", "cash", "equity", "total"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"rebuilt {len(rows)} NAV rows for {len(by_portfolio)} portfolios -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

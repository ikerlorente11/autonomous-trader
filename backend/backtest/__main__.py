"""CLI: backtest one or more strategy versions over stored history.

    docker run --rm -v "$PWD":/app -w /app -e PYTHONPATH=/app \
      --network docker_default --env-file .env docker-api:latest \
      python -m backend.backtest --labels v1,v3,v4,v5,v6 \
      --start 2024-09-01 --end 2026-06-11 --cash 100000 [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json

from backend.analysis.config import load_strategy_config
from backend.backtest.data import load_backtest_data
from backend.backtest.runner import Backtester, BacktestParams


def _fmt_pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:+7.2f}%"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", default="v1,v3,v4,v5,v6")
    parser.add_argument("--start", type=dt.date.fromisoformat, required=True)
    parser.add_argument("--end", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--cash", type=float, default=100_000.0)
    parser.add_argument("--json", dest="json_out", default=None)
    args = parser.parse_args()

    frames, macro, fundamentals = await load_backtest_data(args.start, args.end)
    print(f"universe: {len(frames)} symbols | macro series: {sorted(macro)} | "
          f"fundamentals: {len(fundamentals)} symbols", flush=True)

    params = BacktestParams(start=args.start, end=args.end, starting_cash=args.cash)
    rows = []
    for label in [s.strip() for s in args.labels.split(",") if s.strip()]:
        config = load_strategy_config(label=label)
        result = Backtester(
            frames, config, label, params, macro=macro, fundamentals=fundamentals
        ).run()
        rows.append(result)
        print(f"{label}: done ({len(result.trades)} trades)", flush=True)

    header = (
        f"{'ver':<5} {'return':>9} {'CAGR':>9} {'sharpe':>7} {'maxDD':>9} "
        f"{'trades':>7} {'stops':>6} {'win%':>6} {'SPY':>9} {'alpha':>9}"
    )
    print("\n" + header)
    print("-" * len(header))
    payload = []
    for r in rows:
        win = f"{r.win_rate * 100:5.1f}" if r.win_rate is not None else "    -"
        alpha = (
            r.total_return - r.benchmark_return if r.benchmark_return is not None else None
        )
        print(
            f"{r.label:<5} {_fmt_pct(r.total_return):>9} {_fmt_pct(r.cagr):>9} "
            f"{r.sharpe:7.2f} {_fmt_pct(r.max_drawdown):>9} {len(r.trades):>7} "
            f"{r.stop_outs:>6} {win:>6} {_fmt_pct(r.benchmark_return):>9} {_fmt_pct(alpha):>9}"
        )
        payload.append(
            {
                "label": r.label,
                "total_return": r.total_return,
                "cagr": r.cagr,
                "sharpe": r.sharpe,
                "max_drawdown": r.max_drawdown,
                "trades": len(r.trades),
                "stop_outs": r.stop_outs,
                "win_rate": r.win_rate,
                "benchmark_return": r.benchmark_return,
                "nav": {d.strftime("%Y-%m-%d"): v for d, v in r.nav.items()},
            }
        )
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(payload, fh)
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    asyncio.run(main())

"""v11 calibration sweep — the pre-registered protocol of 10-plan-momentum-mensual §4.

Runs the 8 allowed combos (N x lookback x sizing) over one window and prints the
selection metrics (§4.3): Sharpe, maxDD, turnover (sold notional / avg NAV / years)
and months-with-signal-trades. The OOS window accepts a single --combo (the winner)
and is meant to be run ONCE.

    docker run --rm -v "$PWD":/app -w /app -e PYTHONPATH=/app \
      --network docker_default --env-file .env docker-api:latest \
      python scripts/backtest_sweep_v11.py --window c1 [--json out.json]
    ... --window oos --combo n8_l231_ew
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json

from backend.analysis.config import StrategyConfig, load_strategy_config
from backend.backtest.data import load_backtest_data
from backend.backtest.runner import Backtester, BacktestParams, BacktestResult

# §4.1 — fixed, disjoint windows. OOS is single-pass, winner only.
WINDOWS = {
    "c1": (dt.date(2024, 6, 3), dt.date(2025, 5, 30)),
    "oos": (dt.date(2025, 6, 2), dt.date(2025, 12, 31)),
    "c2": (dt.date(2026, 1, 2), dt.date(2026, 7, 31)),
}

# §4.2 — the whole permitted sweep; widening it after seeing results breaks the protocol.
_N_AXIS = {5: 92.0, 8: 87.0}  # top-N -> min_score_to_act percentile
_LOOKBACK_AXIS = (126, 231)
_SIZING_AXIS = {"ew": None, "vt": 0.004}


def _combos() -> dict[str, StrategyConfig]:
    base = load_strategy_config(label="v11")
    out: dict[str, StrategyConfig] = {}
    for n, act in _N_AXIS.items():
        for lookback in _LOOKBACK_AXIS:
            for sizing, vol_target in _SIZING_AXIS.items():
                assert base.indicators.momentum is not None
                cfg = base.model_copy(
                    update={
                        "ranker": base.ranker.model_copy(
                            update={"min_score_to_act": act}
                        ),
                        "indicators": base.indicators.model_copy(
                            update={
                                "momentum": base.indicators.momentum.model_copy(
                                    update={"period": lookback}
                                )
                            }
                        ),
                        "trading": base.trading.model_copy(
                            update={
                                "max_open_positions": n,
                                "max_position_pct": round(0.95 / n, 4),
                                "vol_target_pct": vol_target,
                            }
                        ),
                    }
                )
                out[f"n{n}_l{lookback}_{sizing}"] = cfg
    return out


def _selection_metrics(r: BacktestResult, start: dt.date, end: dt.date) -> dict:
    sold = sum(t.qty * t.price for t in r.trades if t.side == "sell")
    avg_nav = float(r.nav.mean()) if len(r.nav) else float("nan")
    years = (end - start).days / 365.25
    turnover = sold / avg_nav / years if avg_nav and years else float("nan")
    signal_months = {
        (t.day.year, t.day.month) for t in r.trades if "signal" in t.reason
    }
    return {
        "total_return": r.total_return,
        "benchmark_return": r.benchmark_return,
        "sharpe": r.sharpe,
        "max_drawdown": r.max_drawdown,
        "trades": len(r.trades),
        "stop_outs": r.stop_outs,
        "win_rate": r.win_rate,
        "turnover_per_year": turnover,
        "signal_months": len(signal_months),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=sorted(WINDOWS), required=True)
    parser.add_argument("--combo", default=None, help="run only this combo (OOS)")
    parser.add_argument("--cash", type=float, default=100_000.0)
    parser.add_argument("--json", dest="json_out", default=None)
    args = parser.parse_args()

    start, end = WINDOWS[args.window]
    combos = _combos()
    if args.combo:
        combos = {args.combo: combos[args.combo]}

    frames, macro, fundamentals = await load_backtest_data(start, end)
    print(f"window {args.window}: {start} -> {end} | universe: {len(frames)}", flush=True)

    params = BacktestParams(start=start, end=end, starting_cash=args.cash)
    rows: dict[str, dict] = {}
    for name, cfg in combos.items():
        result = Backtester(
            frames, cfg, name, params, macro=macro, fundamentals=fundamentals
        ).run()
        rows[name] = _selection_metrics(result, start, end)
        print(f"{name}: done ({rows[name]['trades']} trades)", flush=True)

    header = (
        f"{'combo':<14} {'return':>8} {'SPY':>8} {'sharpe':>7} {'maxDD':>8} "
        f"{'turn/yr':>8} {'sigM':>5} {'trades':>7} {'stops':>6}"
    )
    print("\n" + header)
    print("-" * len(header))
    for name, m in rows.items():
        print(
            f"{name:<14} {m['total_return'] * 100:+7.2f}% "
            f"{(m['benchmark_return'] or 0) * 100:+7.2f}% {m['sharpe']:7.2f} "
            f"{m['max_drawdown'] * 100:+7.2f}% {m['turnover_per_year']:8.2f} "
            f"{m['signal_months']:>5} {m['trades']:>7} {m['stop_outs']:>6}"
        )
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump({"window": args.window, "results": rows}, fh, indent=1)
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    asyncio.run(main())

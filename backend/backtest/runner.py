"""Backtester — replay the LIVE pipeline over stored history, one day at a time.

Purpose: compare strategy versions in minutes instead of one live session per day.
It reuses the real building blocks — ``DefaultAnalysisEngine.score_universe`` (same
indicators, rank-normalization, regime multiplier), ``FixedFractionalRiskManager``
(same sizing), ``stops.evaluate_trailing_stop`` maths and the same env knobs for
slippage/commissions — so a version's backtest is the same code path its live
portfolio runs, fed by the same DB tables.

Mechanics per trading day d (mirroring the live schedule):
  1. signals are computed on bars THROUGH d-1 (live: 06:30 fetch has only d-1),
     with fundamentals lagged ``fundamentals_lag_days`` and the macro regime as-of d-1;
  2. exits then sized entries fill at d's OPEN ± slippage (+ commission) — slightly
     more honest than the live paper fill at d-1's close;
  3. the intraday trailing stop is approximated with d's high/low: trigger when
     low_d <= peak - distance using the PRIOR peak (no same-day look-ahead), fill at
     the stop level (or the open if it gapped through), then ratchet peak to high_d;
  4. NAV marks at d's close.

Float maths throughout (not Decimal): a simulation for ranking versions, not a
ledger. Differences vs live are documented above and identical for every version,
so comparisons stay fair.
"""

from __future__ import annotations

import datetime as dt
import math
import os
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from backend.analysis.config import StrategyConfig
from backend.analysis.engine import DefaultAnalysisEngine
from backend.analysis.indicators.volatility import AverageTrueRangeIndicator
from backend.analysis.signals.fundamental.signals import compute_fundamental_signals
from backend.analysis.signals.macro.regime import (
    classify_regime,
    credit_series_id,
    curve_series_id,
    vix_series_id,
)
from backend.contracts import RankedSymbol, SignalAction
from backend.trading.risk_manager import FixedFractionalRiskManager
from backend.trading.stops import stop_distance

_ATR_PERIOD = 14
# Mirror the live analysis window: 400 calendar days of bars feed each day's scores.
_SLICE_BARS = 280


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


@dataclass
class BacktestParams:
    start: dt.date
    end: dt.date
    starting_cash: float = 100_000.0
    slippage_pct: float = field(default_factory=lambda: _float_env("SLIPPAGE_PCT", 0.001))
    commission_pct: float = field(default_factory=lambda: _float_env("COMMISSION_PCT", 0.0))
    commission_per_order: float = field(
        default_factory=lambda: _float_env("COMMISSION_PER_ORDER", 0.0)
    )
    trailing_stop_pct: float = field(
        default_factory=lambda: _float_env("TRAILING_STOP_PCT", 0.08)
    )
    stop_atr_multiple: float = field(
        default_factory=lambda: _float_env("STOP_ATR_MULTIPLE", 2.5)
    )
    vix_tighten_above: float = field(default_factory=lambda: _float_env("VIX_TIGHTEN_ABOVE", 30.0))
    vix_panic_above: float = field(default_factory=lambda: _float_env("VIX_PANIC_ABOVE", 40.0))
    stop_tighten_factor: float = field(
        default_factory=lambda: _float_env("STOP_TIGHTEN_FACTOR", 0.6)
    )
    fundamentals_lag_days: int = 45
    benchmark: str = "SPY"


@dataclass
class _Position:
    qty: float = 0.0
    avg_cost: float = 0.0
    high_water_mark: float | None = None


@dataclass
class Trade:
    day: dt.date
    symbol: str
    side: str
    qty: float
    price: float
    reason: str


@dataclass
class BacktestResult:
    label: str
    nav: pd.Series  # indexed by date, close-of-day total
    trades: list[Trade]
    stop_outs: int
    benchmark_return: float | None

    @property
    def total_return(self) -> float:
        return float(self.nav.iloc[-1] / self.nav.iloc[0] - 1.0)

    @property
    def cagr(self) -> float:
        days = (self.nav.index[-1] - self.nav.index[0]).days or 1
        return float((self.nav.iloc[-1] / self.nav.iloc[0]) ** (365.25 / days) - 1.0)

    @property
    def sharpe(self) -> float:
        rets = self.nav.pct_change().dropna()
        if rets.empty or rets.std() == 0:
            return 0.0
        rf_daily = _float_env("RISK_FREE_RATE", 0.045) / 252.0
        return float((rets.mean() - rf_daily) / rets.std() * math.sqrt(252.0))

    @property
    def max_drawdown(self) -> float:
        peak = self.nav.cummax()
        return float(((self.nav - peak) / peak).min())

    @property
    def win_rate(self) -> float | None:
        """Share of round trips closed above entry (FIFO over full-position exits)."""
        open_cost: dict[str, list[tuple[float, float]]] = {}
        wins = total = 0
        for t in self.trades:
            lots = open_cost.setdefault(t.symbol, [])
            if t.side == "buy":
                lots.append((t.qty, t.price))
                continue
            remaining = t.qty
            cost = 0.0
            matched = 0.0
            while remaining > 1e-12 and lots:
                lot_qty, lot_price = lots[0]
                take = min(lot_qty, remaining)
                cost += take * lot_price
                matched += take
                remaining -= take
                if take >= lot_qty - 1e-12:
                    lots.pop(0)
                else:
                    lots[0] = (lot_qty - take, lot_price)
            if matched > 0:
                total += 1
                if t.price * matched > cost:
                    wins += 1
        return wins / total if total else None


def _asof_value(series: pd.Series, day: dt.date) -> float | None:
    """Last value at/before ``day`` (series indexed by date, sorted)."""
    sliced = series.loc[:day]
    return float(sliced.iloc[-1]) if len(sliced) else None


class Backtester:
    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        config: StrategyConfig,
        label: str,
        params: BacktestParams,
        macro: dict[str, pd.Series] | None = None,
        fundamentals: dict[str, list[tuple[dt.date, dict]]] | None = None,
    ) -> None:
        self._frames = frames
        self._config = config
        self._label = label
        self._params = params
        self._macro = macro or {}
        self._fundamentals = fundamentals or {}
        self._engine = DefaultAnalysisEngine(config)
        # Raw ATR series per symbol, precomputed once (sensitivity unused for raw).
        atr_ind = AverageTrueRangeIndicator(period=_ATR_PERIOD, sensitivity=1.0)
        self._atr: dict[str, pd.Series] = {
            sym: atr_ind.compute(df) for sym, df in frames.items()
        }

    # ---- per-day inputs -------------------------------------------------------

    def _regime_score(self, day: dt.date) -> float | None:
        if not self._macro:
            return None
        curve = self._macro.get(curve_series_id())
        vix = self._macro.get(vix_series_id())
        credit = self._macro.get(credit_series_id())
        result = classify_regime(
            _asof_value(curve, day) if curve is not None else None,
            _asof_value(vix, day) if vix is not None else None,
            _asof_value(credit, day) if credit is not None else None,
        )
        return result.score

    def _extras(self, day: dt.date) -> dict[str, dict[str, float]]:
        if not self._fundamentals:
            return {}
        available_until = day - dt.timedelta(days=self._params.fundamentals_lag_days)
        out: dict[str, dict[str, float]] = {}
        for symbol, quarters in self._fundamentals.items():
            usable = [items for period_end, items in quarters if period_end <= available_until]
            if not usable:
                continue
            scores = compute_fundamental_signals(usable[-8:])
            if scores:
                out[symbol] = scores
        return out

    def _vix_factor(self, day: dt.date) -> tuple[float, bool]:
        vix_series = self._macro.get(vix_series_id())
        vix = _asof_value(vix_series, day) if vix_series is not None else None
        if vix is None:
            return 1.0, False
        if vix > self._params.vix_panic_above:
            return self._params.stop_tighten_factor, True
        if vix > self._params.vix_tighten_above:
            return self._params.stop_tighten_factor, False
        return 1.0, False

    # ---- simulation -----------------------------------------------------------

    def run(self) -> BacktestResult:
        p = self._params
        trading = self._config.trading
        allow_pyramiding = True if trading.allow_pyramiding is None else trading.allow_pyramiding
        cooldown_days = trading.stop_reentry_cooldown_days or 0
        min_dist = float(trading.stop_min_distance_pct or 0.0)
        atr_mult = (
            float(trading.stop_atr_multiple)
            if trading.stop_atr_multiple is not None
            else p.stop_atr_multiple
        )

        all_days = sorted(
            {d.date() if hasattr(d, "date") else d for df in self._frames.values() for d in df.index}
        )
        days = [d for d in all_days if p.start <= d <= p.end]

        cash = p.starting_cash
        positions: dict[str, _Position] = {}
        last_sell: dict[str, dt.date] = {}
        trades: list[Trade] = []
        stop_outs = 0
        nav_index: list[dt.date] = []
        nav_values: list[float] = []

        # date -> integer position per symbol for fast slicing
        date_pos = {
            sym: {(ts.date() if hasattr(ts, "date") else ts): i for i, ts in enumerate(df.index)}
            for sym, df in self._frames.items()
        }

        for day in days:
            # --- 1. signals from data through the previous bar --------------------
            slices: dict[str, pd.DataFrame] = {}
            day_rows: dict[str, pd.Series] = {}
            for sym, df in self._frames.items():
                pos_idx = date_pos[sym].get(day)
                if pos_idx is None or pos_idx == 0:
                    continue
                day_rows[sym] = df.iloc[pos_idx]
                lo = max(0, pos_idx - _SLICE_BARS)
                slices[sym] = df.iloc[lo:pos_idx]
            if not slices:
                continue
            prev_day = day - dt.timedelta(days=1)
            asof = dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc)
            _, scores = self._engine.score_universe(
                slices,
                asof,
                extra_signals=self._extras(prev_day),
                regime_score=self._regime_score(prev_day),
            )
            scores.sort(key=lambda s: s.score, reverse=True)
            ranked = [RankedSymbol(rank=i + 1, score=s) for i, s in enumerate(scores)]

            open_count_before = sum(1 for pos in positions.values() if pos.qty > 0)

            # --- 2a. exits at the open --------------------------------------------
            for sig in ranked:
                sym = sig.score.symbol
                pos = positions.get(sym)
                if sig.score.action is not SignalAction.SELL or pos is None or pos.qty <= 0:
                    continue
                if sym not in day_rows:
                    continue
                fill = float(day_rows[sym]["open"]) * (1.0 - p.slippage_pct)
                proceeds = pos.qty * fill
                commission = proceeds * p.commission_pct + p.commission_per_order
                cash += proceeds - commission
                trades.append(Trade(day, sym, "sell", pos.qty, fill, "signal exit"))
                last_sell[sym] = day
                pos.qty = 0.0
                pos.high_water_mark = None

            # --- 2b. entries at the open ------------------------------------------
            buys = [s for s in ranked if s.score.action is SignalAction.BUY]
            if not allow_pyramiding:
                buys = [
                    s for s in buys
                    if positions.get(s.score.symbol) is None
                    or positions[s.score.symbol].qty <= 0
                ]
            if cooldown_days:
                buys = [
                    s for s in buys
                    if s.score.symbol not in last_sell
                    or (day - last_sell[s.score.symbol]).days > cooldown_days
                ]
            if trading.max_trades_per_day:
                # One execution pass per day here, so the budget is a plain slice by
                # rank (m3's live cap counts fills across the day's interval runs).
                buys = sorted(buys, key=lambda s: s.rank)[: trading.max_trades_per_day]
            if buys:
                # Live sizes against the latest stored close (d-1) and fills at the
                # broker's price; here sizing uses d-1 close and fills at d's open.
                prices = {
                    s.score.symbol: Decimal(str(float(slices[s.score.symbol]["close"].iloc[-1])))
                    for s in buys
                    if s.score.symbol in slices and len(slices[s.score.symbol])
                }
                equity = sum(
                    pos.qty * float(day_rows[sym]["open"])
                    for sym, pos in positions.items()
                    if pos.qty > 0 and sym in day_rows
                )
                vol_kwargs: dict = {}
                if trading.vol_target_pct is not None:
                    # Prior-day raw ATR per candidate — the same series the stop uses,
                    # mirroring the live _frame_atr_map wiring.
                    atr_by_symbol: dict[str, Decimal] = {}
                    for s in buys:
                        sym = s.score.symbol
                        atr_series = self._atr.get(sym)
                        pos_idx = date_pos[sym].get(day) if sym in date_pos else None
                        if atr_series is None or not pos_idx:
                            continue
                        prior = atr_series.iloc[pos_idx - 1]
                        if not pd.isna(prior):
                            atr_by_symbol[sym] = Decimal(str(float(prior)))
                    vol_kwargs = {
                        "vol_target_pct": Decimal(str(trading.vol_target_pct)),
                        "atr_by_symbol": atr_by_symbol,
                        "stop_atr_multiple": Decimal(str(atr_mult)),
                    }
                risk = FixedFractionalRiskManager(
                    prices, open_position_count=open_count_before, **vol_kwargs
                )
                from backend.contracts import AccountBalance  # local import: tiny dataclass

                balance = AccountBalance(
                    cash=Decimal(str(round(cash, 6))),
                    equity=Decimal(str(round(equity, 6))),
                    total=Decimal(str(round(cash + equity, 6))),
                )
                sizes = risk.size_positions(buys, balance)
                for sym, qty_dec in sizes.items():
                    if sym not in day_rows:
                        continue
                    qty = float(qty_dec)
                    fill = float(day_rows[sym]["open"]) * (1.0 + p.slippage_pct)
                    cost = qty * fill
                    commission = cost * p.commission_pct + p.commission_per_order
                    if cost + commission > cash:  # broker-side unfunded-buy reject
                        continue
                    cash -= cost + commission
                    pos = positions.setdefault(sym, _Position())
                    if pos.qty <= 0:
                        pos.qty, pos.avg_cost, pos.high_water_mark = qty, fill, None
                    else:
                        total_qty = pos.qty + qty
                        pos.avg_cost = (pos.qty * pos.avg_cost + qty * fill) / total_qty
                        pos.qty = total_qty
                    trades.append(Trade(day, sym, "buy", qty, fill, "signal entry"))

            # --- 3. intraday trailing stop (daily-bar approximation) ---------------
            factor, panic_hold = self._vix_factor(prev_day)
            for sym, pos in positions.items():
                if pos.qty <= 0 or sym not in day_rows:
                    continue
                row = day_rows[sym]
                peak = max(pos.high_water_mark or pos.avg_cost, float(row["open"]))
                atr_series = self._atr.get(sym)
                atr_val = None
                if atr_series is not None:
                    pos_idx = date_pos[sym][day]
                    if pos_idx > 0:
                        prior = atr_series.iloc[pos_idx - 1]
                        atr_val = None if pd.isna(prior) else float(prior)
                distance = float(
                    stop_distance(
                        Decimal(str(peak)),
                        pct=Decimal(str(p.trailing_stop_pct)),
                        atr=Decimal(str(atr_val)) if atr_val is not None else None,
                        atr_multiple=Decimal(str(atr_mult)),
                        distance_factor=Decimal(str(factor)),
                        min_distance_pct=Decimal(str(min_dist)),
                    )
                )
                stop_level = peak - distance
                if float(row["low"]) <= stop_level and not panic_hold:
                    fill = min(stop_level, float(row["open"])) * (1.0 - p.slippage_pct)
                    proceeds = pos.qty * fill
                    commission = proceeds * p.commission_pct + p.commission_per_order
                    cash += proceeds - commission
                    trades.append(Trade(day, sym, "sell", pos.qty, fill, "protective stop"))
                    last_sell[sym] = day
                    stop_outs += 1
                    pos.qty = 0.0
                    pos.high_water_mark = None
                else:
                    pos.high_water_mark = max(peak, float(row["high"]))

            # --- 4. NAV at the close ------------------------------------------------
            equity = sum(
                pos.qty * float(day_rows[sym]["close"])
                for sym, pos in positions.items()
                if pos.qty > 0 and sym in day_rows
            )
            nav_index.append(day)
            nav_values.append(cash + equity)

        nav = pd.Series(nav_values, index=pd.to_datetime(nav_index), dtype="float64")
        benchmark_return = self._benchmark_return(days)
        return BacktestResult(
            label=self._label,
            nav=nav,
            trades=trades,
            stop_outs=stop_outs,
            benchmark_return=benchmark_return,
        )

    def _benchmark_return(self, days: list[dt.date]) -> float | None:
        df = self._frames.get(self._params.benchmark)
        if df is None or not days:
            return None
        # Copy before re-indexing: pandas caches column Series on the frame, so
        # mutating the view's index would corrupt the shared frame for later runs.
        closes = df["close"].copy()
        closes.index = [ts.date() if hasattr(ts, "date") else ts for ts in df.index]
        first = _asof_value(closes, days[0])
        last = _asof_value(closes, days[-1])
        if not first or not last:
            return None
        return last / first - 1.0

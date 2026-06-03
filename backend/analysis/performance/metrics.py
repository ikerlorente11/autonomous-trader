"""Pure performance-metric computation for the paper-trading simulation.

Every public function is side-effect free: it accepts a DataFrame (and scalar
config), reads nothing external, writes nothing, and returns typed numeric
results. The DB/query layer materializes the DataFrames; this module only does
math. Metric names mirror the keys in docs/finance/reporting-structure.md so the
FP&A reporting layer and Experiment Tracker need no remapping.

Two input shapes recur:
- NAV frame  : columns ``ts`` (datetime), ``total`` (float), optional
  ``benchmark_value`` (float). One row per trading day. Authoritative for all
  return/risk metrics (closed sim, single funding event -> NAV is time-weighted).
- Trips frame: closed round trips with column ``pnl`` (realized currency P&L),
  plus optional ``symbol``/``holding_days`` for grouped metrics. Build it from
  the append-only ``trade_orders`` log via :func:`build_round_trips`.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = 0.045  # annual; overridable via RISK_FREE_RATE env var

FPA_PERIODS = ("wtd", "mtd", "ytd", "inception")
UNCLASSIFIED_SECTOR = "Unclassified"
_PNL_EPSILON = 1e-9  # below this a P&L sum is "flat" → contribution % is undefined


def risk_free_rate_from_env() -> float:
    """Resolve the annual risk-free rate from the environment.

    Kept separate from the metric functions so those stay pure; callers read the
    env once and pass the float in.
    """
    raw = os.environ.get("RISK_FREE_RATE")
    if raw is None or raw.strip() == "":
        return DEFAULT_RISK_FREE_RATE
    return float(raw)


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
class TotalReturn(NamedTuple):
    absolute: float
    pct: float


class DrawdownResult(NamedTuple):
    max_drawdown: float  # negative fraction, e.g. -0.18
    peak_ts: pd.Timestamp | None
    trough_ts: pd.Timestamp | None
    recovery_ts: pd.Timestamp | None  # None if not yet recovered
    drawdown_days: int | None  # peak -> trough
    recovery_days: int | None  # trough -> recovery (None if unrecovered)


class WinLossStats(NamedTuple):
    avg_win: float
    avg_loss: float  # negative
    win_loss_ratio: float  # avg_win / |avg_loss|
    win_count: int
    loss_count: int


class AlphaBeta(NamedTuple):
    alpha: float  # annualized Jensen's alpha
    beta: float


class SignalAccuracy(NamedTuple):
    accuracy: float  # fraction of actionable signals that were correct
    signal_count: int
    correct_count: int


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _nav_series(nav: pd.DataFrame, column: str = "total") -> pd.Series:
    """Ordered float NAV series indexed by ts. Drops NaNs."""
    if column not in nav.columns:
        return pd.Series(dtype="float64")
    values = pd.to_numeric(nav[column], errors="coerce").astype("float64")
    if "ts" in nav.columns:
        values.index = pd.to_datetime(nav["ts"])
        values = values.sort_index()
    return values.dropna()


def daily_returns(nav: pd.DataFrame, column: str = "total") -> pd.Series:
    """Simple daily returns of the NAV (or benchmark) series."""
    s = _nav_series(nav, column)
    if len(s) < 2:
        return pd.Series(dtype="float64")
    return s.pct_change().dropna()


def _years_elapsed(s: pd.Series) -> float:
    if isinstance(s.index, pd.DatetimeIndex) and len(s) >= 2:
        days = (s.index[-1] - s.index[0]).days
        if days > 0:
            return days / 365.25
    # Fallback: trading-day count when no usable timestamps.
    return max(len(s) - 1, 0) / TRADING_DAYS_PER_YEAR


# --------------------------------------------------------------------------- #
# 1. Portfolio performance metrics (NAV-based)
# --------------------------------------------------------------------------- #
def total_return(nav: pd.DataFrame, column: str = "total") -> TotalReturn:
    s = _nav_series(nav, column)
    if len(s) < 2 or s.iloc[0] == 0:
        return TotalReturn(absolute=0.0, pct=float("nan"))
    absolute = float(s.iloc[-1] - s.iloc[0])
    pct = float(s.iloc[-1] / s.iloc[0] - 1.0)
    return TotalReturn(absolute=absolute, pct=pct)


def cagr(nav: pd.DataFrame, column: str = "total") -> float:
    s = _nav_series(nav, column)
    if len(s) < 2 or s.iloc[0] <= 0:
        return float("nan")
    years = _years_elapsed(s)
    if years <= 0:
        return float("nan")
    return float((s.iloc[-1] / s.iloc[0]) ** (1.0 / years) - 1.0)


def sharpe_ratio(
    nav: pd.DataFrame,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    r = daily_returns(nav)
    if len(r) < 2:
        return float("nan")
    rf_daily = risk_free_rate / periods_per_year
    excess = r - rf_daily
    sd = excess.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(excess.mean() / sd * np.sqrt(periods_per_year))


def sortino_ratio(
    nav: pd.DataFrame,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> float:
    r = daily_returns(nav)
    if len(r) < 2:
        return float("nan")
    rf_daily = risk_free_rate / periods_per_year
    excess = r - rf_daily
    downside = np.minimum(excess, 0.0)
    downside_dev = np.sqrt(np.mean(np.square(downside)))
    if downside_dev == 0 or np.isnan(downside_dev):
        return float("nan")
    return float(excess.mean() / downside_dev * np.sqrt(periods_per_year))


def max_drawdown(nav: pd.DataFrame, column: str = "total") -> DrawdownResult:
    s = _nav_series(nav, column)
    if len(s) < 2:
        return DrawdownResult(0.0, None, None, None, None, None)
    running_max = s.cummax()
    drawdown = s / running_max - 1.0
    trough_ts = drawdown.idxmin()
    max_dd = float(drawdown.loc[trough_ts])
    if max_dd >= 0.0:
        return DrawdownResult(0.0, None, None, None, None, None)

    pre_trough = s.loc[:trough_ts]
    peak_ts = pre_trough.idxmax()
    peak_value = s.loc[peak_ts]

    post_trough = s.loc[trough_ts:]
    recovered = post_trough[post_trough >= peak_value]
    recovery_ts = recovered.index[0] if len(recovered) else None

    if isinstance(s.index, pd.DatetimeIndex):
        drawdown_days = int((trough_ts - peak_ts).days)
        recovery_days = (
            int((recovery_ts - trough_ts).days) if recovery_ts is not None else None
        )
    else:
        drawdown_days = recovery_days = None

    return DrawdownResult(
        max_drawdown=max_dd,
        peak_ts=peak_ts,
        trough_ts=trough_ts,
        recovery_ts=recovery_ts,
        drawdown_days=drawdown_days,
        recovery_days=recovery_days,
    )


def calmar_ratio(nav: pd.DataFrame, column: str = "total") -> float:
    growth = cagr(nav, column)
    mdd = max_drawdown(nav, column).max_drawdown
    if np.isnan(growth) or mdd == 0.0:
        return float("nan")
    return float(growth / abs(mdd))


def alpha_beta(
    nav: pd.DataFrame,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
    benchmark_column: str = "benchmark_value",
) -> AlphaBeta:
    """Annualized Jensen's alpha and beta of portfolio vs benchmark.

    Both return series are derived from the same NAV frame and aligned on ts.
    """
    rp = daily_returns(nav, "total")
    rb = daily_returns(nav, benchmark_column)
    aligned = pd.concat([rp, rb], axis=1, join="inner").dropna()
    if len(aligned) < 2:
        return AlphaBeta(alpha=float("nan"), beta=float("nan"))
    rp_a = aligned.iloc[:, 0].to_numpy()
    rb_a = aligned.iloc[:, 1].to_numpy()
    rf_daily = risk_free_rate / periods_per_year
    excess_p = rp_a - rf_daily
    excess_b = rb_a - rf_daily
    var_b = np.var(excess_b, ddof=1)
    if var_b == 0 or np.isnan(var_b):
        return AlphaBeta(alpha=float("nan"), beta=float("nan"))
    beta = float(np.cov(excess_p, excess_b, ddof=1)[0, 1] / var_b)
    alpha_daily = float(np.mean(excess_p) - beta * np.mean(excess_b))
    return AlphaBeta(alpha=alpha_daily * periods_per_year, beta=beta)


# --------------------------------------------------------------------------- #
# Trade-level metrics (round-trip based)
# --------------------------------------------------------------------------- #
def build_round_trips(orders: pd.DataFrame) -> pd.DataFrame:
    """FIFO-match the append-only order log into closed round trips.

    Input columns: ``symbol``, ``side`` ('buy'/'sell'), ``qty``, ``price``,
    ``ts`` (and optional ``status`` — only 'filled' rows are used). Long-only:
    sells are matched against open buy lots FIFO; any sell quantity exceeding
    open lots is ignored (no shorting in Phase 1). Returns a frame with columns
    ``symbol``, ``entry_ts``, ``exit_ts``, ``qty``, ``entry_price``,
    ``exit_price``, ``pnl``, ``return_pct``, ``holding_days``. One row per
    closed quantity slice; open positions produce no row.
    """
    cols = ["symbol", "entry_ts", "exit_ts", "qty", "entry_price",
            "exit_price", "pnl", "return_pct", "holding_days"]
    if orders.empty:
        return pd.DataFrame(columns=cols)

    df = orders.copy()
    if "status" in df.columns:
        df = df[df["status"].str.lower() == "filled"]
    df = df.assign(
        ts=pd.to_datetime(df["ts"]),
        side=df["side"].str.lower(),
        qty=pd.to_numeric(df["qty"], errors="coerce").astype("float64"),
        price=pd.to_numeric(df["price"], errors="coerce").astype("float64"),
    ).dropna(subset=["qty", "price"]).sort_values("ts")

    trips: list[dict] = []
    for symbol, grp in df.groupby("symbol", sort=False):
        lots: list[list] = []  # each: [remaining_qty, price, ts]
        for row in grp.itertuples(index=False):
            if row.side == "buy":
                lots.append([row.qty, row.price, row.ts])
                continue
            if row.side != "sell":
                continue
            remaining = row.qty
            while remaining > 1e-9 and lots:
                lot = lots[0]
                matched = min(remaining, lot[0])
                pnl = (row.price - lot[1]) * matched
                trips.append({
                    "symbol": symbol,
                    "entry_ts": lot[2],
                    "exit_ts": row.ts,
                    "qty": matched,
                    "entry_price": lot[1],
                    "exit_price": row.price,
                    "pnl": pnl,
                    "return_pct": (row.price / lot[1] - 1.0) if lot[1] else float("nan"),
                    "holding_days": int((row.ts - lot[2]).days),
                })
                lot[0] -= matched
                remaining -= matched
                if lot[0] <= 1e-9:
                    lots.pop(0)

    return pd.DataFrame(trips, columns=cols)


def win_rate(trips: pd.DataFrame) -> float:
    if trips.empty:
        return float("nan")
    pnl = pd.to_numeric(trips["pnl"], errors="coerce").dropna()
    if pnl.empty:
        return float("nan")
    return float((pnl > 0).sum() / len(pnl))


def profit_factor(trips: pd.DataFrame) -> float:
    if trips.empty:
        return float("nan")
    pnl = pd.to_numeric(trips["pnl"], errors="coerce").dropna()
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = -pnl[pnl < 0].sum()
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else float("nan")
    return float(gross_profit / gross_loss)


def avg_win_loss(trips: pd.DataFrame) -> WinLossStats:
    if trips.empty:
        return WinLossStats(float("nan"), float("nan"), float("nan"), 0, 0)
    pnl = pd.to_numeric(trips["pnl"], errors="coerce").dropna()
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    ratio = float(avg_win / abs(avg_loss)) if avg_loss != 0 else float("nan")
    return WinLossStats(avg_win, avg_loss, ratio, len(wins), len(losses))


# --------------------------------------------------------------------------- #
# 3. FP&A periods & P&L attribution (reporting-structure.md §1.2–1.3)
# --------------------------------------------------------------------------- #
class PeriodPnl(NamedTuple):
    period: str  # one of FPA_PERIODS
    start_ts: pd.Timestamp | None
    end_ts: pd.Timestamp | None
    start_value: float
    end_value: float
    pnl: float
    return_pct: float


class SymbolAttribution(NamedTuple):
    symbol: str
    realized_pnl: float  # FIFO-closed lots exiting inside the period window
    unrealized_pnl: float  # current open-position mark (point-in-time)
    total_pnl: float
    contribution_pct: float  # share of the summed total across symbols


class SectorAttribution(NamedTuple):
    sector: str
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    contribution_pct: float


def _to_naive_utc(ts: dt.datetime | pd.Timestamp) -> pd.Timestamp:
    """Normalize a timestamp to tz-naive UTC so it compares against a naive index."""
    t = pd.Timestamp(ts)
    if t.tz is not None:
        t = t.tz_convert("UTC").tz_localize(None)
    return t


def _naive_utc_index(s: pd.Series) -> pd.Series:
    if isinstance(s.index, pd.DatetimeIndex) and s.index.tz is not None:
        s = s.copy()
        s.index = s.index.tz_convert("UTC").tz_localize(None)
    return s


def period_start(asof: dt.datetime | pd.Timestamp, period: str) -> pd.Timestamp | None:
    """The window-open boundary for a period (tz-naive UTC midnight).

    ``None`` for ``inception`` (the window opens at the first NAV). The baseline NAV
    for a period is the last close *before* this boundary (§1.2: "vs last Friday's
    close" / "vs prior month-end"); realized trips are those exiting at/after it.
    """
    a = _to_naive_utc(asof).normalize()
    if period == "wtd":
        return a - pd.Timedelta(days=int(a.weekday()))  # Monday 00:00
    if period == "mtd":
        return a.replace(day=1)
    if period == "ytd":
        return a.replace(month=1, day=1)
    if period == "inception":
        return None
    raise ValueError(f"unknown period {period!r}; expected one of {FPA_PERIODS}")


def period_pnl(
    nav: pd.DataFrame, period: str, asof: dt.datetime | pd.Timestamp
) -> PeriodPnl:
    """Period P&L from the daily NAV series: ``end − baseline`` / ``end/baseline − 1``.

    Baseline is the last NAV strictly before the period boundary (the prior close);
    if the boundary predates inception it falls back to the first NAV (§1.2 "or
    inception if first year"). Pure: ``asof`` is passed in, never read from a clock.
    """
    s = _naive_utc_index(_nav_series(nav))
    asof_ts = _to_naive_utc(asof)
    s = s[s.index <= asof_ts]
    if s.empty:
        return PeriodPnl(period, None, None, 0.0, 0.0, 0.0, float("nan"))

    end_ts, end_value = s.index[-1], float(s.iloc[-1])
    boundary = period_start(asof_ts, period)
    prior = s[s.index < boundary] if boundary is not None else s.iloc[:0]
    if len(prior):
        start_ts, start_value = prior.index[-1], float(prior.iloc[-1])
    else:
        start_ts, start_value = s.index[0], float(s.iloc[0])  # inception anchor

    pnl = end_value - start_value
    return_pct = (end_value / start_value - 1.0) if start_value != 0 else float("nan")
    return PeriodPnl(period, start_ts, end_ts, start_value, end_value, pnl, return_pct)


def attribution_by_symbol(
    trips: pd.DataFrame,
    unrealized: Mapping[str, float] | None = None,
    *,
    start: dt.datetime | pd.Timestamp | None = None,
    end: dt.datetime | pd.Timestamp | None = None,
) -> list[SymbolAttribution]:
    """Per-symbol P&L = period-realized closed lots + current unrealized mark (§1.3).

    Realized is summed from ``trips`` whose ``exit_ts`` falls in ``[start, end]``
    (``start=None`` → inception). ``unrealized`` is the point-in-time open mark
    ``{symbol: pnl}`` (period-independent by construction). ``contribution_pct`` is
    each symbol's share of the summed total; undefined (NaN) when the total nets flat.
    Sorted best → worst contributor.
    """
    marks = dict(unrealized or {})
    realized: dict[str, float] = {}
    if trips is not None and not trips.empty and "exit_ts" in trips.columns:
        df = trips.copy()
        exit_ts = pd.to_datetime(df["exit_ts"])
        if getattr(exit_ts.dt, "tz", None) is not None:
            exit_ts = exit_ts.dt.tz_convert("UTC").dt.tz_localize(None)
        df = df.assign(exit_ts=exit_ts, pnl=pd.to_numeric(df["pnl"], errors="coerce"))
        if start is not None:
            df = df[df["exit_ts"] >= _to_naive_utc(start)]
        if end is not None:
            df = df[df["exit_ts"] <= _to_naive_utc(end)]
        df = df.dropna(subset=["pnl"])
        if not df.empty:
            realized = df.groupby("symbol")["pnl"].sum().to_dict()

    rows = [
        (sym, float(realized.get(sym, 0.0)), float(marks.get(sym, 0.0)))
        for sym in set(realized) | set(marks)
    ]
    grand = sum(r + u for _, r, u in rows)
    out = [
        SymbolAttribution(
            symbol=sym,
            realized_pnl=r,
            unrealized_pnl=u,
            total_pnl=r + u,
            contribution_pct=(
                (r + u) / grand * 100.0 if abs(grand) > _PNL_EPSILON else float("nan")
            ),
        )
        for sym, r, u in rows
    ]
    out.sort(key=lambda a: a.total_pnl, reverse=True)
    return out


def attribution_by_sector(
    symbol_attr: Sequence[SymbolAttribution],
    sector_map: Mapping[str, str],
) -> list[SectorAttribution]:
    """Roll per-symbol attribution up to sectors via ``{symbol: sector}`` (§1.3).

    Symbols absent from the map (held but un-watchlisted) fall into
    ``UNCLASSIFIED_SECTOR``; sector is joined at read time, never persisted.
    """
    agg: dict[str, list[float]] = {}
    for sa in symbol_attr:
        sector = sector_map.get(sa.symbol) or UNCLASSIFIED_SECTOR
        acc = agg.setdefault(sector, [0.0, 0.0])
        acc[0] += sa.realized_pnl
        acc[1] += sa.unrealized_pnl
    grand = sum(r + u for r, u in agg.values())
    out = [
        SectorAttribution(
            sector=sector,
            realized_pnl=r,
            unrealized_pnl=u,
            total_pnl=r + u,
            contribution_pct=(
                (r + u) / grand * 100.0 if abs(grand) > _PNL_EPSILON else float("nan")
            ),
        )
        for sector, (r, u) in agg.items()
    ]
    out.sort(key=lambda a: a.total_pnl, reverse=True)
    return out


# --------------------------------------------------------------------------- #
# 2. Signal quality metrics
# --------------------------------------------------------------------------- #
def _signal_correctness(df: pd.DataFrame) -> pd.Series:
    """Per-row correctness for settled signals as a nullable boolean Series.

    Prefers the pre-computed ``outcome`` ('correct'/'incorrect'); falls back to
    the sign of ``realized_return`` (a buy is correct when forward return > 0).
    Unsettled rows (neither source available) are <NA> and excluded downstream.
    """
    correct = pd.Series(pd.NA, index=df.index, dtype="object")
    if "outcome" in df.columns:
        oc = df["outcome"].astype("string").str.lower()
        correct = correct.mask(oc == "correct", True).mask(oc == "incorrect", False)
    if "realized_return" in df.columns:
        ret = pd.to_numeric(df["realized_return"], errors="coerce")
        fallback = (ret > 0).where(ret.notna(), pd.NA)
        correct = correct.where(correct.notna(), fallback)
    return correct


def signal_accuracy(
    signals: pd.DataFrame,
    actionable: tuple[str, ...] = ("buy",),
) -> SignalAccuracy:
    """Fraction of settled actionable signals that were correct.

    Input: ``algorithm_signals`` rows with ``action``, ``outcome`` and/or
    ``realized_return``. Unsettled rows (no outcome and no realized_return) are
    excluded.
    """
    if signals.empty:
        return SignalAccuracy(float("nan"), 0, 0)
    df = signals[signals["action"].str.lower().isin(actionable)]
    if df.empty:
        return SignalAccuracy(float("nan"), 0, 0)

    settled = _signal_correctness(df).dropna().astype(bool)
    if settled.empty:
        return SignalAccuracy(float("nan"), 0, 0)
    return SignalAccuracy(
        accuracy=float(settled.mean()),
        signal_count=int(len(settled)),
        correct_count=int(settled.sum()),
    )


def signal_hit_rate_by_sector(
    signals: pd.DataFrame,
    sector_map: dict[str, str],
    actionable: tuple[str, ...] = ("buy",),
) -> pd.Series:
    """Hit rate of settled actionable signals grouped by watchlist sector.

    ``sector_map`` is ``{symbol: sector}`` from the watchlist. Returns a Series
    indexed by sector with the correct-signal fraction; sectors with no settled
    signals are omitted.
    """
    if signals.empty or not sector_map:
        return pd.Series(dtype="float64")
    df = signals[signals["action"].str.lower().isin(actionable)].copy()
    if df.empty:
        return pd.Series(dtype="float64")

    correct = _signal_correctness(df)
    df = df.assign(_correct=correct, _sector=df["symbol"].map(sector_map))
    df = df[correct.notna()].dropna(subset=["_sector"])
    if df.empty:
        return pd.Series(dtype="float64")
    df["_correct"] = df["_correct"].astype(bool)
    return df.groupby("_sector")["_correct"].mean().astype("float64").sort_index()


def avg_holding_period_profitability(
    trips: pd.DataFrame,
    bins: tuple[int, ...] = (0, 5, 10, 20, 60),
) -> pd.DataFrame:
    """Average realized return and P&L bucketed by holding period (trading days).

    Surfaces whether the 1–4 week target horizon (synthesis §0) is where the
    edge actually lives. Returns a frame indexed by holding-period bucket with
    ``trip_count``, ``avg_return_pct``, ``avg_pnl``, ``win_rate``.
    """
    cols = ["trip_count", "avg_return_pct", "avg_pnl", "win_rate"]
    if trips.empty or "holding_days" not in trips.columns:
        return pd.DataFrame(columns=cols)
    df = trips.copy()
    df["holding_days"] = pd.to_numeric(df["holding_days"], errors="coerce")
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    df["return_pct"] = pd.to_numeric(df.get("return_pct"), errors="coerce")
    df = df.dropna(subset=["holding_days", "pnl"])
    if df.empty:
        return pd.DataFrame(columns=cols)

    edges = list(bins) + [float("inf")]
    labels = [f"{edges[i]}-{edges[i + 1]}d" for i in range(len(edges) - 2)]
    labels.append(f">{edges[-2]}d")
    df["_bucket"] = pd.cut(df["holding_days"], bins=edges, labels=labels,
                           right=True, include_lowest=True)
    grouped = df.groupby("_bucket", observed=True)
    out = pd.DataFrame({
        "trip_count": grouped.size(),
        "avg_return_pct": grouped["return_pct"].mean(),
        "avg_pnl": grouped["pnl"].mean(),
        "win_rate": grouped["pnl"].apply(lambda s: float((s > 0).mean())),
    })
    return out[cols]


# --------------------------------------------------------------------------- #
# 4. Performance thresholds (dashboard alert config)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PerformanceThresholds:
    """Good/bad cutoffs for dashboard coloring and health alerts.

    Defaults are starting points to be recalibrated by the Experiment Tracker
    after backtesting; they are not strategy parameters and live here (not in
    strategy.yaml) because they describe *evaluation*, not *behavior*.
    """

    sharpe_good: float = 1.0
    sharpe_warn: float = 0.0
    sortino_good: float = 1.5
    max_drawdown_warn: float = -0.10
    max_drawdown_bad: float = -0.20
    calmar_good: float = 0.5
    win_rate_min: float = 0.45
    profit_factor_good: float = 1.5
    profit_factor_min: float = 1.0
    signal_accuracy_min: float = 0.52
    alpha_good: float = 0.0  # any positive annualized alpha beats the benchmark


def summarize_performance(
    nav: pd.DataFrame,
    trips: pd.DataFrame | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict[str, dict[str, float]]:
    """Bundle the headline metrics into the reporting-structure.md envelope.

    Returns ``{"returns": {...}, "risk": {...}, "trades": {...}}`` with keys
    matching docs/finance/reporting-structure.md so the FP&A layer and
    Experiment Tracker consume them without remapping.
    """
    ab = alpha_beta(nav, risk_free_rate)
    bench = total_return(nav, "benchmark_value")
    returns = {
        "total": total_return(nav).pct,
        "annualized": cagr(nav),
        "benchmark": bench.pct,
        "alpha": ab.alpha,
        "beta": ab.beta,
    }
    risk = {
        "sharpe": sharpe_ratio(nav, risk_free_rate),
        "sortino": sortino_ratio(nav, risk_free_rate),
        "max_drawdown": max_drawdown(nav).max_drawdown,
        "calmar": calmar_ratio(nav),
    }
    trades: dict[str, float] = {}
    if trips is not None and not trips.empty:
        wl = avg_win_loss(trips)
        trades = {
            "win_rate": win_rate(trips),
            "profit_factor": profit_factor(trips),
            "avg_win": wl.avg_win,
            "avg_loss": wl.avg_loss,
            "win_loss_ratio": wl.win_loss_ratio,
        }
    return {"returns": returns, "risk": risk, "trades": trades}

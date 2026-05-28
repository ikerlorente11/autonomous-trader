"""Post-fetch data-quality checks.

Providers normalise *shape*; this layer judges *correctness*. It runs on the
``Mapping[str, list[OHLCVBar]]`` a provider returns, before anything is written to
``market_bars``. Checks are pure (no I/O) so they are cheap and testable; thresholds
are env-driven so nothing is hardcoded.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from backend.contracts import OHLCVBar
from backend.data_ingestion.calendar import trading_days


def _anomaly_threshold() -> Decimal:
    return Decimal(os.environ.get("PRICE_ANOMALY_PCT", "0.50"))


def _stale_max_age_days() -> int:
    return int(os.environ.get("DATA_STALE_MAX_AGE_DAYS", "4"))


@dataclass(frozen=True)
class PriceAnomaly:
    symbol: str
    ts: dt.datetime
    prev_close: Decimal
    close: Decimal
    pct_change: Decimal


@dataclass
class ValidationReport:
    """Per-batch verdict. ``ok`` is False if any hard problem was found."""

    missing_days: dict[str, list[dt.date]] = field(default_factory=dict)
    stale_symbols: dict[str, dt.date | None] = field(default_factory=dict)
    anomalies: list[PriceAnomaly] = field(default_factory=list)
    empty_symbols: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.stale_symbols or self.anomalies or self.empty_symbols)


def detect_missing_days(
    bars: Sequence[OHLCVBar], start: dt.date, end: dt.date
) -> list[dt.date]:
    """Sessions the exchange held in ``[start, end]`` that this symbol is missing."""
    present = {b.ts.date() for b in bars}
    return [d for d in trading_days(start, end) if d not in present]


def detect_stale(bars: Sequence[OHLCVBar], asof: dt.date) -> dt.date | None:
    """Return the last bar date if it is older than the staleness budget, else None."""
    if not bars:
        return None
    last = max(b.ts.date() for b in bars)
    expected = trading_days(asof - dt.timedelta(days=10), asof)
    if not expected:
        return None
    age_sessions = sum(1 for d in expected if d > last)
    return last if age_sessions > _stale_max_age_days() else None


def detect_price_anomalies(symbol: str, bars: Sequence[OHLCVBar]) -> list[PriceAnomaly]:
    """Flag single-session close-to-close moves beyond the configured threshold."""
    threshold = _anomaly_threshold()
    ordered = sorted(bars, key=lambda b: b.ts)
    out: list[PriceAnomaly] = []
    for prev, cur in zip(ordered, ordered[1:]):
        if prev.close == 0:
            continue
        pct = (cur.close - prev.close) / prev.close
        if abs(pct) > threshold:
            out.append(PriceAnomaly(symbol, cur.ts, prev.close, cur.close, pct))
    return out


def validate_batch(
    batch: Mapping[str, Sequence[OHLCVBar]],
    requested: Sequence[str],
    start: dt.date,
    end: dt.date,
    *,
    asof: dt.date | None = None,
) -> ValidationReport:
    """Run every check across a fetched batch and collect the findings."""
    asof = asof or end
    report = ValidationReport()
    for symbol in requested:
        bars = batch.get(symbol, [])
        if not bars:
            report.empty_symbols.append(symbol)
            continue
        missing = detect_missing_days(bars, start, end)
        if missing:
            report.missing_days[symbol] = missing
        stale = detect_stale(bars, asof)
        if stale is not None:
            report.stale_symbols[symbol] = stale
        report.anomalies.extend(detect_price_anomalies(symbol, bars))
    return report

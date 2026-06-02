"""Forward-return settlement of algorithm signals.

A signal predicts a direction; once its evaluation horizon has elapsed we can score it.
This fills ``algorithm_signals.realized_return`` / ``outcome`` so the signal-quality
metrics (``signal_accuracy`` and friends) have settled rows to read. Pure DB-side work:
no network, no scoring logic. Idempotent — a signal is settled once (outcome IS NULL
filter) and re-running settles only the newly-eligible ones. Caller owns the transaction.
"""

from __future__ import annotations

import datetime as dt
import os

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.queries.market_queries import get_close_after, get_close_asof
from backend.db.queries.portfolio_queries import get_unsettled_signals

_DEFAULT_HORIZON_DAYS = 5


def _horizon_days() -> int:
    raw = os.environ.get("SIGNAL_EVAL_HORIZON_DAYS")
    if raw and raw.strip():
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_HORIZON_DAYS


async def settle_due_signals(session: AsyncSession, asof: dt.datetime) -> int:
    """Settle every actionable signal whose horizon has elapsed by ``asof``.

    A buy is correct when the forward return is positive; a sell when it is negative.
    Returns the number of signals settled."""
    horizon = _horizon_days()
    cutoff = asof - dt.timedelta(days=horizon)
    settled = 0
    for sig in await get_unsettled_signals(session, cutoff):
        entry = await get_close_asof(session, sig.symbol, sig.ts)
        exit_bar = await get_close_after(
            session, sig.symbol, sig.ts + dt.timedelta(days=horizon)
        )
        if entry is None or exit_bar is None or entry.close <= 0:
            continue
        ret = exit_bar.close / entry.close - 1
        is_buy = sig.action.lower() == "buy"
        correct = ret > 0 if is_buy else ret < 0
        sig.realized_return = ret
        sig.outcome = "correct" if correct else "incorrect"
        settled += 1
    await session.flush()
    return settled

"""Idempotent persistence of analysis outputs.

The composite scorer is a pure unit; this module is the session-aware layer the
scheduler's ``run_analysis`` job uses to write results. Both writers upsert on the
table's primary key so re-running analysis for the same day overwrites rather than
duplicates (CLAUDE.md: all jobs idempotent). Caller owns the transaction (commit).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.contracts import IndicatorResult, SymbolScore
from backend.db.models import AlgorithmSignal, SignalValue


async def persist_signal_values(
    session: AsyncSession, results: Sequence[IndicatorResult]
) -> int:
    if not results:
        return 0
    rows = [
        {
            "symbol": r.symbol,
            "ts": r.ts,
            "signal_id": r.signal_id,
            "value": r.value,
            "data_completeness": r.data_completeness,
        }
        for r in results
    ]
    stmt = insert(SignalValue).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[SignalValue.symbol, SignalValue.ts, SignalValue.signal_id],
        set_={
            "value": stmt.excluded.value,
            "data_completeness": stmt.excluded.data_completeness,
        },
    )
    await session.execute(stmt)
    return len(rows)


async def persist_algorithm_signals(
    session: AsyncSession, scores: Sequence[SymbolScore], strategy_version: str
) -> int:
    if not scores:
        return 0
    rows = [
        {
            "symbol": s.symbol,
            "ts": s.ts,
            "score": s.score,
            "action": s.action.value,
            "reason": s.reason,
            "indicator_snapshot": s.indicator_snapshot,
            "strategy_version": strategy_version,
        }
        for s in scores
    ]
    stmt = insert(AlgorithmSignal).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[AlgorithmSignal.symbol, AlgorithmSignal.ts],
        set_={
            "score": stmt.excluded.score,
            "action": stmt.excluded.action,
            "reason": stmt.excluded.reason,
            "indicator_snapshot": stmt.excluded.indicator_snapshot,
            "strategy_version": stmt.excluded.strategy_version,
        },
    )
    await session.execute(stmt)
    return len(rows)

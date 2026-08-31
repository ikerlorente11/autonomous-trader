"""Backfill earnings surprises (PEAD raw material) from Alpha Vantage, and validate
the history's point-in-time quality against Finnhub before trusting it.

Resumable one-shot (idempotent upsert; symbols already stored are skipped):
    docker run --rm -v "$PWD":/app -w /app --network docker_default \
      --env-file .env docker-api:latest python scripts/backfill_earnings.py \
      [--since 2023-01-01] [--max-requests 24] [--refresh] [--validate]

The free AV quota is 25 requests/day and one EARNINGS call returns a symbol's full
history, so a 62-symbol watchlist backfills over ~3 daily runs. Needs
ALPHA_VANTAGE_API_KEY in .env; degrades to a clean skip without it.

--validate is the doc 13 §3.1 vintage gate, PART OF THE BACKFILL, not optional:
AV's estimatedEPS has no contractual point-in-time guarantee, so stored rows are
cross-checked against Finnhub's last 4 quarters (estimate + actual). Proposed
acceptance (doc 13 handoff): <5% of overlapping quarters with |Δestimate| > $0.01.
If it fails, PEAD is NO-GO and only the insider signal proceeds.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import sys
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.db.models import EarningsEvent
from backend.db.queries.portfolio_queries import get_active_watchlist
from backend.db.session import async_session

_AV_URL = "https://www.alphavantage.co/query"
_FINNHUB_URL = "https://finnhub.io/api/v1/stock/earnings"
_UTC = dt.timezone.utc
# 5 req/min on the free tier; a fixed pause keeps the one-shot well under it.
_AV_PAUSE_S = 15.0
_SESSION_MAP = {"pre-market": "bmo", "post-market": "amc"}


def _decimal(raw: object) -> Decimal | None:
    if raw in (None, "", "None"):
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def _available_ts(announce: dt.date, session: str) -> dt.datetime:
    # bmo -> tradable that session; amc/unknown -> conservatively the next day.
    # Signals compare against session dates, so midnight UTC of the day suffices.
    day = announce if session == "bmo" else announce + dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time.min, tzinfo=_UTC)


def _rows_from_av(symbol: str, payload: dict, since: dt.date) -> list[dict]:
    rows = []
    for q in payload.get("quarterlyEarnings", []):
        try:
            fiscal_end = dt.date.fromisoformat(q["fiscalDateEnding"])
            announce = dt.date.fromisoformat(q["reportedDate"])
        except (KeyError, ValueError):
            continue
        if announce < since:
            continue
        actual = _decimal(q.get("reportedEPS"))
        if actual is None:  # not-yet-reported placeholder rows
            continue
        session = _SESSION_MAP.get((q.get("reportTime") or "").strip(), "unknown")
        rows.append({
            "symbol": symbol,
            "fiscal_period_end": fiscal_end,
            "announce_date": announce,
            "announce_session": session,
            "available_ts": _available_ts(announce, session),
            "eps_estimate": _decimal(q.get("estimatedEPS")),
            "eps_actual": actual,
            "surprise_pct": _decimal(q.get("surprisePercentage")),
            "source": "alpha_vantage",
        })
    return rows


async def _upsert(rows: list[dict]) -> None:
    stmt = pg_insert(EarningsEvent).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "fiscal_period_end"],
        set_={c: stmt.excluded[c] for c in rows[0] if c not in ("symbol", "fiscal_period_end")},
    )
    async with async_session() as session:
        await session.execute(stmt)
        await session.commit()


async def _stored_symbols() -> set[str]:
    async with async_session() as session:
        result = await session.execute(select(EarningsEvent.symbol).distinct())
        return {row[0] for row in result}


async def backfill(since: dt.date, max_requests: int, refresh: bool) -> None:
    key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    if not key:
        print("ALPHA_VANTAGE_API_KEY not set — skipping backfill cleanly", flush=True)
        return
    async with async_session() as session:
        watchlist = await get_active_watchlist(session)
    pending = sorted(w.symbol for w in watchlist)
    if not refresh:
        done = await _stored_symbols()
        pending = [s for s in pending if s not in done]
    if not pending:
        print("all watchlist symbols already stored — nothing to do", flush=True)
        return

    used = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        for symbol in pending:
            if used >= max_requests:
                print(f"request budget ({max_requests}) reached — rerun tomorrow; "
                      f"{len(pending) - used} symbols left", flush=True)
                break
            resp = await client.get(
                _AV_URL, params={"function": "EARNINGS", "symbol": symbol, "apikey": key}
            )
            resp.raise_for_status()
            payload = resp.json()
            used += 1
            # AV signals throttling/errors in-band, with 200s.
            note = payload.get("Note") or payload.get("Information") or payload.get("Error Message")
            if note and "quarterlyEarnings" not in payload:
                print(f"{symbol}: AV said: {note} — stopping", flush=True)
                break
            rows = _rows_from_av(symbol, payload, since)
            if rows:
                await _upsert(rows)
            print(f"{symbol}: {len(rows)} quarters", flush=True)
            await asyncio.sleep(_AV_PAUSE_S)
    print(f"done: {used} requests used", flush=True)


async def validate() -> None:
    """AV↔Finnhub vintage cross-check over Finnhub's 4-quarter overlap window."""
    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not key:
        print("FINNHUB_API_KEY not set — cannot validate", flush=True)
        return
    async with async_session() as session:
        result = await session.execute(select(EarningsEvent))
        stored = {(e.symbol, e.fiscal_period_end): e for e in result.scalars()}
    symbols = sorted({s for s, _ in stored})
    if not symbols:
        print("no stored earnings_events — run the backfill first", flush=True)
        return

    overlaps = discrepancies = 0
    details: list[str] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for symbol in symbols:
            resp = await client.get(
                _FINNHUB_URL, params={"symbol": symbol, "token": key}
            )
            if resp.status_code != 200:
                print(f"{symbol}: finnhub {resp.status_code} — skipped", flush=True)
                continue
            for q in resp.json() or []:
                try:
                    period = dt.date.fromisoformat(q["period"])
                except (KeyError, TypeError, ValueError):
                    continue
                event = stored.get((symbol, period))
                if event is None:
                    continue
                overlaps += 1
                for field, ours, theirs in (
                    ("estimate", event.eps_estimate, _decimal(q.get("estimate"))),
                    ("actual", event.eps_actual, _decimal(q.get("actual"))),
                ):
                    if ours is None or theirs is None:
                        continue
                    if abs(ours - theirs) > Decimal("0.01"):
                        discrepancies += 1
                        details.append(
                            f"  {symbol} {period} {field}: av={ours} finnhub={theirs}"
                        )
                        break
            await asyncio.sleep(1.1)  # stay far under 60/min

    pct = 100.0 * discrepancies / overlaps if overlaps else float("nan")
    verdict = "PASS" if overlaps and pct < 5.0 else "FAIL"
    print(f"\nvintage check: {overlaps} overlapping quarters, "
          f"{discrepancies} discrepant ({pct:.1f}%) -> {verdict}", flush=True)
    for line in details:
        print(line, flush=True)
    if verdict == "FAIL":
        print("PEAD history is NOT trustworthy (doc 13 §3.1) — PEAD is NO-GO", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=dt.date.fromisoformat, default=dt.date(2023, 1, 1))
    parser.add_argument("--max-requests", type=int, default=24)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        asyncio.run(validate())
    else:
        asyncio.run(backfill(args.since, args.max_requests, args.refresh))

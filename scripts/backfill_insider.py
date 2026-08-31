"""Backfill Form 4 insider transactions from the SEC's quarterly bulk data sets.

One-shot operational tool (idempotent upsert — safe to re-run):
    docker run --rm -v "$PWD":/app -w /app --network docker_default \
      --env-file .env docker-api:latest python scripts/backfill_insider.py \
      [--from-quarter 2023q2] [--to-quarter 2026q2]

Source (no API key): https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets
Each quarter is a ~10MB ZIP of TSVs; SUBMISSION rows are filtered to the active
watchlist's tickers and Form 4/4A, then joined with NONDERIV_TRANS (the open-market
transactions) and REPORTINGOWNER (role). ``filed_ts`` (FILING_DATE) is the
point-in-time key — the bulk sets carry no acceptance time, so the conservative
reading is "actionable from the next session" (signal layer's rule, doc 13 §3).
SEC asks for a descriptive User-Agent: set SEC_USER_AGENT in .env.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import io
import os
import sys
import tempfile
import zipfile
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.db.models import InsiderTransaction
from backend.db.queries.portfolio_queries import get_active_watchlist
from backend.db.session import async_session

_URL = (
    "https://www.sec.gov/files/structureddata/data/"
    "insider-transactions-data-sets/{quarter}_form345.zip"
)
_UTC = dt.timezone.utc
# The TSVs are wide; only Form 4 rows for watchlist tickers survive the first pass,
# so memory stays bounded regardless of quarter size.
csv.field_size_limit(1 << 20)


def _quarters(start: str, end: str) -> list[str]:
    y0, q0 = int(start[:4]), int(start[5])
    y1, q1 = int(end[:4]), int(end[5])
    out = []
    y, q = y0, q0
    while (y, q) <= (y1, q1):
        out.append(f"{y}q{q}")
        q += 1
        if q == 5:
            y, q = y + 1, 1
    return out


def _latest_published_quarter(today: dt.date) -> str:
    # A quarter's set is published after it closes: latest complete quarter.
    q = (today.month - 1) // 3  # 0-based current quarter
    y = today.year
    if q == 0:
        y, q = y - 1, 4
    return f"{y}q{q}"


def _parse_date(raw: str) -> dt.date | None:
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _decimal(raw: str) -> Decimal | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _tsv(zf: zipfile.ZipFile, name: str) -> csv.DictReader:
    return csv.DictReader(
        io.TextIOWrapper(zf.open(name), encoding="utf-8", errors="replace"),
        delimiter="\t",
    )


def _rows_for_quarter(path: str, symbols: set[str]) -> list[dict]:
    with zipfile.ZipFile(path) as zf:
        filings: dict[str, dict] = {}
        for row in _tsv(zf, "SUBMISSION.tsv"):
            sym = (row.get("ISSUERTRADINGSYMBOL") or "").strip().upper()
            doc = (row.get("DOCUMENT_TYPE") or "").strip()
            if sym not in symbols or doc not in ("4", "4/A"):
                continue
            filed = _parse_date(row.get("FILING_DATE") or "")
            if filed is None:
                continue
            filings[row["ACCESSION_NUMBER"]] = {
                "symbol": sym,
                "issuer_cik": (row.get("ISSUERCIK") or "").strip() or None,
                "filed": filed,
                "is_amendment": doc == "4/A",
                "role": None,
            }
        if not filings:
            return []

        for row in _tsv(zf, "REPORTINGOWNER.tsv"):
            filing = filings.get(row["ACCESSION_NUMBER"])
            if filing is None:
                continue
            rel = (row.get("RPTOWNER_RELATIONSHIP") or "").strip()
            title = (row.get("RPTOWNER_TITLE") or "").strip()
            role = ", ".join(p for p in (rel, title) if p)[:64] or None
            # Several owners can share a filing; keep the first descriptive one.
            filing["role"] = filing["role"] or role

        raw: dict[str, list[tuple[int, dict]]] = {}
        for row in _tsv(zf, "NONDERIV_TRANS.tsv"):
            filing = filings.get(row["ACCESSION_NUMBER"])
            if filing is None:
                continue
            code = (row.get("TRANS_CODE") or "").strip()
            if not code:
                continue
            try:
                sk = int(float(row.get("NONDERIV_TRANS_SK") or 0))
            except ValueError:
                sk = 0
            raw.setdefault(row["ACCESSION_NUMBER"], []).append((sk, {
                "code": code,
                "txn_date": _parse_date(row.get("TRANS_DATE") or ""),
                "shares": _decimal(row.get("TRANS_SHARES") or ""),
                "price": _decimal(row.get("TRANS_PRICEPERSHARE") or ""),
                "shares_after": _decimal(row.get("SHRS_OWND_FOLWNG_TRANS") or ""),
            }))

    rows: list[dict] = []
    for accession, trans in raw.items():
        filing = filings[accession]
        # The surrogate key orders transactions deterministically; the stored seq is
        # the position, so re-runs upsert the same (accession, seq) pairs.
        for seq, (_, t) in enumerate(sorted(trans, key=lambda x: x[0])):
            rows.append({
                "accession_no": accession,
                "txn_seq": seq,
                "symbol": filing["symbol"],
                "insider_role": filing["role"],
                "txn_type": t["code"][:16],
                "shares": t["shares"],
                "price": t["price"],
                "filed_ts": dt.datetime.combine(filing["filed"], dt.time.min, tzinfo=_UTC),
                "issuer_cik": filing["issuer_cik"],
                "transaction_date": t["txn_date"],
                "shares_after": t["shares_after"],
                "is_amendment": filing["is_amendment"],
                "source": "sec_bulk",
            })
    return rows


# asyncpg caps a statement at 32767 bind parameters; 13 columns -> stay well under.
_UPSERT_CHUNK = 1000


async def _upsert(rows: list[dict]) -> None:
    async with async_session() as session:
        for i in range(0, len(rows), _UPSERT_CHUNK):
            chunk = rows[i : i + _UPSERT_CHUNK]
            stmt = pg_insert(InsiderTransaction).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["accession_no", "txn_seq"],
                set_={
                    c: stmt.excluded[c]
                    for c in chunk[0]
                    if c not in ("accession_no", "txn_seq")
                },
            )
            await session.execute(stmt)
        await session.commit()


async def main(from_quarter: str, to_quarter: str | None) -> None:
    async with async_session() as session:
        watchlist = await get_active_watchlist(session)
    symbols = {w.symbol.upper() for w in watchlist}
    if not symbols:
        sys.exit("watchlist is empty — nothing to backfill")

    to_quarter = to_quarter or _latest_published_quarter(dt.date.today())
    ua = os.environ.get("SEC_USER_AGENT", "autonomous-trader iker@encore-lab.com")
    total = 0
    async with httpx.AsyncClient(
        headers={"User-Agent": ua}, timeout=120.0, follow_redirects=True
    ) as client:
        for quarter in _quarters(from_quarter, to_quarter):
            resp = await client.get(_URL.format(quarter=quarter))
            if resp.status_code == 404:
                print(f"{quarter}: not published yet, skipping", flush=True)
                continue
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
                tmp.write(resp.content)
                tmp.flush()
                rows = _rows_for_quarter(tmp.name, symbols)
            if rows:
                await _upsert(rows)
            total += len(rows)
            print(f"{quarter}: {len(rows)} transactions", flush=True)
    print(f"done: {total} transactions upserted", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-quarter", default="2023q2")
    parser.add_argument("--to-quarter", default=None)
    args = parser.parse_args()
    asyncio.run(main(args.from_quarter, args.to_quarter))

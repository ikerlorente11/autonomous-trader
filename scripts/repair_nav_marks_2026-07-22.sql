-- Repair: rebuild portfolio_nav equity/total for ALL portfolios and dates.
--
-- The TimescaleDB SkipScan wrong-results bug (fixed in this PR) made
-- get_latest_bars return stale bars (value-set dependent) to update_positions /
-- snapshot_nav, so stored NAV equity drifted from reality on many days (audited
-- ±0.5%..±9.6% since at least 2026-07-06; the ledger — cash_movements and
-- trade_orders — was never affected: broker fills price through the
-- single-symbol path, which never triggered the bug).
--
-- Rebuild semantics match the system's own morning-snapshot convention:
--   * positions at snapshot = filled orders with ts < nav.ts + 9h
--     (the 08:15 UTC snapshot includes that morning's 08:00 fills; protective
--     and micro fills happen after 13:30 UTC and belong to the NEXT snapshot)
--   * marks = last stored close STRICTLY BEFORE nav.ts (bars for day D do not
--     exist at D's 08:15 snapshot)
--   * cash column is ledger-derived and stays untouched; total = cash + equity
-- Rows written by a mid-session "Run now" are approximated by the same rule.
--
-- Idempotent: recomputing is a fixed point. Run AFTER the query fix deploys:
--   docker exec -i trader-db psql -U trader -d autonomous_trader \
--     < scripts/repair_nav_marks_2026-07-22.sql

BEGIN;

WITH pos AS (
  SELECT n.portfolio_id, n.ts, t.symbol,
         SUM(CASE WHEN lower(t.side)='buy' THEN t.qty ELSE -t.qty END) AS qty
  FROM portfolio_nav n
  JOIN trade_orders t
    ON t.portfolio_id = n.portfolio_id
   AND lower(t.status) = 'filled'
   AND t.ts < n.ts + interval '9 hours'
  GROUP BY n.portfolio_id, n.ts, t.symbol
  HAVING SUM(CASE WHEN lower(t.side)='buy' THEN t.qty ELSE -t.qty END) > 0.000001
), truth AS (
  SELECT p.portfolio_id, p.ts, SUM(p.qty * b.close) AS equity_true
  FROM pos p
  JOIN LATERAL (
    SELECT close FROM market_bars
    WHERE symbol = p.symbol AND ts < p.ts
    ORDER BY ts DESC LIMIT 1
  ) b ON true
  GROUP BY p.portfolio_id, p.ts
)
UPDATE portfolio_nav n
SET equity = ROUND(COALESCE(t.equity_true, 0), 2),
    total  = n.cash + ROUND(COALESCE(t.equity_true, 0), 2)
FROM (
  SELECT n2.portfolio_id, n2.ts, tr.equity_true
  FROM portfolio_nav n2 LEFT JOIN truth tr
    ON tr.portfolio_id = n2.portfolio_id AND tr.ts = n2.ts
) t
WHERE n.portfolio_id = t.portfolio_id AND n.ts = t.ts
  AND ABS(n.equity - ROUND(COALESCE(t.equity_true, 0), 2)) > 0.01;

-- Re-mark open positions at the true latest close (current_price /
-- unrealized_pnl were written from the same buggy reads).
UPDATE portfolio_positions p
SET current_price = b.close,
    unrealized_pnl = (b.close - p.avg_cost) * p.qty
FROM LATERAL (
  SELECT close FROM market_bars WHERE symbol = p.symbol ORDER BY ts DESC LIMIT 1
) b
WHERE p.qty > 0;

-- Post-repair sanity: latest NAV per active portfolio.
SELECT p.name, l.ts::date, ROUND(l.cash,2) AS cash, ROUND(l.equity,2) AS equity,
       ROUND(l.total,2) AS total
FROM portfolios p
JOIN LATERAL (
  SELECT * FROM portfolio_nav WHERE portfolio_id = p.id ORDER BY ts DESC LIMIT 1
) l ON true
WHERE p.active ORDER BY p.id;

COMMIT;

-- weekly_performance materialized the corrupted equity; refresh everything.
CALL refresh_continuous_aggregate('weekly_performance', NULL, NULL);

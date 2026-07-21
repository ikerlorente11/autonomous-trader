-- Repair: void the 8 phantom duplicate sells minted by the run_micro ×
-- micro_eod_flatten race (fixed in fix/micro-race-finnhub-429) and remove
-- their proceeds from the NAV history so charts/compare tell the truth.
--
-- Idempotent: the UPDATEs match on status='filled', so a second run is a no-op
-- (rows are already 'cancelled' and the NAV adjustment CTE returns 0 rows).
--
-- Run: docker exec -i trader-db psql -U trader -d autonomous_trader \
--        < scripts/repair_phantom_sells_2026-07-21.sql

BEGIN;

-- The dup of each pair: same portfolio+symbol+qty sells seconds apart near the
-- close. IDs pinned explicitly (audited 2026-07-21) rather than re-derived, so
-- this script can never void a legitimate order.
CREATE TEMP TABLE phantom_fills ON COMMIT DROP AS
SELECT id, portfolio_id, ts, qty * price AS proceeds
FROM trade_orders
WHERE id IN (478, 663, 2530, 2872, 2985, 2994, 2995, 3120)
  AND lower(status) = 'filled';

-- 1) Void the fills. compute_cash() derives cash from filled orders only, so
--    live cash/NAV self-correct from here on.
UPDATE trade_orders t
SET status = 'cancelled',
    reason = 'voided: phantom duplicate sell (run_micro x micro_eod_flatten race, repaired 2026-07-21)'
FROM phantom_fills p
WHERE t.id = p.id;

-- 2) Rewrite the NAV history: every snapshot after a phantom fill carried its
--    proceeds as phantom cash.
UPDATE portfolio_nav n
SET cash  = n.cash  - adj.amount,
    total = n.total - adj.amount
FROM (
  SELECT portfolio_id, ts, SUM(proceeds) AS amount
  FROM phantom_fills GROUP BY portfolio_id, ts
) adj
WHERE n.portfolio_id = adj.portfolio_id AND n.ts > adj.ts;

-- Expected end state (pre-repair 2026-07-21): micro-500 ≈ 457.5, micro-100k ≈ 91545.4
SELECT p.name, l.ts, ROUND(l.total, 2) AS nav_now
FROM portfolios p
JOIN LATERAL (
  SELECT ts, total FROM portfolio_nav
  WHERE portfolio_id = p.id ORDER BY ts DESC LIMIT 1
) l ON true
WHERE p.id IN (14, 15);

COMMIT;

-- The weekly_performance continuous aggregate materialized the phantom NAV;
-- refresh the full range (small table). Must run outside the transaction.
CALL refresh_continuous_aggregate('weekly_performance', NULL, NULL);

-- Repair: void the 8 phantom duplicate sells minted by the run_micro ×
-- micro_eod_flatten race (fixed in this same PR) and rebuild the micro NAV
-- history from the clean ledgers so charts/compare tell the truth.
--
-- EXECUTED against prod on 2026-07-21 (kept for the audit trail). Idempotent:
-- re-voiding matches nothing and the ledger rebuild is a fixed point.
--
-- NOTE the NAV step rebuilds cash from the ledgers (the compute_cash formula)
-- instead of subtracting per-fill adjustments: UPDATE ... FROM applies at most
-- ONE matching source row per target row, so a per-fill subtraction silently
-- drops all but one adjustment when several phantom fills precede a snapshot.
--
-- Run: docker exec -i trader-db psql -U trader -d autonomous_trader \
--        < scripts/repair_phantom_sells_2026-07-21.sql

BEGIN;

-- The dup of each pair: same portfolio+symbol+qty sells seconds apart near the
-- close. IDs pinned explicitly (audited 2026-07-21) rather than re-derived, so
-- this script can never void a legitimate order.
UPDATE trade_orders
SET status = 'cancelled',
    reason = 'voided: phantom duplicate sell (run_micro x micro_eod_flatten race, repaired 2026-07-21)'
WHERE id IN (478, 663, 2530, 2872, 2985, 2994, 2995, 3120)
  AND lower(status) = 'filled';

-- Rebuild the micro NAV history: historical cash at snapshot time T is a pure
-- function of the (now-clean) ledgers, mirroring compute_cash:
--   cash(T) = Σ deposits(≤T) − Σ withdrawals(≤T)
--           − Σ filled buys (price·qty + commission, ts ≤ T)
--           + Σ filled sells (price·qty − commission, ts ≤ T)
-- total = cash + equity (equity snapshots were always correct: the phantom
-- sells only ever inflated cash).
UPDATE portfolio_nav n
SET cash = c.correct_cash,
    total = c.correct_cash + n.equity
FROM (
  SELECT n2.portfolio_id, n2.ts,
    COALESCE((SELECT SUM(CASE WHEN m.kind='deposit' THEN m.amount ELSE -m.amount END)
              FROM cash_movements m
              WHERE m.portfolio_id=n2.portfolio_id AND m.ts <= n2.ts),0)
    -
    COALESCE((SELECT SUM(CASE WHEN lower(t.side)='buy' THEN t.price*t.qty ELSE -(t.price*t.qty) END
                        + COALESCE(t.commission,0))
              FROM trade_orders t
              WHERE t.portfolio_id=n2.portfolio_id AND lower(t.status)='filled' AND t.ts <= n2.ts),0)
    AS correct_cash
  FROM portfolio_nav n2
  WHERE n2.portfolio_id IN (14,15)
) c
WHERE n.portfolio_id = c.portfolio_id AND n.ts = c.ts;

-- Verified end state on 2026-07-21: micro-500 = 457.50, micro-100k = 91545.38
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

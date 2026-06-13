-- Reset all active portfolios to a clean, comparable starting state.
--
-- Wipes every trade, position mark and NAV snapshot, and re-dates each portfolio's
-- single funding deposit to now() so all arms share one inception date. The deposit
-- amount (contributed capital) is preserved, so cash returns to the nominal budget
-- and every portfolio starts flat (100% cash). Strategy label and name are untouched.
--
-- Paper system only — safe to run directly. Run inside the db container:
--   docker exec -i trader-db psql -U trader -d autonomous_trader < scripts/reset_portfolios.sql
--
-- After this, the next daily run (or "Run now") re-enters positions ONLY when each
-- version's signals say so AND the market filter allows it — no forced first-run buy.

BEGIN;

DELETE FROM trade_orders       WHERE portfolio_id IN (SELECT id FROM portfolios WHERE active);
DELETE FROM portfolio_positions WHERE portfolio_id IN (SELECT id FROM portfolios WHERE active);
DELETE FROM portfolio_nav      WHERE portfolio_id IN (SELECT id FROM portfolios WHERE active);

-- One funding deposit per portfolio already holds the nominal budget; re-date it so
-- every arm's performance clock starts together.
UPDATE cash_movements SET ts = now()
WHERE portfolio_id IN (SELECT id FROM portfolios WHERE active)
  AND kind = 'deposit';

COMMIT;

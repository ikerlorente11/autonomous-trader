<!--
  Route: /system (Health & Scheduler)  —  UX: docs/design/ux-architecture.md §3.6
  Purpose: "is the machine healthy?"  (scaffold — job-status endpoint pending)

  Contents (Phase 5 — Frontend Developer):
    - Expanded health rollup mirroring the +layout banner.
    - Daily job status table: job, scheduled (UTC), last run, status, duration, rows written
      (7 jobs: fetch_macro_data, fetch_news_sentiment, fetch_market_data, fetch_fundamentals,
       run_analysis, execute_paper_trades, update_portfolio_nav).
    - Status cards (status palette): NAV continuity, bar freshness (% universe),
      signal coverage (mean data_completeness), stuck PENDING orders, ledger reconciles.
    - Regime history chart (RISK_ON/CAUTION/RISK_OFF over time) + recent error log.

  Endpoints: pending — assumed GET /api/system/health (flag to Backend Architect;
             module-contracts §4 exposes no job-status endpoint yet).
  Refresh: job table every 30 s while this route is open (pause on unmount).
  Rule: status palette only (--status-*) — never the P&L palette.
-->

<h1>System</h1>

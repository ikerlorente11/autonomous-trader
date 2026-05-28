<!--
  Route: /trades (Trade Ledger)  —  UX: docs/design/ux-architecture.md §3.4
  Purpose: "what did the algorithm actually do?"

  Contents (Phase 5 — Frontend Developer):
    - Filters: date range, symbol, side (BUY/SELL), sector, strategy_version.
    - Trade ledger table (paged, sortable): fill_ts, symbol, sector, side, qty, price,
      cost basis, realized P&L (P&L palette), signal_score. Row click -> detail.
    - Trade detail panel: order_id, timestamps, FIFO matched lots, triggering final_score,
      mini price chart around the fill date.

  Endpoints: GET /api/trades, /api/market/bars
  Refresh: on load, then every 5 min (written once/day by execute_paper_trades).
-->

<h1>Trades</h1>

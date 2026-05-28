<!--
  Route: /market (Watchlist & Per-Symbol Detail)  —  UX: docs/design/ux-architecture.md §3.3
  Purpose: "what does the universe look like right now?"

  Contents (Phase 5 — Frontend Developer):
    - Controls: search, sort (score/Δ/symbol), filter (sector, role: alpha/hedge/benchmark).
    - 50-symbol watchlist grid: symbol, name, sector, last, daily Δ%, composite score,
      regime tag, role. Row click -> per-symbol detail (?symbol= query param).
    - Per-symbol detail: candlestick chart (OHLCV), signal-series chart (final_score +
      components), latest indicator snapshot panel (show data_completeness).

  Endpoints: GET /api/market/watchlist, /api/market/latest, /api/algorithms/ranked,
             /api/market/bars, /api/market/signal
  Refresh: watchlist on load + 5 min (marks are daily closes, not intraday);
           detail charts on load + manual refresh + on range change.
-->

<h1>Market</h1>

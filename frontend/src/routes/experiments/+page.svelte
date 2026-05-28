<!--
  Route: /experiments (Strategy Comparison)  —  UX: docs/design/ux-architecture.md §3.5
  Purpose: "which strategy version is better?"  (scaffold — data source pending)

  Contents (Phase 5 — Frontend Developer):
    - Strategy versions table: version, active dates, total return, Sharpe, max DD, trades.
    - Compare two versions -> side-by-side returns/risk/activity + parameter diff.
    - Cumulative-return-by-version overlay chart.
    - Empty state until the Experiment Tracker's strategy_version surface/endpoint exists.

  Endpoints: pending — Experiment Tracker (docs/finance/experiment-framework.md).
  Refresh: on load (historical comparison; no polling needed).
-->

<h1>Experiments</h1>

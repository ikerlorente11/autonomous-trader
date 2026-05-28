<!--
  Route: /portfolio (Positions & Attribution)  —  UX: docs/design/ux-architecture.md §3.2
  Purpose: "what do I hold and what's it worth?"

  Contents (Phase 5 — Frontend Developer):
    - Period switcher.
    - Cards: NAV, Cash, Positions Value, Realized P&L, Unrealized P&L (P&L palette).
    - NAV detail chart (full width) with cash/positions split area beneath.
    - Open positions table: symbol, sector, qty, avg cost, mark, mkt value,
      unrealized P&L $/%, weight %.
    - Per-sector P&L bar + per-symbol P&L table (realized + unrealized, contribution %).

  Endpoints: GET /api/portfolio/positions, /api/portfolio/nav, /api/portfolio/performance
  Refresh: on load, then every 5 min (daily-batch backend; NAV snapshot 08:15 UTC).
-->

<h1>Portfolio</h1>

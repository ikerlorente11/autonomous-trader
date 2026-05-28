<!--
  Route: / (Main Dashboard)  —  UX: docs/design/ux-architecture.md §3.1
  Purpose: glance-first answer to "is it running, is it doing well, what did it do today?"

  Contents (Phase 5 — Frontend Developer):
    - Period switcher (Daily/WTD/MTD/YTD/Inception/30·60·90d) driving everything below.
    - Performance band (P&L palette): Cards 1-6 — NAV, Today's P&L, Total Return,
      Alpha vs SPY (MTD), Max Drawdown, Sharpe 90d.
    - Context/Health band (status palette): Cards 7-9 — Cash/Exposure, Regime, Health.
    - NAV-over-time chart (full width) with SPY benchmark overlay, optional regime shading.
    - Tables: today's ranked signals (top 10), today's trades.
    - Sector P&L bar + Best/Worst contributors list.

  Endpoints: GET /api/portfolio/nav, /api/portfolio/performance,
             /api/algorithms/ranked, /api/trades, /api/market/sentiment
  Refresh: cards/NAV/signals/trades every 5 min; health chip (in +layout) every 60 s.
  Rule: never interleave --pnl-* and --status-* palettes (FP&A §4 / UI Designer A.1-2).
-->

<h1>Dashboard</h1>

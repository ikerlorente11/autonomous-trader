// HTTP contract types — mirror the LIVE backend (backend/api/schemas.py,
// backend/contracts.py). Decimal columns serialize to JSON as strings; parse
// defensively with toNum(). Timestamps are ISO 8601 (UTC).

export interface ApiErrorEnvelope {
	error?: { code?: string; message?: string };
	detail?: unknown;
}

// backend/api/schemas.py::PortfolioSummary
export interface PortfolioSummary {
	portfolio_id: number;
	name: string;
	cash: string;
	equity: string;
	total: string;
	contributed_capital: string;
	total_pnl: string;
	unrealized_pnl: string;
	positions_count: number;
}

// backend/api/schemas.py::Portfolio
export interface Portfolio {
	id: number;
	name: string;
	active: boolean;
	created_at: string;
}

// backend/api/schemas.py::CashMovement
export interface CashMovement {
	id: number;
	portfolio_id: number;
	kind: string;
	amount: string;
	ts: string;
	note: string | null;
}

// backend/contracts.py::Position
export interface Position {
	symbol: string;
	qty: string;
	avg_cost: string;
	current_price: string | null;
	unrealized_pnl: string | null;
	updated_at: string | null;
}

export interface Quote {
	symbol: string;
	price: string;
}

// backend/contracts.py::PortfolioSnapshot
export interface PortfolioSnapshot {
	ts: string;
	cash: string;
	equity: string;
	total: string;
	benchmark_value: string | null;
}

// backend/contracts.py::PerformanceMetrics — three open float dicts.
export interface PerformanceMetrics {
	returns: Record<string, number>;
	risk: Record<string, number>;
	trades: Record<string, number>;
}

// backend/api/schemas.py::WatchlistEntry
export interface WatchlistEntry {
	symbol: string;
	sector: string | null;
	asset_class: string | null;
	latest_price: string | null;
	score: string | null;
	action: string | null;
	ts: string | null;
}

// backend/contracts.py::OHLCVBar
export interface OHLCVBar {
	symbol: string;
	ts: string;
	open: string;
	high: string;
	low: string;
	close: string;
	volume: number;
	adj_close: string;
}

export type OrderSide = 'buy' | 'sell';
export type OrderState = 'pending' | 'filled' | 'rejected' | 'cancelled';
export type SignalAction = 'buy' | 'sell' | 'hold';

// backend/contracts.py::TradeRecord
export interface TradeRecord {
	id: number;
	symbol: string;
	side: OrderSide;
	qty: string;
	price: string | null;
	status: OrderState;
	reason: string | null;
	strategy_version: string | null;
	ts: string;
}

// backend/contracts.py::TradeRoundTrip — GET /api/trades/round-trips
export interface TradeRoundTrip {
	symbol: string;
	entry_ts: string;
	exit_ts: string;
	qty: number;
	entry_price: number;
	exit_price: number;
	pnl: number;
	return_pct: number | null;
	holding_days: number;
}

// backend/api/schemas.py::SignalAccuracySummary — GET /api/algorithms/accuracy
export interface SignalAccuracySummary {
	accuracy: number | null;
	signal_count: number;
	correct_count: number;
}

// backend/api/schemas.py::SignalEntry
export interface SignalEntry {
	symbol: string;
	ts: string;
	score: string;
	action: SignalAction;
	reason: string | null;
	indicator_snapshot: Record<string, number> | null;
	strategy_version: string | null;
}

// backend/api/schemas.py::ExperimentEntry
export interface ExperimentEntry {
	id: number;
	strategy_version: string;
	started_at: string;
	ended_at: string | null;
	config: Record<string, unknown> | null;
	notes: string | null;
}

// backend/api/schemas.py::JobStatus
export interface JobStatus {
	job: string;
	status: string | null;
	last_run_at: string | null;
	ended_at: string | null;
	duration_ms: number | null;
	error: string | null;
	next_run_at: string | null;
}

// backend/api/schemas.py::SystemStatus
export interface SystemStatus {
	server_time: string;
	jobs: JobStatus[];
	recent_errors: JobStatus[];
}

// backend/api/schemas.py::RunTrigger
export interface RunTrigger {
	status: string;
	detail: string;
}

// Client-side NAV range presets -> translated to start/end ISO datetimes.
export type NavRange = '7d' | '30d' | '90d' | '1y' | 'all';
// Client-side bar range presets for candlesticks.
export type BarsRange = '30d' | '90d' | '1y';

import { api } from './client';
import { getActivePortfolioId } from '$lib/stores/activePortfolio';
import type {
	AttributionAxis,
	AttributionReport,
	BarsRange,
	CashMovement,
	ExperimentEntry,
	FpaPeriod,
	NavRange,
	OHLCVBar,
	PerformanceMetrics,
	PeriodPerformance,
	Portfolio,
	PortfolioComparison,
	PortfolioSnapshot,
	PortfolioSummary,
	Position,
	Quote,
	RunTrigger,
	SignalEntry,
	StrategyVersion,
	SystemStatus,
	TradeRecord,
	WatchlistEntry
} from './types';

type F = typeof fetch;

const DAY_MS = 86_400_000;

// Scope a request to the active portfolio (omitted -> backend uses its default).
function portfolioParam(): { portfolio_id?: number } {
	const id = getActivePortfolioId();
	return id === null ? {} : { portfolio_id: id };
}

// Translate a UI range preset into a backend start/end datetime window.
function rangeWindow(range: NavRange | BarsRange): { start?: string; end?: string } {
	const end = new Date();
	const days: Record<string, number | null> = {
		'7d': 7,
		'30d': 30,
		'90d': 90,
		'1y': 365,
		all: null
	};
	const d = days[range];
	if (d === null || d === undefined) return {}; // 'all' -> let backend default span apply
	const start = new Date(end.getTime() - d * DAY_MS);
	return { start: start.toISOString(), end: end.toISOString() };
}

export const portfolioApi = {
	summary: (f?: F) =>
		api.get<PortfolioSummary>('/portfolio/summary', { params: portfolioParam(), fetcher: f }),
	positions: (f?: F) =>
		api.get<Position[]>('/portfolio/positions', { params: portfolioParam(), fetcher: f }),
	nav: (range: NavRange, f?: F) =>
		api.get<PortfolioSnapshot[]>('/portfolio/nav', {
			params: { ...rangeWindow(range), ...portfolioParam() },
			fetcher: f
		}),
	performance: (f?: F) =>
		api.get<PerformanceMetrics>('/portfolio/performance', {
			params: portfolioParam(),
			fetcher: f
		}),
	performancePeriods: (f?: F) =>
		api.get<PeriodPerformance[]>('/portfolio/performance/periods', {
			params: portfolioParam(),
			fetcher: f
		}),
	attribution: (period: FpaPeriod, by: AttributionAxis, f?: F) =>
		api.get<AttributionReport>('/portfolio/attribution', {
			params: { period, by, ...portfolioParam() },
			fetcher: f
		})
};

export interface NewPortfolio {
	name: string;
	initial_deposit?: number;
}

export const portfoliosApi = {
	list: (f?: F) => api.get<Portfolio[]>('/portfolios', { fetcher: f }),
	create: (input: NewPortfolio) => api.post<Portfolio>('/portfolios', input),
	rename: (id: number, name: string) => api.patch<Portfolio>(`/portfolios/${id}`, { name }),
	setStrategy: (id: number, strategy_label: string | null) =>
		api.patch<Portfolio>(`/portfolios/${id}`, { strategy_label }),
	navFor: (id: number, range: NavRange, f?: F) =>
		api.get<PortfolioSnapshot[]>('/portfolio/nav', {
			params: { ...rangeWindow(range), portfolio_id: id },
			fetcher: f
		}),
	remove: (id: number) => api.del<void>(`/portfolios/${id}`),
	deposit: (id: number, amount: number, note?: string) =>
		api.post<CashMovement>(`/portfolios/${id}/deposit`, { amount, note }),
	withdraw: (id: number, amount: number, note?: string) =>
		api.post<CashMovement>(`/portfolios/${id}/withdraw`, { amount, note }),
	movements: (id: number, f?: F) =>
		api.get<CashMovement[]>(`/portfolios/${id}/movements`, { fetcher: f })
};

// Explicitly-scoped reads for a specific portfolio id (the micro section shows a
// portfolio other than the global active daily one). Same endpoints, fixed id.
export const portfolioByIdApi = {
	summary: (id: number, f?: F) =>
		api.get<PortfolioSummary>('/portfolio/summary', { params: { portfolio_id: id }, fetcher: f }),
	positions: (id: number, f?: F) =>
		api.get<Position[]>('/portfolio/positions', { params: { portfolio_id: id }, fetcher: f }),
	nav: (id: number, range: NavRange, f?: F) =>
		api.get<PortfolioSnapshot[]>('/portfolio/nav', {
			params: { ...rangeWindow(range), portfolio_id: id },
			fetcher: f
		}),
	trades: (id: number, limit = 50, f?: F) =>
		api.get<TradeRecord[]>('/trades', { params: { portfolio_id: id, limit }, fetcher: f })
};

export const strategiesApi = {
	list: (f?: F) => api.get<StrategyVersion[]>('/strategies', { fetcher: f })
};

export const marketApi = {
	watchlist: (f?: F) => api.get<WatchlistEntry[]>('/market/watchlist', { fetcher: f }),
	quotes: (symbols: string[], f?: F) =>
		api.get<Quote[]>('/market/quotes', { params: { symbols: symbols.join(',') }, fetcher: f }),
	bars: (symbol: string, range: BarsRange, f?: F) =>
		api.get<OHLCVBar[]>(`/market/bars/${encodeURIComponent(symbol)}`, {
			params: rangeWindow(range),
			fetcher: f
		}),
	addSymbol: (input: { symbol: string; sector?: string; asset_class?: string }) =>
		api.post<WatchlistEntry>('/market/watchlist', input),
	removeSymbol: (symbol: string) =>
		api.del<WatchlistEntry>(`/market/watchlist/${encodeURIComponent(symbol)}`)
};

export interface TradeFilters {
	symbol?: string;
	start?: string;
	end?: string;
	limit?: number;
}

export const tradesApi = {
	list: (filters: TradeFilters = {}, f?: F) =>
		api.get<TradeRecord[]>('/trades', { params: { ...filters, ...portfolioParam() }, fetcher: f })
};

export const algorithmsApi = {
	signals: (limit = 20, f?: F) =>
		api.get<SignalEntry[]>('/algorithms/signals', { params: { limit }, fetcher: f }),
	experiments: (f?: F) => api.get<ExperimentEntry[]>('/algorithms/experiments', { fetcher: f }),
	compare: (a: number, b: number, f?: F) =>
		api.get<PortfolioComparison>('/algorithms/compare', { params: { a, b }, fetcher: f })
};

export const systemApi = {
	status: (f?: F) => api.get<SystemStatus>('/system/status', { fetcher: f }),
	run: () => api.post<RunTrigger>('/system/run')
};

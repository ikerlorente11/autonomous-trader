import { api } from './client';
import type {
	BarsRange,
	ExperimentEntry,
	NavRange,
	OHLCVBar,
	PerformanceMetrics,
	PortfolioSnapshot,
	PortfolioSummary,
	Position,
	SignalEntry,
	SystemStatus,
	TradeRecord,
	WatchlistEntry
} from './types';

type F = typeof fetch;

const DAY_MS = 86_400_000;

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
	summary: (f?: F) => api.get<PortfolioSummary>('/portfolio/summary', { fetcher: f }),
	positions: (f?: F) => api.get<Position[]>('/portfolio/positions', { fetcher: f }),
	nav: (range: NavRange, f?: F) =>
		api.get<PortfolioSnapshot[]>('/portfolio/nav', { params: rangeWindow(range), fetcher: f }),
	performance: (f?: F) => api.get<PerformanceMetrics>('/portfolio/performance', { fetcher: f })
};

export const marketApi = {
	watchlist: (f?: F) => api.get<WatchlistEntry[]>('/market/watchlist', { fetcher: f }),
	bars: (symbol: string, range: BarsRange, f?: F) =>
		api.get<OHLCVBar[]>(`/market/bars/${encodeURIComponent(symbol)}`, {
			params: rangeWindow(range),
			fetcher: f
		})
};

export interface TradeFilters {
	symbol?: string;
	start?: string;
	end?: string;
	limit?: number;
}

export const tradesApi = {
	list: (filters: TradeFilters = {}, f?: F) =>
		api.get<TradeRecord[]>('/trades', { params: { ...filters }, fetcher: f })
};

export const algorithmsApi = {
	signals: (limit = 20, f?: F) =>
		api.get<SignalEntry[]>('/algorithms/signals', { params: { limit }, fetcher: f }),
	experiments: (f?: F) => api.get<ExperimentEntry[]>('/algorithms/experiments', { fetcher: f })
};

export const systemApi = {
	status: (f?: F) => api.get<SystemStatus>('/system/status', { fetcher: f })
};

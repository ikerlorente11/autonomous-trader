// Metric threshold bands from docs/finance/performance-metrics.md §4
// (PerformanceThresholds). Backend emits metrics as FRACTIONS (sharpe 1.12,
// max_drawdown -0.067, win_rate 0.55), so bands are evaluated on fractions.
import { toNum } from './format';

export type Band = 'good' | 'warn' | 'bad' | 'neutral';

type Evaluator = (n: number) => Band;

const evaluators: Record<string, Evaluator> = {
	sharpe: (n) => (n >= 1.0 ? 'good' : n >= 0.0 ? 'warn' : 'bad'),
	sortino: (n) => (n >= 1.5 ? 'good' : n >= 0.0 ? 'warn' : 'bad'),
	calmar: (n) => (n >= 0.5 ? 'good' : n >= 0.0 ? 'warn' : 'bad'),
	// max_drawdown is a negative fraction; > -0.10 good, -0.10..-0.20 warn, < -0.20 bad
	max_drawdown: (n) => (n > -0.1 ? 'good' : n >= -0.2 ? 'warn' : 'bad'),
	win_rate: (n) => (n >= 0.45 ? 'good' : n >= 0.4 ? 'warn' : 'bad'),
	profit_factor: (n) => (n >= 1.5 ? 'good' : n >= 1.0 ? 'warn' : 'bad'),
	alpha: (n) => (n > 0 ? 'good' : n === 0 ? 'warn' : 'bad'),
	total: (n) => (n > 0 ? 'good' : n === 0 ? 'neutral' : 'bad'),
	annualized: (n) => (n > 0 ? 'good' : n === 0 ? 'neutral' : 'bad')
};

export function band(metric: string, value: string | number | null | undefined): Band {
	const n = toNum(value);
	if (n === null || Number.isNaN(n)) return 'neutral';
	const ev = evaluators[metric];
	return ev ? ev(n) : 'neutral';
}

// Score band for 0-100 composite signal scores (ui-system §C.4).
export function scoreBand(value: string | number | null | undefined): Band {
	const n = toNum(value);
	if (n === null) return 'neutral';
	if (n >= 60) return 'good';
	if (n >= 40) return 'warn';
	return 'bad';
}

// Metrics that should render as a percentage (value × 100).
export const percentMetrics = new Set([
	'total',
	'annualized',
	'benchmark',
	'alpha',
	'max_drawdown',
	'win_rate'
]);

// Metrics shown with an explicit +/- sign.
export const signedMetrics = new Set(['total', 'annualized', 'benchmark', 'alpha', 'max_drawdown']);

export const metricLabels: Record<string, string> = {
	total: 'Total Return',
	annualized: 'CAGR',
	benchmark: 'Benchmark (SPY)',
	alpha: 'Alpha',
	beta: 'Beta',
	sharpe: 'Sharpe',
	sortino: 'Sortino',
	max_drawdown: 'Max Drawdown',
	calmar: 'Calmar',
	win_rate: 'Win Rate',
	profit_factor: 'Profit Factor',
	avg_win: 'Avg Win',
	avg_loss: 'Avg Loss',
	win_loss_ratio: 'Win/Loss Ratio'
};

export const metricTooltips: Record<string, string> = {
	total: 'Total return since the start of the window: NAV_end / NAV_start − 1.',
	annualized: 'Compound annual growth rate of NAV.',
	benchmark: 'SPY return over the identical window.',
	alpha: 'Annualized Jensen alpha vs SPY after adjusting for beta. >0 beats buy-and-hold.',
	beta: 'Sensitivity of the portfolio to SPY moves. 1.0 = moves with the market.',
	sharpe: 'Mean excess return / volatility, annualized. ≥1.0 is earning its risk.',
	sortino: 'Like Sharpe but penalizes only downside volatility. Target ≥1.5.',
	max_drawdown: 'Largest peak-to-trough NAV decline. >−10% caution, >−20% breach.',
	calmar: 'CAGR / |max drawdown|. Return per unit of worst-case pain.',
	win_rate: 'Share of closed round-trips that were profitable. Read with profit factor.',
	profit_factor: 'Gross profit / gross loss. <1.0 loses money gross; ≥1.5 healthy.',
	avg_win: 'Average P&L of winning round-trips.',
	avg_loss: 'Average P&L of losing round-trips.',
	win_loss_ratio: 'Average win divided by average loss.'
};

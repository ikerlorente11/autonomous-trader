// Maps UI Designer tokens (ui-system §A) to Chart.js colors. Token names match
// frontend/src/lib/styles/tokens.css exactly. Read from the live DOM so a future
// theme switch flows through automatically.

function cssVar(name: string, fallback: string): string {
	if (typeof window === 'undefined') return fallback;
	const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	return v || fallback;
}

function rgba(hex: string, alpha: number): string {
	const m = /^#?([0-9a-f]{6})$/i.exec(hex.replace('#', ''));
	if (!m) return hex;
	const int = parseInt(m[1], 16);
	return `rgba(${(int >> 16) & 255},${(int >> 8) & 255},${int & 255},${alpha})`;
}

export interface ChartTokens {
	textPrimary: string;
	textSecondary: string;
	gridLine: string;
	accent: string;
	accentFill: string;
	benchmark: string;
	gain: string;
	loss: string;
	warn: string;
	candleUp: string;
	candleDown: string;
	candleVolUp: string;
	candleVolDown: string;
	surfaceOverlay: string;
	borderStrong: string;
	fontSans: string;
	fontMono: string;
}

export function chartTokens(): ChartTokens {
	const grid = cssVar('--chart-grid', '#21272f');
	return {
		textPrimary: cssVar('--text-primary', '#e6edf3'),
		textSecondary: cssVar('--chart-axis', '#7d8896'),
		gridLine: rgba(grid, 0.7),
		accent: cssVar('--chart-portfolio', '#4c8dff'),
		accentFill: 'rgba(76,141,255,0.15)',
		benchmark: cssVar('--chart-benchmark', '#9aa4b2'),
		gain: cssVar('--pnl-gain', '#26a269'),
		loss: cssVar('--pnl-loss', '#e5484d'),
		warn: cssVar('--status-warn', '#f5a623'),
		candleUp: cssVar('--candle-up-body', '#26a269'),
		candleDown: cssVar('--candle-down-body', '#e5484d'),
		candleVolUp: cssVar('--candle-volume-up', 'rgba(38,162,105,0.35)'),
		candleVolDown: cssVar('--candle-volume-down', 'rgba(229,72,77,0.35)'),
		surfaceOverlay: cssVar('--surface-overlay', '#1c2330'),
		borderStrong: cssVar('--border-strong', '#3a4452'),
		fontSans: cssVar('--font-sans', 'system-ui, sans-serif'),
		fontMono: cssVar('--font-mono', 'ui-monospace, monospace')
	};
}

export function baseScales(t: ChartTokens) {
	return {
		x: {
			grid: { color: t.gridLine, drawTicks: false },
			border: { display: false },
			ticks: { color: t.textSecondary, font: { size: 11, family: t.fontSans }, maxRotation: 0 }
		},
		y: {
			grid: { color: t.gridLine, drawTicks: false },
			border: { display: false },
			ticks: { color: t.textSecondary, font: { size: 11, family: t.fontMono } }
		}
	};
}

export function tooltipStyle(t: ChartTokens) {
	return {
		backgroundColor: t.surfaceOverlay,
		borderColor: t.borderStrong,
		borderWidth: 1,
		titleColor: t.textPrimary,
		bodyColor: t.textPrimary,
		titleFont: { family: t.fontSans, size: 12 },
		bodyFont: { family: t.fontMono, size: 12 },
		padding: 10,
		cornerRadius: 6
	};
}

// Formatting helpers. API money/metric values are strings; parse defensively.

export function toNum(v: string | number | null | undefined): number | null {
	if (v === null || v === undefined || v === '') return null;
	const n = typeof v === 'number' ? v : Number(v);
	return Number.isFinite(n) ? n : null;
}

const moneyFmt = new Intl.NumberFormat('en-US', {
	minimumFractionDigits: 2,
	maximumFractionDigits: 2
});

export function money(v: string | number | null | undefined, withSign = false): string {
	const n = toNum(v);
	if (n === null) return '—';
	const sign = withSign && n > 0 ? '+' : n < 0 ? '−' : '';
	return `${sign}€${moneyFmt.format(Math.abs(n))}`;
}

// Value is ALREADY a percent (e.g. 1.24 -> "1.24%").
export function percent(v: string | number | null | undefined, withSign = true): string {
	const n = toNum(v);
	if (n === null || Number.isNaN(n)) return '—';
	const sign = withSign ? (n > 0 ? '+' : n < 0 ? '−' : '') : '';
	return `${sign}${Math.abs(n).toFixed(2)}%`;
}

// Value is a FRACTION (e.g. 0.0124 -> "1.24%"). Used for backend metric dicts.
export function percentFrac(v: string | number | null | undefined, withSign = true): string {
	const n = toNum(v);
	if (n === null || Number.isNaN(n)) return '—';
	return percent(n * 100, withSign);
}

export function num(v: string | number | null | undefined, dp = 2): string {
	const n = toNum(v);
	if (n === null || Number.isNaN(n)) return '—';
	return n.toFixed(dp);
}

export function qty(v: string | number | null | undefined): string {
	const n = toNum(v);
	if (n === null) return '—';
	return Number.isInteger(n) ? String(n) : n.toString();
}

const intFmt = new Intl.NumberFormat('en-US');

export function compactInt(v: string | number | null | undefined): string {
	const n = toNum(v);
	if (n === null) return '—';
	return intFmt.format(Math.round(n));
}

export function changeClass(v: string | number | null | undefined): 'gain' | 'loss' | 'flat' {
	const n = toNum(v);
	if (n === null || n === 0) return 'flat';
	return n > 0 ? 'gain' : 'loss';
}

export function arrow(v: string | number | null | undefined): string {
	const n = toNum(v);
	if (n === null || n === 0) return '';
	return n > 0 ? '▲' : '▼';
}

export function formatDate(iso: string | null | undefined): string {
	if (!iso) return '—';
	const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
	if (Number.isNaN(d.getTime())) return iso;
	return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: '2-digit' });
}

export function formatDateTime(iso: string | null | undefined): string {
	if (!iso) return '—';
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return iso;
	return d.toLocaleString('en-US', {
		month: 'short',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
		hour12: false
	});
}

export function relativeFromNow(iso: string | null | undefined): string {
	if (!iso) return 'never';
	const then = new Date(iso).getTime();
	if (Number.isNaN(then)) return '—';
	const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000));
	if (diffSec < 60) return `${diffSec}s ago`;
	const min = Math.round(diffSec / 60);
	if (min < 60) return `${min}m ago`;
	const hr = Math.round(min / 60);
	if (hr < 24) return `${hr}h ago`;
	const day = Math.round(hr / 24);
	return `${day}d ago`;
}

// Formatting helpers. API money/metric values are strings; parse defensively.
import { getLocale, t } from '$lib/i18n';

// Numbers/money keep a fixed format on purpose; only textual date/time output is localized.
function dateLocale(): string {
	return getLocale() === 'es' ? 'es-ES' : 'en-US';
}

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

export function num(v: string | number | null | undefined, dp = 2): string {
	const n = toNum(v);
	if (n === null || Number.isNaN(n)) return '—';
	return n.toFixed(dp);
}

export function qty(v: string | number | null | undefined): string {
	const n = toNum(v);
	if (n === null) return '—';
	return String(n);
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
	return d.toLocaleDateString(dateLocale(), { year: 'numeric', month: 'short', day: '2-digit' });
}

export function formatDateTime(iso: string | null | undefined): string {
	if (!iso) return '—';
	const d = new Date(iso);
	if (Number.isNaN(d.getTime())) return iso;
	return d.toLocaleString(dateLocale(), {
		month: 'short',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
		hour12: false
	});
}

export function relativeFromNow(iso: string | null | undefined): string {
	if (!iso) return t('common.never');
	const then = new Date(iso).getTime();
	if (Number.isNaN(then)) return '—';
	const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000));
	if (diffSec < 60) return t('time.secondsAgo', { n: diffSec });
	const min = Math.round(diffSec / 60);
	if (min < 60) return t('time.minutesAgo', { n: min });
	const hr = Math.round(min / 60);
	if (hr < 24) return t('time.hoursAgo', { n: hr });
	const day = Math.round(hr / 24);
	return t('time.daysAgo', { n: day });
}

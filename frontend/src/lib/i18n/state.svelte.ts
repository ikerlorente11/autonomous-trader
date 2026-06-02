import { LOCALES, messages, type Locale } from './messages';

const DEFAULT_LOCALE: Locale = 'es';
const STORAGE_KEY = 'at-locale';

function isLocale(v: string | null): v is Locale {
	return v !== null && (LOCALES as readonly string[]).includes(v);
}

let current = $state<Locale>(DEFAULT_LOCALE);

// Resolve the saved choice once on the client and sync <html lang>. SSR/prerender
// renders the default locale; hydration applies the stored preference.
export function initLocale(): void {
	if (typeof localStorage !== 'undefined') {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (isLocale(saved)) current = saved;
	}
	syncDocumentLang();
}

function syncDocumentLang(): void {
	if (typeof document !== 'undefined') document.documentElement.lang = current;
}

export function getLocale(): Locale {
	return current;
}

export function setLocale(next: Locale): void {
	if (next === current) return;
	current = next;
	if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, next);
	syncDocumentLang();
}

export function t(key: string, vars?: Record<string, string | number>): string {
	const table = messages[current];
	let text = table[key] ?? messages[DEFAULT_LOCALE][key] ?? key;
	if (vars) {
		for (const [name, value] of Object.entries(vars)) {
			text = text.replaceAll(`{${name}}`, String(value));
		}
	}
	return text;
}

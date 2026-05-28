import { systemApi } from '$lib/api/endpoints';
import type { SystemStatus } from '$lib/api/types';

// Shared, layout-scoped system status. Polls every 30s (ux-architecture §4 — the
// health surface is the only fast-moving signal). One poller feeds both the header
// health dot and the /system page so we don't double-poll.
const POLL_MS = 30_000;

let status = $state<SystemStatus | null>(null);
let available = $state(true);
let lastUpdated = $state<number | null>(null);
let timer: ReturnType<typeof setInterval> | null = null;
let started = false;

async function fetchOnce() {
	try {
		status = await systemApi.status();
		available = true;
		lastUpdated = Date.now();
	} catch {
		// Endpoint failure (incl. 404 if backend not wired): keep header functional.
		available = false;
	}
}

export function startSystemPolling() {
	if (started || typeof window === 'undefined') return;
	started = true;
	void fetchOnce();
	timer = setInterval(() => {
		if (document.hidden) return;
		void fetchOnce();
	}, POLL_MS);
}

export function stopSystemPolling() {
	if (timer) clearInterval(timer);
	timer = null;
	started = false;
}

// Health rollup: worst job status wins.
export function healthLevel(s: SystemStatus | null): 'ok' | 'degraded' | 'broken' | 'unknown' {
	if (!s) return 'unknown';
	const states = s.jobs.map((j) => j.status);
	if (states.some((st) => st === 'failed')) return 'broken';
	if (states.some((st) => st === 'degraded')) return 'degraded';
	if (states.some((st) => st === 'running')) return 'ok';
	if (s.jobs.length > 0 && states.every((st) => st === 'success')) return 'ok';
	return 'unknown';
}

export const systemStatus = {
	get value() {
		return status;
	},
	get available() {
		return available;
	},
	get lastUpdated() {
		return lastUpdated;
	},
	refresh: fetchOnce
};

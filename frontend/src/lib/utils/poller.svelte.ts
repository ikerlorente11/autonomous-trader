import { onDestroy } from 'svelte';
import { ApiError } from '../api/client';

export interface Resource<T> {
	readonly data: T | null;
	readonly error: ApiError | Error | null;
	readonly loading: boolean;
	readonly lastUpdated: number | null;
	refresh: () => Promise<void>;
}

interface PollOptions {
	// Polling interval in ms. Omit/0 to fetch once.
	intervalMs?: number;
	// Pause polling when the document is hidden (default true).
	pauseWhenHidden?: boolean;
	immediate?: boolean;
}

// Stale-while-revalidate resource. Keeps previous data on refresh error.
// Auto-clears its interval on component destroy.
export function createResource<T>(loader: () => Promise<T>, options: PollOptions = {}): Resource<T> {
	const { intervalMs = 0, pauseWhenHidden = true, immediate = true } = options;

	let data = $state<T | null>(null);
	let error = $state<ApiError | Error | null>(null);
	let loading = $state(false);
	let lastUpdated = $state<number | null>(null);
	let timer: ReturnType<typeof setInterval> | null = null;
	let inFlight = false;

	async function refresh() {
		if (inFlight) return;
		inFlight = true;
		loading = true;
		try {
			const result = await loader();
			data = result;
			error = null;
			lastUpdated = Date.now();
		} catch (e) {
			error = e instanceof Error ? e : new Error(String(e));
		} finally {
			loading = false;
			inFlight = false;
		}
	}

	function tick() {
		if (pauseWhenHidden && typeof document !== 'undefined' && document.hidden) return;
		void refresh();
	}

	if (immediate) void refresh();

	if (intervalMs > 0 && typeof window !== 'undefined') {
		timer = setInterval(tick, intervalMs);
		try {
			onDestroy(() => {
				if (timer) clearInterval(timer);
				timer = null;
			});
		} catch {
			// onDestroy only valid during component init; safe to ignore otherwise.
		}
	}

	return {
		get data() {
			return data;
		},
		get error() {
			return error;
		},
		get loading() {
			return loading;
		},
		get lastUpdated() {
			return lastUpdated;
		},
		refresh
	};
}

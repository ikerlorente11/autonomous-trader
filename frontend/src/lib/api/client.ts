import type { ApiErrorEnvelope } from './types';

export class ApiError extends Error {
	code: string;
	status: number;
	constructor(code: string, message: string, status: number) {
		super(message);
		this.name = 'ApiError';
		this.code = code;
		this.status = status;
	}
}

const BASE = '/api';
const DEFAULT_TIMEOUT_MS = 15_000;

function buildQuery(params?: Record<string, string | number | undefined | null>): string {
	if (!params) return '';
	const usp = new URLSearchParams();
	for (const [k, v] of Object.entries(params)) {
		if (v !== undefined && v !== null && v !== '') usp.set(k, String(v));
	}
	const s = usp.toString();
	return s ? `?${s}` : '';
}

async function request<T>(
	path: string,
	opts: {
		method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
		params?: Record<string, string | number | undefined | null>;
		body?: unknown;
		fetcher?: typeof fetch;
		timeoutMs?: number;
	} = {}
): Promise<T> {
	const f = opts.fetcher ?? fetch;
	const url = `${BASE}${path}${buildQuery(opts.params)}`;
	const headers: Record<string, string> = { Accept: 'application/json' };
	const init: RequestInit = { method: opts.method ?? 'GET', headers };
	if (opts.body !== undefined) {
		headers['Content-Type'] = 'application/json';
		init.body = JSON.stringify(opts.body);
	}
	const timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS;
	const controller = new AbortController();
	init.signal = controller.signal;
	const timer = setTimeout(() => controller.abort(), timeoutMs);
	let res: Response;
	try {
		res = await f(url, init);
	} catch (e) {
		if (controller.signal.aborted) {
			throw new ApiError('TIMEOUT', `Request timed out after ${timeoutMs} ms`, 0);
		}
		throw new ApiError('NETWORK', e instanceof Error ? e.message : 'Network request failed', 0);
	} finally {
		clearTimeout(timer);
	}

	if (!res.ok) {
		const code = res.status === 404 ? 'NOT_FOUND' : 'INTERNAL';
		let message = `Request failed (${res.status})`;
		try {
			const body = (await res.json()) as ApiErrorEnvelope;
			// Support both a custom {error:{code,message}} envelope and FastAPI's {detail}.
			if (body?.error?.message) {
				message = body.error.message;
			} else if (typeof body?.detail === 'string') {
				message = body.detail;
			}
		} catch {
			// non-JSON error body; keep default message
		}
		throw new ApiError(code, message, res.status);
	}

	if (res.status === 204) return undefined as T;

	try {
		return (await res.json()) as T;
	} catch {
		throw new ApiError('PARSE', 'Response was not valid JSON', res.status);
	}
}

export const api = {
	get: request,
	post: <T>(path: string, body?: unknown, fetcher?: typeof fetch) =>
		request<T>(path, { method: 'POST', body, fetcher }),
	patch: <T>(path: string, body?: unknown, fetcher?: typeof fetch) =>
		request<T>(path, { method: 'PATCH', body, fetcher }),
	del: <T>(path: string, fetcher?: typeof fetch) =>
		request<T>(path, { method: 'DELETE', fetcher })
};

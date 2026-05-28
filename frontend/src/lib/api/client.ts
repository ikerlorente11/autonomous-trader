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
	opts: { params?: Record<string, string | number | undefined | null>; fetcher?: typeof fetch } = {}
): Promise<T> {
	const f = opts.fetcher ?? fetch;
	const url = `${BASE}${path}${buildQuery(opts.params)}`;
	let res: Response;
	try {
		res = await f(url, { headers: { Accept: 'application/json' } });
	} catch (e) {
		throw new ApiError('NETWORK', e instanceof Error ? e.message : 'Network request failed', 0);
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

	try {
		return (await res.json()) as T;
	} catch {
		throw new ApiError('PARSE', 'Response was not valid JSON', res.status);
	}
}

export const api = {
	get: request
};

import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Dev proxy target for /api. In Docker dev it's the api service (http://api:8000);
// on the host it defaults to the published port (http://localhost:8080).
const API_PROXY = process.env.VITE_API_PROXY ?? 'http://localhost:8080';

// When the dev server is reached through a reverse proxy / subdomain, Vite must
// (a) accept the proxied Host header and (b) point the HMR websocket at the public
// origin instead of the internal container port. Both are env-driven so the static
// production build (which ignores `server`) is unaffected.
const ALLOWED_HOSTS = process.env.VITE_ALLOWED_HOSTS; // CSV of hostnames, or "all"
const HMR_HOST = process.env.VITE_HMR_HOST; // public hostname of the subdomain
const HMR_CLIENT_PORT = process.env.VITE_HMR_CLIENT_PORT; // 443 behind a TLS proxy
const HMR_PROTOCOL = process.env.VITE_HMR_PROTOCOL; // "wss" behind a TLS proxy

const allowedHosts =
	ALLOWED_HOSTS === 'all'
		? true
		: ALLOWED_HOSTS?.split(',')
				.map((h) => h.trim())
				.filter(Boolean);

const hmr = HMR_HOST
	? {
			host: HMR_HOST,
			...(HMR_CLIENT_PORT ? { clientPort: Number(HMR_CLIENT_PORT) } : {}),
			...(HMR_PROTOCOL ? { protocol: HMR_PROTOCOL } : {})
		}
	: undefined;

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		...(allowedHosts ? { allowedHosts } : {}),
		...(hmr ? { hmr } : {}),
		proxy: {
			'/api': {
				target: API_PROXY,
				changeOrigin: true
			}
		}
	}
});

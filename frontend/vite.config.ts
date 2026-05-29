import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Dev proxy target for /api. In Docker dev it's the api service (http://api:8000);
// on the host it defaults to the published port (http://localhost:8080).
const API_PROXY = process.env.VITE_API_PROXY ?? 'http://localhost:8080';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		proxy: {
			'/api': {
				target: API_PROXY,
				changeOrigin: true
			}
		}
	}
});

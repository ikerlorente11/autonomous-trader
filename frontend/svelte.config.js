import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Served as static files by FastAPI (StaticFiles, html=True). No SSR.
		// SPA fallback lets client-side routes (incl. /market/[symbol]) resolve
		// without per-route prerendered HTML, since data is fetched at runtime.
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',
			precompress: false,
			strict: false
		})
	}
};

export default config;

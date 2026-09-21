import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Force runes mode for app code (Svelte 5). Can be removed in Svelte 6.
		runes: true
	},
	kit: {
		// GitHub Pages (project site): BASE_PATH=/hack_max при релизной сборке.
		// Локально BASE_PATH пустой → http://localhost:5173/
		paths: {
			base: process.env.BASE_PATH ?? ''
		},
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			// GH Pages отдаёт 404.html для неизвестных путей — SPA fallback.
			fallback: '404.html',
			precompress: false,
			strict: true
		})
	}
};

export default config;

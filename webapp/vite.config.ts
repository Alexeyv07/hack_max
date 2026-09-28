import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, process.cwd(), '');
	const apiTarget = env.API_PROXY_TARGET || 'http://127.0.0.1:8000';
	/** Через CloudPub HMR/full-reload убивают Max WebView (белый экран, сброс экрана, 502). */
	const disableHmr = env.DISABLE_HMR === '1' || env.DISABLE_HMR === 'true';

	const proxy = {
		'/api': {
			target: apiTarget,
			changeOrigin: true,
			rewrite: (path: string) => path.replace(/^\/api/, '')
		},
		// Same-origin тайлы для превью в ленте (Max WebView часто режет сторонние img).
		'/map-tiles/esri': {
			target: 'https://server.arcgisonline.com',
			changeOrigin: true,
			rewrite: (path: string) =>
				path.replace(
					/^\/map-tiles\/esri/,
					'/ArcGIS/rest/services/World_Street_Map/MapServer/tile'
				)
		}
	};

	return {
		plugins: [sveltekit()],
		server: {
			// CloudPub (и любой туннель) ходит с чужим Host — иначе Vite 403.
			allowedHosts: true,
			proxy,
			...(disableHmr
				? {
						hmr: false,
						// Не релоадить страницу при правках на хосте (volume mount).
						watch: null
					}
				: {})
		},
		preview: {
			allowedHosts: true,
			proxy
		}
	};
});

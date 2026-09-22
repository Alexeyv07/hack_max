import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, process.cwd(), '');
	const apiTarget = env.API_PROXY_TARGET || 'http://127.0.0.1:8000';

	const proxy = {
		'/api': {
			target: apiTarget,
			changeOrigin: true,
			rewrite: (path: string) => path.replace(/^\/api/, '')
		}
	};

	return {
		plugins: [sveltekit()],
		server: {
			proxy
		},
		preview: {
			proxy
		}
	};
});

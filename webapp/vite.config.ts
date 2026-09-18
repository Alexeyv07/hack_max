import adapter from '@sveltejs/adapter-auto';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, process.cwd(), '');
	const apiTarget = env.API_PROXY_TARGET || 'http://127.0.0.1:8000';

	return {
		plugins: [
			sveltekit({
				compilerOptions: {
					// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
					runes: ({ filename }) =>
						filename.split(/[/\\]/).includes('node_modules') ? undefined : true
				},

				// adapter-auto only supports some environments, see https://svelte.dev/docs/kit/adapter-auto for a list.
				// If your environment is not supported, or you settled on a specific environment, switch out the adapter.
				// See https://svelte.dev/docs/kit/adapters for more information about adapters.
				adapter: adapter()
			})
		],
		server: {
			// Max/ngrok ходят с Host: *.ngrok-free.dev — иначе Vite отвечает 403.
			allowedHosts: true,
			proxy: {
				'/api': {
					target: apiTarget,
					changeOrigin: true,
					rewrite: (path) => path.replace(/^\/api/, ''),
					headers: {
						'ngrok-skip-browser-warning': 'true'
					}
				}
			}
		}
	};
});

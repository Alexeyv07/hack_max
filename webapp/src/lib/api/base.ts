import { env } from '$env/dynamic/public';

/**
 * База API без завершающего `/`.
 * По умолчанию `/api` (Vite proxy → backend на :8000).
 */
export function apiBase(): string {
	const raw = (env.PUBLIC_API_BASE || '/api').trim();
	return raw.replace(/\/$/, '') || '/api';
}

/** Собрать URL бэкенда: `apiUrl('/events/feed')`. */
export function apiUrl(path: string): string {
	const p = path.startsWith('/') ? path : `/${path}`;
	return `${apiBase()}${p}`;
}

import { requireMaxUserId } from '$lib/maxUser';
import type { FeedResponse, FeedScope } from '$lib/types/event';

const API_BASE = '/api';

/** Пропуск interstitial ngrok на free-домене. */
const NGROK_SKIP = { 'ngrok-skip-browser-warning': 'true' };

export async function fetchFeed(
	scope: FeedScope,
	opts: { cursor?: string | null; limit?: number; signal?: AbortSignal } = {}
): Promise<FeedResponse> {
	const userId = requireMaxUserId();
	const params = new URLSearchParams({
		scope,
		limit: String(opts.limit ?? 20)
	});
	if (opts.cursor) {
		params.set('cursor', opts.cursor);
	}

	const response = await fetch(`${API_BASE}/events/feed?${params}`, {
		headers: {
			'X-Max-User-Id': String(userId),
			Accept: 'application/json',
			...NGROK_SKIP
		},
		signal: opts.signal
	});

	if (!response.ok) {
		const detail = await response.text().catch(() => '');
		throw new Error(`Лента ${scope}: HTTP ${response.status}${detail ? ` — ${detail}` : ''}`);
	}

	return (await response.json()) as FeedResponse;
}

import { apiUrl } from '$lib/api/base';
import { requireMaxUserId } from '$lib/maxUser';
import type { FeedResponse, FeedScope, MapResponse } from '$lib/types/event';

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

	const response = await fetch(`${apiUrl('/events/feed')}?${params}`, {
		headers: {
			'X-Max-User-Id': String(userId),
			Accept: 'application/json'
		},
		signal: opts.signal
	});

	if (!response.ok) {
		const detail = await response.text().catch(() => '');
		throw new Error(`Лента ${scope}: HTTP ${response.status}${detail ? ` — ${detail}` : ''}`);
	}

	return (await response.json()) as FeedResponse;
}

export async function fetchEventMap(signal?: AbortSignal): Promise<MapResponse> {
	const userId = requireMaxUserId();
	const response = await fetch(apiUrl('/events/map'), {
		headers: { 'X-Max-User-Id': String(userId), Accept: 'application/json' },
		signal
	});
	if (!response.ok) throw new Error(`Карта событий: HTTP ${response.status}`);
	return (await response.json()) as MapResponse;
}

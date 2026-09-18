/** Типы ответа GET /events/feed (KAN-14 / KAN-16). */

export type FeedScope = 'nearby' | 'city';

export type FeedItem = {
	id: number;
	title: string;
	body: string;
	importance: number;
	source: string;
	lat: number | null;
	lon: number | null;
	weight: number;
	source_msg_id: string | null;
	disaster_flag: boolean;
	source_url: string | null;
	image_url: string | null;
	geo_by: string | null;
	location: string | null;
	published_at: string | null;
	created_at: string | null;
	updated_at: string | null;
	distance_m: number | null;
};

export type FeedResponse = {
	items: FeedItem[];
	scope: FeedScope;
	next_cursor: string | null;
	count: number;
};

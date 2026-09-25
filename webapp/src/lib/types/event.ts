/** Типы ответа GET /events/feed (KAN-14 / KAN-16). */

export type FeedScope = 'nearby' | 'city';

export type ProximityBand = 'home' | 'block' | 'street' | 'district';

export type FeedItem = {
	id: number;
	title: string | null;
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
	active_from?: string | null;
	active_to?: string | null;
	created_at: string | null;
	updated_at: string | null;
	distance_m: number | null;
	proximity?: ProximityBand | null;
	same_street?: boolean;
	is_active_now?: boolean | null;
};

export type FeedOrigin = {
	lat: number;
	lon: number;
	radius_m: number;
	chat_count: number;
};

export type FeedResponse = {
	items: FeedItem[];
	scope: FeedScope;
	next_cursor: string | null;
	count: number;
	origin?: FeedOrigin | null;
};

/** Ответ GET /events/map. */
export type MapPoint = {
	id: number;
	title: string | null;
	body: string | null;
	lat: number;
	lon: number;
	importance: number;
	category: 'catastrophe' | 'important';
	disaster_flag: boolean;
	geo_by: string | null;
	location: string | null;
};

export type MapResponse = { items: MapPoint[]; count: number };

import type { FeedItem, MapPoint } from '$lib/types/event';

export const MOSCOW_CENTER: [number, number] = [37.6173, 55.7558];

/** City-only geocoding is not an event location: do not pin it to the city centre. */
export function hasEventLocation(event: Pick<FeedItem, 'lat' | 'lon' | 'geo_by'>): boolean {
	return (
		(event.geo_by === 'street' || event.geo_by === 'home') &&
		typeof event.lat === 'number' &&
		typeof event.lon === 'number' &&
		Number.isFinite(event.lat) &&
		Number.isFinite(event.lon) &&
		Math.abs(event.lat) <= 90 &&
		Math.abs(event.lon) <= 180
	);
}

export function eventPoint(event: FeedItem): MapPoint | null {
	if (!hasEventLocation(event)) return null;
	return {
		id: event.id,
		title: event.title,
		body: event.body,
		lat: event.lat as number,
		lon: event.lon as number,
		importance: event.importance,
		category: event.disaster_flag || event.importance === 1 ? 'catastrophe' : 'important',
		disaster_flag: event.disaster_flag,
		geo_by: event.geo_by,
		location: event.location
	};
}

export function makeEventMarker(
	point: MapPoint,
	options: { selected?: boolean; onSelect?: () => void } = {}
): HTMLElement {
	const marker = options.onSelect ? document.createElement('button') : document.createElement('div');
	if (marker instanceof HTMLButtonElement) marker.type = 'button';
	marker.className = 'event-map-marker';
	marker.dataset.priority = point.disaster_flag || point.importance === 1 ? 'high' : 'important';
	marker.dataset.selected = options.selected ? 'true' : 'false';
	marker.dataset.precision = point.geo_by === 'street' ? 'street' : 'home';
	marker.setAttribute(
		'aria-label',
		`${point.geo_by === 'street' ? 'Примерное место события' : 'Показать событие'}: ${point.title || 'Без заголовка'}`
	);
	const symbol = document.createElement('span');
	symbol.textContent = point.disaster_flag ? '!' : '•';
	marker.appendChild(symbol);
	if (options.onSelect) marker.addEventListener('click', options.onSelect);
	return marker;
}

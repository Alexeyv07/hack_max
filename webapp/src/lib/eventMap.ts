import type { FeedItem, MapPoint } from '$lib/types/event';
import type { YandexMapInstance, YandexMapsApi, YandexPolygonGeometry } from '$lib/yandexMaps';

export type MapEvent = Pick<
	FeedItem,
	'id' | 'title' | 'importance' | 'disaster_flag' | 'lat' | 'lon' | 'geo_by' | 'location'
> & { body: string | null };

export const MOSCOW_CENTER: [number, number] = [37.6173, 55.7558];

// Условный визуальный масштаб для улицы, НЕ радиус, в пределах которого точно произошло событие.
export const STREET_CONTEXT_RADIUS_M = 800;

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

export function eventPoint(event: MapEvent): MapPoint | null {
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

/** Геодезический круг для контекста карты, а не геометрия улицы или зона достоверности. */
export function streetContextGeometry(point: Pick<MapPoint, 'lat' | 'lon'>): YandexPolygonGeometry {
	const earthRadiusM = 6_371_000;
	const angularDistance = STREET_CONTEXT_RADIUS_M / earthRadiusM;
	const lat1 = (point.lat * Math.PI) / 180;
	const lon1 = (point.lon * Math.PI) / 180;
	const ring: [number, number][] = [];
	for (let i = 0; i <= 64; i += 1) {
		const bearing = (2 * Math.PI * i) / 64;
		const lat2 = Math.asin(
			Math.sin(lat1) * Math.cos(angularDistance) +
				Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearing)
		);
		const lon2 =
			lon1 +
			Math.atan2(
				Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(lat1),
				Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2)
			);
		ring.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
	}
	return { type: 'Polygon', coordinates: [ring] };
}

/** Дом: точечный маркер. Улица: только условная размытая область, без ложной «точки события». */
export function addEventGeography(
	map: YandexMapInstance,
	ymaps3: YandexMapsApi,
	event: MapEvent,
	options: { selected?: boolean; onSelect?: () => void } = {}
) {
	const point = eventPoint(event);
	if (!point) return;
	if (event.geo_by === 'street') {
		const color = event.disaster_flag || event.importance === 1 ? '#e53935' : '#fb8c00';
		map.addChild(
			new ymaps3.YMapFeature({
				geometry: streetContextGeometry(point),
				style: {
					fill:
						event.disaster_flag || event.importance === 1
							? 'rgba(229, 57, 53, 0.13)'
							: 'rgba(251, 140, 0, 0.13)',
					stroke: [{ color, width: 2, dash: [6, 8] }],
					simplificationRate: 0
				}
			})
		);
		const label = makeEventMarker(point, options);
		label.classList.add('event-map-street-dot');
		label.dataset.precision = 'street';
		label.firstElementChild!.textContent = '';
		label.firstElementChild!.setAttribute('aria-hidden', 'true');
		label.setAttribute(
			'aria-label',
			`Событие на улице: ${point.title || 'Без заголовка'}. Место приблизительное`
		);
		map.addChild(new ymaps3.YMapMarker({ coordinates: [point.lon, point.lat] }, label));
		return label;
	}
	const marker = makeEventMarker(point, { selected: true, ...options });
	map.addChild(new ymaps3.YMapMarker({ coordinates: [point.lon, point.lat] }, marker));
	return marker;
}

export function eventMapZoom(event: MapEvent): number {
	if (eventPoint(event)) return event.geo_by === 'street' ? 12 : 15;
	return event.geo_by === 'city' ? 9 : 10;
}

export function makeEventMarker(
	point: MapPoint,
	options: { selected?: boolean; onSelect?: () => void } = {}
): HTMLElement {
	const marker = options.onSelect
		? document.createElement('button')
		: document.createElement('div');
	if (marker instanceof HTMLButtonElement) marker.type = 'button';
	marker.className = 'event-map-marker';
	marker.dataset.priority = point.disaster_flag || point.importance === 1 ? 'high' : 'important';
	marker.dataset.selected = options.selected ? 'true' : 'false';
	marker.dataset.precision = 'home';
	marker.setAttribute('aria-label', `Показать событие: ${point.title || 'Без заголовка'}`);
	const symbol = document.createElement('span');
	symbol.textContent = point.disaster_flag ? '!' : '•';
	marker.appendChild(symbol);
	if (options.onSelect) marker.addEventListener('click', options.onSelect);
	return marker;
}

/** Custom DOM content is supported by YMapMarker; no emoji font dependency. */
export function makeHomeMarker(address: string): HTMLElement {
	const marker = document.createElement('div');
	marker.className = 'home-map-marker';
	marker.setAttribute('role', 'img');
	marker.setAttribute('aria-label', `Ваш дом: ${address}`);
	marker.title = `Ваш дом: ${address}`;
	marker.innerHTML =
		'<span><svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="currentColor" d="M12 3 2 11l1.5 1.8L5 11.6V21h5v-6h4v6h5v-9.4l1.5 1.2L22 11 12 3Z"/></svg></span>';
	return marker;
}

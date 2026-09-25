<script lang="ts">
	import { HIDE_YANDEX_ATTRIBUTION } from '$lib/mapAppearance';
	import { onMount, untrack } from 'svelte';
	import { fetchEventMap } from '$lib/api/events';
	import { fetchResidence, type AddressOption } from '$lib/api/chatLink';
	import {
		addEventGeography,
		eventMapZoom,
		eventPoint,
		makeHomeMarker,
		MOSCOW_CENTER,
		type MapEvent
	} from '$lib/eventMap';
	import type { FeedItem } from '$lib/types/event';
	import { loadYandexMaps, type YandexMapInstance, type YandexMapsApi } from '$lib/yandexMaps';

	let { event, onclose }: { event: FeedItem; onclose: () => void } = $props();
	let mapElement: HTMLDivElement;
	let dialogElement: HTMLDivElement;
	let map: YandexMapInstance | null = null;
	let api: YandexMapsApi | null = null;
	let selected = $state<MapEvent>(untrack(() => event));
	let viewingHome = $state(false);
	let detailsCollapsed = $state(false);
	let home = $state<AddressOption | null>(null);
	let homeStatus = $state('Загрузка дома…');
	let eventsStatus = $state('Загрузка событий…');
	let loaded = $state(false);
	let error = $state('');
	const located = $derived(eventPoint(selected) !== null);
	const markers = new Map<number, HTMLElement>();

	function selectEvent(next: MapEvent) {
		viewingHome = false;
		detailsCollapsed = false;
		selected = next;
		for (const [id, marker] of markers) marker.dataset.selected = String(id === next.id);
		const location = eventPoint(next);
		if (location)
			map?.update({
				location: {
					center: [location.lon, location.lat],
					zoom: eventMapZoom(next),
					duration: 350
				}
			});
	}

	function returnHome() {
		viewingHome = true;
		detailsCollapsed = false;
		if (home)
			map?.update({
				location: {
					center: [home.longitude, home.latitude],
					zoom: 16,
					duration: 400
				}
			});
	}

	function addEvent(item: MapEvent) {
		if (!map || !api) return;
		const marker = addEventGeography(map, api, item, {
			selected: item.id === selected.id,
			onSelect: () => selectEvent(item)
		});
		if (marker) markers.set(item.id, marker);
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			onclose();
		}
		if (e.key !== 'Tab') return;
		const buttons = [
			...dialogElement.querySelectorAll<HTMLElement>(
				'button:not(:disabled), a[href], [tabindex="0"]'
			)
		];
		const first = buttons[0],
			last = buttons.at(-1);
		if (!first || !last) return;
		if (
			e.shiftKey &&
			(document.activeElement === first || document.activeElement === dialogElement)
		) {
			e.preventDefault();
			last.focus();
		} else if (
			!e.shiftKey &&
			(document.activeElement === last || document.activeElement === dialogElement)
		) {
			e.preventDefault();
			first.focus();
		}
	}

	onMount(() => {
		let disposed = false;
		const abort = new AbortController();
		const previousFocus = document.activeElement;
		dialogElement.focus({ preventScroll: true });
		// Settle independently: an unavailable home must not prevent displaying events.
		const eventsRequest = fetchEventMap(abort.signal).then(
			(value) => ({ value }),
			() => ({ value: null })
		);
		const homeRequest = fetchResidence(abort.signal).then(
			(value) => ({ value, failed: false }),
			() => ({ value: null, failed: true })
		);
		void (async () => {
			try {
				api = await loadYandexMaps();
				if (disposed) return;
				const initialPoint = eventPoint(event);
				map = new api.YMap(mapElement, {
					location: {
						center: initialPoint ? [initialPoint.lon, initialPoint.lat] : MOSCOW_CENTER,
						zoom: eventMapZoom(event)
					},
					behaviors: ['drag', 'pinchZoom', 'scrollZoom', 'dblClick', 'oneFingerZoom'],
					theme: 'dark',
					distribution: !HIDE_YANDEX_ATTRIBUTION,
					copyrightsPosition: 'bottom right',
					distributionPosition: 'bottom left'
				});
				map.addChild(new api.YMapDefaultSchemeLayer({}));
				map.addChild(new api.YMapDefaultFeaturesLayer({}));
				addEvent(event);
				loaded = true;
				void eventsRequest.then(({ value }) => {
					if (disposed) return;
					if (!value) {
						eventsStatus = 'Остальные события не загрузились. Откройте карту ещё раз.';
						return;
					}
					for (const item of value.items) if (item.id !== event.id) addEvent(item);
					eventsStatus = '';
				});
				void homeRequest.then(({ value, failed }) => {
					if (disposed || !map || !api) return;
					home = value;
					if (home && Number.isFinite(home.latitude) && Number.isFinite(home.longitude)) {
						map.addChild(
							new api.YMapMarker(
								{ coordinates: [home.longitude, home.latitude] },
								makeHomeMarker(home.address_text)
							)
						);
						homeStatus = '';
					} else {
						home = null;
						homeStatus = failed ? 'Дом не загрузился' : 'Дом не выбран';
					}
				});
			} catch (cause) {
				if (!disposed) {
					error = cause instanceof Error ? cause.message : 'Не удалось загрузить карту';
					abort.abort();
				}
			}
		})();
		return () => {
			disposed = true;
			abort.abort();
			map?.destroy();
			map = null;
			markers.clear();
			if (previousFocus instanceof HTMLElement && previousFocus.isConnected)
				previousFocus.focus({ preventScroll: true });
		};
	});
</script>

<svelte:window onkeydown={onKeydown} />

<div
	class="fullscreen"
	class:compact-map={HIDE_YANDEX_ATTRIBUTION}
	bind:this={dialogElement}
	tabindex="-1"
	role="dialog"
	aria-modal="true"
	aria-label="Карта событий"
	ontouchstart={(e) => e.stopPropagation()}
	ontouchend={(e) => e.stopPropagation()}
>
	<div class="map" class:yandex-map-clean={HIDE_YANDEX_ATTRIBUTION} bind:this={mapElement}></div>
	{#if !loaded}
		<div class="map-loading" aria-live="polite">
			{error || 'Загрузка карты…'}
		</div>
	{/if}

	<div class="toolbar">
		<button class="back" type="button" onclick={onclose} aria-label="Назад к ленте">
			<span aria-hidden="true">←</span> Назад
		</button>
		<span class="toolbar-title">Карта событий</span>
		<button
			class="back home-button"
			type="button"
			disabled={!loaded || !home}
			onclick={returnHome}
			title={home ? home.address_text : homeStatus}
			aria-label={home ? 'Вернуться к дому' : homeStatus}
		>
			<span aria-hidden="true">⌂</span> К дому
		</button>
	</div>

	{#if loaded && (eventsStatus || homeStatus)}
		<div class="status" role="status">{eventsStatus || homeStatus}</div>
	{/if}

	<section class="details" class:collapsed={detailsCollapsed} aria-label="Описание на карте">
		<button
			class="details-toggle"
			type="button"
			aria-expanded={!detailsCollapsed}
			aria-controls="map-details-content"
			onclick={() => (detailsCollapsed = !detailsCollapsed)}
			aria-label={detailsCollapsed ? 'Развернуть описание' : 'Свернуть описание'}
		>
			<span class="details-title">
				{#if !viewingHome}<span
						class="dot"
						class:important={selected.importance === 2 && !selected.disaster_flag}
					></span>{/if}
				<span class="details-heading"
					>{viewingHome && home ? 'Ваш дом' : selected.title || 'Событие'}</span
				>
			</span>
			<span class="details-chevron" aria-hidden="true">{detailsCollapsed ? '▲' : '▼'}</span>
		</button>
		<div id="map-details-content" class="details-content" hidden={detailsCollapsed}>
			{#if viewingHome && home}
				<div class="details-location">{home.address_text}</div>
			{:else}
				{#if selected.location}<div class="details-location">⌖ {selected.location}</div>{/if}
				{#if selected.geo_by === 'city'}
					<div class="approximate">
						Известен только город. Точное место события неизвестно, поэтому маркер на карте не
						ставим.
					</div>
				{:else if !located}
					<div class="approximate">
						К сожалению, определить местоположение этого события не удалось.
					</div>
				{:else if selected.geo_by === 'street'}
					<div class="approximate">
						Известна только улица. Подсвеченный круг — условный ориентир, не границы улицы и не
						точное место события.
					</div>
				{/if}
				{#if selected.body}<p>{selected.body}</p>{/if}
			{/if}
		</div>
	</section>
</div>

<style>
	.fullscreen {
		position: fixed;
		inset: 0;
		z-index: 1000;
		width: 100vw;
		height: 100dvh;
		background: #152a30;
		color: #fff;
		touch-action: auto;
	}
	.map {
		position: absolute;
		inset: 0;
	}
	.map-loading {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		padding: 2rem;
		background: linear-gradient(145deg, #18313b, #263e3b);
		text-align: center;
	}
	.toolbar {
		position: absolute;
		z-index: 2;
		left: 0;
		right: 0;
		top: 0;
		padding: calc(0.85rem + env(safe-area-inset-top)) 1rem 0.9rem;
		background: linear-gradient(rgba(7, 17, 23, 0.78), transparent);
		display: flex;
		align-items: center;
		gap: 0.75rem;
		pointer-events: none;
	}
	.back {
		pointer-events: auto;
		border: 1px solid rgba(255, 255, 255, 0.23);
		border-radius: 12px;
		background: rgba(8, 24, 32, 0.82);
		backdrop-filter: blur(10px);
		color: #fff;
		font-weight: 700;
		padding: 0.65rem 1rem;
		cursor: pointer;
	}
	.back span {
		margin-right: 0.3rem;
		font-size: 1.2rem;
	}
	.home-button {
		margin-left: auto;
		white-space: nowrap;
	}
	.home-button:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.status {
		position: absolute;
		top: calc(4.7rem + env(safe-area-inset-top));
		left: 1rem;
		right: 1rem;
		padding: 0.4rem 0.65rem;
		border-radius: 8px;
		background: #102029e6;
		font-size: 0.75rem;
		pointer-events: none;
	}
	@media (max-width: 380px) {
		.toolbar-title {
			display: none;
		}
	}
	.toolbar-title {
		font-size: 0.88rem;
		font-weight: 700;
		text-shadow: 0 1px 5px #000;
	}
	.details {
		position: absolute;
		z-index: 2;
		/* Reserve attribution space when the presentation override is disabled. */
		bottom: calc(4.3rem + env(safe-area-inset-bottom));
		left: 1rem;
		right: 1rem;
		max-height: min(
			34dvh,
			calc(100dvh - 12rem - env(safe-area-inset-top) - env(safe-area-inset-bottom))
		);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		border: 1px solid rgba(255, 255, 255, 0.2);
		border-radius: 17px;
		padding: 0;
		background: rgba(12, 28, 35, 0.88);
		backdrop-filter: blur(16px);
		box-shadow: 0 9px 30px rgba(0, 0, 0, 0.3);
	}
	.compact-map .details {
		bottom: calc(1rem + env(safe-area-inset-bottom));
	}
	.details-toggle {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		width: 100%;
		min-height: 52px;
		padding: 0.85rem 1rem;
		border: 0;
		color: inherit;
		background: transparent;
		text-align: left;
		cursor: pointer;
	}
	.details-toggle:focus-visible {
		outline: 2px solid white;
		outline-offset: -4px;
		border-radius: 16px;
	}
	.details-heading {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}
	.details-chevron {
		flex-shrink: 0;
		font-size: 0.8rem;
	}
	.details-content {
		min-height: 0;
		padding: 0 1rem 1rem;
		overflow-y: auto;
		max-height: 24dvh;
	}
	.details-content[hidden] {
		display: none;
	}
	.details-title {
		font-weight: 750;
		display: flex;
		align-items: baseline;
		gap: 0.55rem;
		line-height: 1.4;
	}
	.dot {
		width: 0.6rem;
		height: 0.6rem;
		flex: 0 0 0.6rem;
		border-radius: 50%;
		background: #e53935;
	}
	.dot.important {
		background: #fb8c00;
	}
	.details-location {
		margin-top: 0.3rem;
		font-size: 0.75rem;
		opacity: 0.75;
	}
	.approximate {
		margin-top: 0.4rem;
		color: #d5e6ef;
		font-size: 0.76rem;
		line-height: 1.3;
	}
	.details p {
		margin: 0.45rem 0 0;
		font-size: 0.87rem;
		line-height: 1.45;
		white-space: pre-wrap;
	}
</style>

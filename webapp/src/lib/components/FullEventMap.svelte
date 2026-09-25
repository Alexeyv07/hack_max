<script lang="ts">
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
	let home = $state<AddressOption | null>(null);
	let homeStatus = $state('Загрузка дома…');
	let eventsStatus = $state('Загрузка событий…');
	let loaded = $state(false);
	let error = $state('');
	const point = $derived(eventPoint(selected));
	const located = $derived(point !== null);
	const markers = new Map<number, HTMLElement>();

	function selectEvent(next: MapEvent) {
		viewingHome = false;
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
	bind:this={dialogElement}
	tabindex="-1"
	role="dialog"
	aria-modal="true"
	aria-label="Карта событий"
	ontouchstart={(e) => e.stopPropagation()}
	ontouchend={(e) => e.stopPropagation()}
>
	<div class="map" bind:this={mapElement}></div>
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

	{#if viewingHome && home}
		<div class="details">
			<div class="details-title">Ваш дом</div>
			<div class="details-location">{home.address_text}</div>
		</div>
	{:else if selected.geo_by === 'city'}
		<div class="no-location" role="status">
			<span aria-hidden="true">⌖</span>
			Известен только город{selected.location ? `: ${selected.location}` : ''}. Точное место события
			неизвестно, поэтому маркер на карте не ставим.
		</div>
	{:else if !located}
		<div class="no-location" role="status">
			<span aria-hidden="true">⌖</span>
			К сожалению, определить местоположение этого события не удалось.
		</div>
	{:else if point}
		<div class="details" aria-live="polite">
			<div class="details-title">
				<span class="dot" class:important={selected.importance === 2 && !selected.disaster_flag}
				></span>{selected.title || 'Событие'}
			</div>
			{#if selected.location}<div class="details-location">
					⌖ {selected.location}
				</div>{/if}
			{#if selected.geo_by === 'street'}
				<div class="approximate">
					Известна только улица. Подсвеченный круг — условный ориентир, не границы улицы и не точное
					место события.
				</div>
			{/if}
			{#if selected.body}<p>{selected.body}</p>{/if}
		</div>
	{/if}
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
	.no-location {
		position: absolute;
		z-index: 2;
		left: 1rem;
		right: 1rem;
		bottom: calc(4.3rem + env(safe-area-inset-bottom));
		border: 1px solid rgba(255, 255, 255, 0.25);
		border-radius: 18px;
		padding: 1.3rem;
		text-align: center;
		background: rgba(17, 32, 40, 0.78);
		backdrop-filter: blur(14px);
		box-shadow: 0 14px 40px rgba(0, 0, 0, 0.25);
		font-weight: 600;
		line-height: 1.4;
	}
	.no-location span {
		display: block;
		font-size: 2.3rem;
		margin-bottom: 0.4rem;
	}
	.details {
		position: absolute;
		z-index: 2;
		/* Чуть ниже, но нижние элементы Яндекс Карт остаются доступными. */
		bottom: calc(4.3rem + env(safe-area-inset-bottom));
		left: 1rem;
		right: 1rem;
		max-height: min(
			34dvh,
			calc(100dvh - 12rem - env(safe-area-inset-top) - env(safe-area-inset-bottom))
		);
		overflow-y: auto;
		border: 1px solid rgba(255, 255, 255, 0.2);
		border-radius: 17px;
		padding: 1rem;
		background: rgba(12, 28, 35, 0.88);
		backdrop-filter: blur(16px);
		box-shadow: 0 9px 30px rgba(0, 0, 0, 0.3);
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

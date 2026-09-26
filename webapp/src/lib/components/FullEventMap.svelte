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
			<svg class="btn-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
				<path
					fill="currentColor"
					fill-rule="evenodd"
					clip-rule="evenodd"
					d="M9.53 2.47a.75.75 0 0 1 0 1.06L4.81 8.25H15a6.75 6.75 0 0 1 0 13.5h-3a.75.75 0 0 1 0-1.5h3a5.25 5.25 0 1 0 0-10.5H4.81l4.72 4.72a.75.75 0 1 1-1.06 1.06l-6-6a.75.75 0 0 1 0-1.06l6-6a.75.75 0 0 1 1.06 0Z"
				/>
			</svg>
			Назад
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
			<svg class="btn-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
				<path
					fill="currentColor"
					d="M11.47 3.841a.75.75 0 0 1 1.06 0l8.69 8.69a.75.75 0 1 0 1.06-1.061l-8.689-8.69a2.25 2.25 0 0 0-3.182 0l-8.69 8.69a.75.75 0 1 0 1.061 1.06l8.69-8.689Z"
				/>
				<path
					fill="currentColor"
					d="m12 5.432 8.159 8.159c.03.03.06.058.091.086v6.198c0 1.035-.84 1.875-1.875 1.875H15a.75.75 0 0 1-.75-.75v-4.5a.75.75 0 0 0-.75-.75h-3a.75.75 0 0 0-.75.75V21a.75.75 0 0 1-.75.75H5.625a1.875 1.875 0 0 1-1.875-1.875v-6.198a2.29 2.29 0 0 0 .091-.086L12 5.432Z"
				/>
			</svg>
			К дому
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
			<span class="details-chevron" aria-hidden="true">
				{#if detailsCollapsed}
					<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
						<path
							fill="currentColor"
							fill-rule="evenodd"
							clip-rule="evenodd"
							d="M11.47 13.28a.75.75 0 0 0 1.06 0l7.5-7.5a.75.75 0 0 0-1.06-1.06L12 11.69 5.03 4.72a.75.75 0 0 0-1.06 1.06l7.5 7.5Z"
						/>
						<path
							fill="currentColor"
							fill-rule="evenodd"
							clip-rule="evenodd"
							d="M11.47 19.28a.75.75 0 0 0 1.06 0l7.5-7.5a.75.75 0 1 0-1.06-1.06L12 17.69l-6.97-6.97a.75.75 0 0 0-1.06 1.06l7.5 7.5Z"
						/>
					</svg>
				{:else}
					<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
						<path
							fill="currentColor"
							fill-rule="evenodd"
							clip-rule="evenodd"
							d="M11.47 10.72a.75.75 0 0 1 1.06 0l7.5 7.5a.75.75 0 1 1-1.06 1.06L12 12.31l-6.97 6.97a.75.75 0 0 1-1.06-1.06l7.5-7.5Z"
						/>
						<path
							fill="currentColor"
							fill-rule="evenodd"
							clip-rule="evenodd"
							d="M11.47 4.72a.75.75 0 0 1 1.06 0l7.5 7.5a.75.75 0 1 1-1.06 1.06L12 6.31l-6.97 6.97a.75.75 0 0 1-1.06-1.06l7.5-7.5Z"
						/>
					</svg>
				{/if}
			</span>
		</button>
		<div id="map-details-content" class="details-content" hidden={detailsCollapsed}>
			{#if viewingHome && home}
				<div class="details-location">{home.address_text}</div>
			{:else}
				{#if selected.location}<div class="details-location">{selected.location}</div>{/if}
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
		background: var(--bg-canvas);
		color: var(--text-primary);
		touch-action: auto;
		font-family: var(--font);
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
		padding: var(--space-8);
		background: var(--bg-surface);
		color: var(--text-secondary);
		font-size: var(--fs-14);
		text-align: center;
	}
	.toolbar {
		position: absolute;
		z-index: 2;
		left: 0;
		right: 0;
		top: 0;
		padding: calc(8px + env(safe-area-inset-top)) 12px 8px;
		background: var(--bg-canvas);
		border-bottom: 1px solid var(--border);
		display: flex;
		align-items: center;
		gap: 8px;
		pointer-events: none;
	}
	.back {
		pointer-events: auto;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-md);
		background: var(--bg-elevated);
		color: var(--text-primary);
		font-weight: 500;
		font-size: var(--fs-14);
		padding: 8px 12px;
		min-height: 36px;
		cursor: pointer;
		transition: background var(--ease);
	}
	.back:hover:not(:disabled) {
		background: var(--bg-raised);
	}
	.btn-icon {
		flex-shrink: 0;
		display: block;
	}
	.home-button {
		margin-left: auto;
		white-space: nowrap;
	}
	.home-button:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.status {
		position: absolute;
		top: calc(56px + env(safe-area-inset-top));
		left: 12px;
		right: 12px;
		padding: 8px 12px;
		border-radius: var(--radius-md);
		border: 1px solid var(--border);
		background: var(--bg-elevated);
		color: var(--text-secondary);
		font-size: var(--fs-12);
		font-family: var(--font-mono);
		pointer-events: none;
	}
	@media (max-width: 380px) {
		.toolbar-title {
			display: none;
		}
	}
	.toolbar-title {
		font-size: var(--fs-14);
		font-weight: 500;
		color: var(--text-secondary);
	}
	.details {
		position: absolute;
		z-index: 2;
		bottom: calc(68px + env(safe-area-inset-bottom));
		left: 12px;
		right: 12px;
		max-height: min(
			34dvh,
			calc(100dvh - 12rem - env(safe-area-inset-top) - env(safe-area-inset-bottom))
		);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-lg);
		padding: 0;
		background: var(--bg-elevated);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
	}
	.compact-map .details {
		bottom: calc(12px + env(safe-area-inset-bottom));
	}
	.details-toggle {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		width: 100%;
		min-height: 48px;
		padding: 12px;
		border: 0;
		color: inherit;
		background: transparent;
		text-align: left;
		cursor: pointer;
		font: inherit;
	}
	.details-toggle:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
		border-radius: var(--radius-lg);
	}
	.details-heading {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		font-size: var(--fs-14);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.details-chevron {
		flex-shrink: 0;
		display: grid;
		place-items: center;
		color: var(--text-tertiary);
	}
	.details-content {
		min-height: 0;
		padding: 0 12px 12px;
		overflow-y: auto;
		max-height: 24dvh;
	}
	.details-content[hidden] {
		display: none;
	}
	.details-title {
		font-weight: 500;
		display: flex;
		align-items: baseline;
		gap: 8px;
		line-height: 1.4;
	}
	.dot {
		width: 8px;
		height: 8px;
		flex: 0 0 8px;
		border-radius: 50%;
		background: var(--danger);
	}
	.dot.important {
		background: var(--warning);
	}
	.details-location {
		margin-top: 4px;
		font-size: var(--fs-12);
		font-family: var(--font-mono);
		color: var(--text-tertiary);
	}
	.approximate {
		margin-top: 8px;
		color: var(--text-secondary);
		font-size: var(--fs-12);
		line-height: 1.4;
	}
	.details p {
		margin: 8px 0 0;
		font-size: var(--fs-14);
		line-height: 1.45;
		color: var(--text-secondary);
		white-space: pre-wrap;
	}
</style>

<script lang="ts">
	import { HIDE_YANDEX_ATTRIBUTION } from '$lib/mapAppearance';
	import { onMount } from 'svelte';
	import { addEventGeography, eventMapZoom, eventPoint, MOSCOW_CENTER } from '$lib/eventMap';
	import type { FeedItem } from '$lib/types/event';
	import { loadYandexMaps, type YandexMapInstance } from '$lib/yandexMaps';

	let { event }: { event: FeedItem } = $props();
	let mapElement: HTMLDivElement;
	let map: YandexMapInstance | null = null;
	let loadError = $state(false);
	let loaded = $state(false);
	const point = $derived(eventPoint(event));

	onMount(() => {
		let disposed = false;
		void (async () => {
			try {
				const ymaps3 = await loadYandexMaps();
				if (disposed) return;
				const initialPoint = eventPoint(event);
				map = new ymaps3.YMap(mapElement, {
					location: {
						center: initialPoint ? [initialPoint.lon, initialPoint.lat] : MOSCOW_CENTER,
						zoom: eventMapZoom(event)
					},
					behaviors: [],
					theme: 'dark',
					distribution: !HIDE_YANDEX_ATTRIBUTION,
					copyrightsPosition: 'bottom right'
				});
				map.addChild(new ymaps3.YMapDefaultSchemeLayer({}));
				map.addChild(new ymaps3.YMapDefaultFeaturesLayer({}));
				addEventGeography(map, ymaps3, event);
				loaded = true;
			} catch {
				if (!disposed) loadError = true;
			}
		})();
		return () => {
			disposed = true;
			map?.destroy();
			map = null;
		};
	});
</script>

<div class="preview" class:clean-preview={HIDE_YANDEX_ATTRIBUTION} aria-hidden="true">
	<div class="map" class:yandex-map-clean={HIDE_YANDEX_ATTRIBUTION} bind:this={mapElement}></div>
	{#if !loaded}
		<div class="waiting">{loadError ? 'Карта временно недоступна' : 'Загрузка карты…'}</div>
	{/if}
	{#if event.geo_by === 'street' && point}
		<div class="note">Только улица · область условная</div>
	{:else if event.geo_by === 'city'}
		<div class="note">Известен только город</div>
	{:else if !point}
		<div class="note">Место события не определено</div>
	{/if}
</div>

<style>
	.preview {
		position: relative;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: var(--bg-elevated);
	}
	.map {
		position: absolute;
		inset: 0;
		pointer-events: none;
	}
	.waiting {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		color: var(--text-secondary);
		font-size: var(--fs-14);
		background: var(--bg-surface);
	}
	.clean-preview .note {
		bottom: 12px;
	}
	.note {
		position: absolute;
		left: 12px;
		bottom: 4.3rem;
		max-width: calc(100% - 5rem);
		padding: 4px 8px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border);
		background: var(--bg-raised);
		color: var(--text-secondary);
		font-size: var(--fs-12);
		font-family: var(--font-mono);
		line-height: 1.35;
		pointer-events: none;
	}
</style>

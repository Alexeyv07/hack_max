<script lang="ts">
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

<div class="preview" aria-hidden="true">
	<div class="map" bind:this={mapElement}></div>
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
		background: #152b31;
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
		color: #d9e8ee;
		font-size: 0.9rem;
		background: linear-gradient(145deg, #142c36, #213d3c);
	}
	.note {
		position: absolute;
		left: 0.75rem;
		bottom: 0.75rem;
		max-width: calc(100% - 1.5rem);
		padding: 0.35rem 0.6rem;
		border-radius: 8px;
		background: rgba(11, 25, 31, 0.77);
		color: #fff;
		font-size: 0.73rem;
		line-height: 1.35;
		pointer-events: none;
	}
</style>

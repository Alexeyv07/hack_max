<script lang="ts">
	import { onMount } from 'svelte';
	import { eventPoint, hasEventLocation, makeEventMarker, MOSCOW_CENTER } from '$lib/eventMap';
	import type { FeedItem } from '$lib/types/event';
	import { loadYandexMaps, type YandexMapInstance } from '$lib/yandexMaps';

	let { event }: { event: FeedItem } = $props();
	let mapElement: HTMLDivElement;
	let map: YandexMapInstance | null = null;
	let loadError = $state(false);
	let loaded = $state(false);
	const located = $derived(hasEventLocation(event));

	onMount(() => {
		let disposed = false;
		void (async () => {
			try {
				const ymaps3 = await loadYandexMaps();
				if (disposed) return;
				const point = eventPoint(event);
				map = new ymaps3.YMap(mapElement, {
					location: {
						center: point ? [point.lon, point.lat] : MOSCOW_CENTER,
						zoom: point ? (event.geo_by === 'street' ? 13 : 15) : 10
					},
					behaviors: [],
					theme: 'dark',
					copyrightsPosition: 'bottom right'
				});
				map.addChild(new ymaps3.YMapDefaultSchemeLayer({}));
				map.addChild(new ymaps3.YMapDefaultFeaturesLayer({}));
				if (point) {
					const marker = makeEventMarker(point, { selected: true });
					map.addChild(new ymaps3.YMapMarker({ coordinates: [point.lon, point.lat] }, marker));
				}
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
	<div class="shade"></div>
	<div class="label">
		<span class="map-icon">⌖</span>
		<span>{!located
			? 'Место пока неизвестно · открыть карту'
			: event.geo_by === 'street'
				? 'Примерная точка на улице · открыть карту'
				: 'Место события · открыть карту'}</span>
		<span aria-hidden="true">↗</span>
	</div>
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
	.shade {
		position: absolute;
		inset: 0;
		pointer-events: none;
		background: linear-gradient(transparent 40%, rgba(5, 17, 22, 0.76));
	}
	.label {
		position: absolute;
		left: 0.75rem;
		right: 0.75rem;
		bottom: 0.75rem;
		display: flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.6rem 0.75rem;
		border: 1px solid rgba(255, 255, 255, 0.22);
		border-radius: 12px;
		background: rgba(11, 25, 31, 0.74);
		backdrop-filter: blur(10px);
		color: #fff;
		font-size: 0.8rem;
		font-weight: 600;
	}
	.label span:nth-child(2) {
		flex: 1;
	}
	.map-icon {
		font-size: 1.4rem;
		line-height: 0.8;
	}
</style>

<script lang="ts">
	import { onMount } from 'svelte';
	import { addEventGeography, eventMapZoom, eventPoint, MOSCOW_CENTER } from '$lib/eventMap';
	import type { FeedItem } from '$lib/types/event';
	import { loadYandexMaps, type YandexMapInstance } from '$lib/yandexMaps';

	let { event, onclose }: { event: FeedItem; onclose: () => void } = $props();
	let mapElement: HTMLDivElement;
	let dialogElement: HTMLDivElement;
	let map: YandexMapInstance | null = null;
	let loaded = $state(false);
	let error = $state('');
	const point = $derived(eventPoint(event));
	const located = $derived(point !== null);

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			onclose();
		}
	}

	onMount(() => {
		let disposed = false;
		dialogElement.focus({ preventScroll: true });
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
					behaviors: ['drag', 'pinchZoom', 'scrollZoom', 'dblClick', 'oneFingerZoom'],
					theme: 'dark',
					copyrightsPosition: 'bottom right'
				});
				map.addChild(new ymaps3.YMapDefaultSchemeLayer({}));
				map.addChild(new ymaps3.YMapDefaultFeaturesLayer({}));
				// Только география выбранного события. Для улицы — условная область, не точечный маркер.
				addEventGeography(map, ymaps3, event);
				loaded = true;
			} catch (cause) {
				if (!disposed) error = cause instanceof Error ? cause.message : 'Не удалось загрузить карту';
			}
		})();
		return () => {
			disposed = true;
			map?.destroy();
			map = null;
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
	aria-label="Карта события"
	ontouchstart={(e) => e.stopPropagation()}
	ontouchend={(e) => e.stopPropagation()}
>
	<div class="map" bind:this={mapElement}></div>
	{#if !loaded}
		<div class="map-loading" aria-live="polite">{error || 'Загрузка карты…'}</div>
	{/if}

	<div class="toolbar">
		<button class="back" type="button" onclick={onclose} aria-label="Назад к ленте">
			<span aria-hidden="true">←</span> Назад
		</button>
		<span class="toolbar-title">Карта события</span>
	</div>

	{#if event.geo_by === 'city'}
		<div class="no-location" role="status">
			<span aria-hidden="true">⌖</span>
			Известен только город{event.location ? `: ${event.location}` : ''}. Точное место события неизвестно, поэтому маркер на карте не ставим.
		</div>
	{:else if !located}
		<div class="no-location" role="status">
			<span aria-hidden="true">⌖</span>
			К сожалению, определить местоположение этого события не удалось.
		</div>
	{:else if point}
		<div class="details" aria-live="polite">
			<div class="details-title"><span class="dot" class:important={event.importance === 2 && !event.disaster_flag}></span>{event.title || 'Событие'}</div>
			{#if event.location}<div class="details-location">⌖ {event.location}</div>{/if}
			{#if event.geo_by === 'street'}
				<div class="approximate">Известна только улица. Подсвеченный круг — условный ориентир, не границы улицы и не точное место события.</div>
			{/if}
			{#if event.body}<p>{event.body}</p>{/if}
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
	.toolbar-title {
		font-size: 0.88rem;
		font-weight: 700;
		text-shadow: 0 1px 5px #000;
	}
	.no-location {
		position: absolute;
		z-index: 2;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		width: min(85vw, 22rem);
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
		max-height: min(34dvh, calc(100dvh - 12rem - env(safe-area-inset-top) - env(safe-area-inset-bottom)));
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

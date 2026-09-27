<script lang="ts">
	import { eventPoint, MOSCOW_CENTER } from '$lib/eventMap';
	import type { FeedItem } from '$lib/types/event';

	/** Превью карты в ленте без Yandex JS (чёрный canvas в Max) и без Static API
	 * (наш ключ — только JS, Static даёт 403). Тайлы Carto + пин. */
	let { event }: { event: FeedItem; active?: boolean } = $props();

	const TILE = 256;
	const ZOOM = 14;
	/** Сколько тайлов по стороне (нечётное — центр ровно на точке). */
	const GRID = 3;

	const point = $derived(eventPoint(event));
	const center = $derived(
		point ? { lat: point.lat, lon: point.lon } : { lat: MOSCOW_CENTER[1], lon: MOSCOW_CENTER[0] }
	);

	const tiles = $derived(buildTileGrid(center.lat, center.lon, ZOOM, GRID));
	const note = $derived.by(() => {
		if (event.geo_by === 'street' && point) return 'Только улица · область условная';
		if (event.geo_by === 'city') return 'Известен только город';
		if (!point) return 'Место события не определено';
		return event.location?.trim() || null;
	});

	function lon2tile(lon: number, z: number): number {
		return ((lon + 180) / 360) * 2 ** z;
	}

	function lat2tile(lat: number, z: number): number {
		const rad = (lat * Math.PI) / 180;
		return ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * 2 ** z;
	}

	function buildTileGrid(lat: number, lon: number, z: number, n: number) {
		const fx = lon2tile(lon, z);
		const fy = lat2tile(lat, z);
		const cx = Math.floor(fx);
		const cy = Math.floor(fy);
		const half = Math.floor(n / 2);
		const max = 2 ** z;
		const items: { key: string; src: string; col: number; row: number }[] = [];
		for (let row = 0; row < n; row += 1) {
			for (let col = 0; col < n; col += 1) {
				const tx = ((cx - half + col) % max + max) % max;
				const ty = Math.min(max - 1, Math.max(0, cy - half + row));
				const mirror = ['a', 'b', 'c', 'd'][(tx + ty) % 4];
				items.push({
					key: `${z}/${tx}/${ty}`,
					src: `https://${mirror}.basemaps.cartocdn.com/dark_all/${z}/${tx}/${ty}.png`,
					col,
					row
				});
			}
		}
		const offsetX = (0.5 - (fx - cx)) * TILE;
		const offsetY = (0.5 - (fy - cy)) * TILE;
		return {
			items,
			size: n * TILE,
			offsetX,
			offsetY
		};
	}
</script>

<div class="preview" aria-hidden="true">
	<div
		class="tiles"
		style:width="{tiles.size}px"
		style:height="{tiles.size}px"
		style:transform="translate(calc(-50% + {tiles.offsetX}px), calc(-50% + {tiles.offsetY}px))"
	>
		{#each tiles.items as tile (tile.key)}
			<img
				class="tile"
				src={tile.src}
				alt=""
				width={TILE}
				height={TILE}
				loading="lazy"
				decoding="async"
				style:grid-column={tile.col + 1}
				style:grid-row={tile.row + 1}
			/>
		{/each}
	</div>
	<div class="pin" class:muted={!point || event.geo_by === 'city'}>
		<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">
			<path
				fill="currentColor"
				d="M12 2.25c-3.728 0-6.75 2.94-6.75 6.563 0 4.687 5.25 11.062 6.262 12.23a.64.64 0 0 0 .976 0C13.5 19.875 18.75 13.5 18.75 8.813 18.75 5.19 15.728 2.25 12 2.25Zm0 9a2.437 2.437 0 1 1 0-4.875A2.437 2.437 0 0 1 12 11.25Z"
			/>
		</svg>
	</div>
	{#if note}
		<div class="note">{note}</div>
	{/if}
</div>

<style>
	.preview {
		position: relative;
		width: 100%;
		height: 100%;
		overflow: hidden;
		background: #1b2832;
	}

	.tiles {
		position: absolute;
		left: 50%;
		top: 50%;
		display: grid;
		grid-template-columns: repeat(3, 256px);
		grid-template-rows: repeat(3, 256px);
		pointer-events: none;
	}

	.tile {
		display: block;
		width: 256px;
		height: 256px;
		margin: 0;
		padding: 0;
		border: 0;
	}

	.pin {
		position: absolute;
		left: 50%;
		top: 50%;
		z-index: 2;
		transform: translate(-50%, -100%);
		color: #ef5350;
		filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.55));
	}

	.pin.muted {
		color: #90a4ae;
	}

	.note {
		position: absolute;
		left: 12px;
		bottom: 12px;
		z-index: 2;
		max-width: calc(100% - 5rem);
		padding: 4px 8px;
		border-radius: var(--radius-sm);
		border: 1px solid rgba(255, 255, 255, 0.12);
		background: rgba(12, 16, 20, 0.82);
		color: #d7dee3;
		font-size: var(--fs-12);
		font-family: var(--font-mono);
		line-height: 1.35;
		pointer-events: none;
	}
</style>

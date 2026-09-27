<script lang="ts">
	import { HIDE_YANDEX_ATTRIBUTION } from '$lib/mapAppearance';
	import type { FeedItem } from '$lib/types/event';
	import mapSearchIcon from '$lib/assets/map-search.svg';
	import EventMapPreview from '$lib/components/EventMapPreview.svelte';

	type Props = {
		event: FeedItem;
		/** Активный слайд — меряем overflow «ещё» (карточка монтируется только в окне ±1). */
		active?: boolean;
		onopenmap: (event: FeedItem) => void;
	};

	let { event, active = false, onopenmap }: Props = $props();
	let bodyExpanded = $state(false);
	let needsMore = $state(false);
	let descriptionEl: HTMLParagraphElement | undefined = $state();

	const importanceColor = $derived(
		event.disaster_flag || event.importance === 1
			? 'var(--danger)'
			: event.importance === 2
				? 'var(--warning)'
				: 'var(--accent)'
	);

	const displayTitle = $derived(
		(event.title ?? '').trim() || event.body.trim().split('\n')[0]?.trim() || 'Событие'
	);
	const displayBody = $derived.by(() => {
		const explicitTitle = (event.title ?? '').trim();
		if (explicitTitle) return event.body;
		const lines = event.body
			.split('\n')
			.map((l) => l.trim())
			.filter(Boolean);
		if (lines.length <= 1) return '';
		return lines.slice(1).join('\n');
	});
	const publishedLabel = $derived(formatPublished(event.published_at ?? event.created_at));
	const sourceLabel = $derived(formatSource(event.source, event.source_msg_id));
	const distanceLabel = $derived(formatDistance(event.distance_m, event.proximity));
	const nearHints = $derived(
		[
			event.same_street ? 'ваша улица' : null,
			event.is_active_now === true ? 'сейчас' : null,
			distanceLabel
		].filter(Boolean) as string[]
	);

	function formatDistance(
		meters: number | null,
		proximity: string | null | undefined
	): string | null {
		if (meters == null || Number.isNaN(meters)) return null;
		if (meters < 1000) return `${Math.round(meters)} м`;
		const km = meters / 1000;
		const rounded = km < 10 ? km.toFixed(1) : String(Math.round(km));
		const band =
			proximity === 'home'
				? 'у дома'
				: proximity === 'block'
					? 'квартал'
					: proximity === 'street'
						? 'улица'
						: proximity === 'district'
							? 'район'
							: null;
		return band ? `${rounded} км · ${band}` : `${rounded} км`;
	}

	function formatPublished(iso: string | null): string {
		if (!iso) return 'Дата неизвестна';
		const d = new Date(iso);
		if (Number.isNaN(d.getTime())) return 'Дата неизвестна';
		return d.toLocaleString('ru-RU', {
			day: 'numeric',
			month: 'short',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function formatSource(source: string, sourceMsgId: string | null): string {
		const map: Record<string, string> = {
			news: 'Новости',
			mc: 'ЖКХ',
			neighbors_chat: 'Чат соседей',
			max_public: 'Паблик Max',
			manual: 'Вручную'
		};
		if (source === 'neighbors_chat') return map.neighbors_chat;
		if (sourceMsgId?.includes(':') && source === 'news') {
			const outlet = sourceMsgId.split(':', 1)[0];
			if (outlet) return outlet.toUpperCase();
		}
		if (sourceMsgId?.includes(':') && source === 'mc') {
			const outlet = sourceMsgId.split(':', 1)[0];
			if (outlet) return outlet.toUpperCase();
		}
		return map[source] ?? source;
	}

	function measureOverflow() {
		const el = descriptionEl;
		if (!el || bodyExpanded || !active) {
			needsMore = false;
			return;
		}
		needsMore = el.scrollHeight > el.clientHeight + 1;
	}

	$effect(() => {
		void event.id;
		void event.body;
		void active;
		bodyExpanded = false;
		needsMore = false;
		if (!active) return;
		const id = requestAnimationFrame(() => {
			requestAnimationFrame(measureOverflow);
		});
		return () => cancelAnimationFrame(id);
	});

	function expandBody() {
		bodyExpanded = true;
		needsMore = false;
	}
</script>

<article class="card" style:--importance-color={importanceColor}>
	<!-- div, не button: Yandex Maps canvas внутри <button> в Max WebView часто чёрный. -->
	<div
		class="media"
		class:clean-preview={HIDE_YANDEX_ATTRIBUTION}
		class:placeholder={!event.image_url}
		role="button"
		tabindex="0"
		aria-label={`Открыть карту: ${displayTitle}`}
		onclick={() => onopenmap(event)}
		onkeydown={(e) => {
			if (e.key === 'Enter' || e.key === ' ') {
				e.preventDefault();
				onopenmap(event);
			}
		}}
	>
		{#if event.image_url}
			<img src={event.image_url} alt="" loading="lazy" decoding="async" />
		{:else}
			<EventMapPreview {event} />
		{/if}
		<span class="map-shortcut" aria-hidden="true"><img src={mapSearchIcon} alt="" /></span>
	</div>

	<div class="importance-bar" aria-hidden="true"></div>

	<div class="body">
		<h2 class="title">
			{#if event.disaster_flag}
				<span class="disaster" title="Важная новость / ЧС" aria-label="Важная новость">
					<svg
						viewBox="0 0 24 24"
						width="18"
						height="18"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						aria-hidden="true"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
						/>
					</svg>
				</span>
			{/if}
			{displayTitle}
		</h2>

		{#if displayBody}
			<div class="description-wrap">
				<p class="description" class:expanded={bodyExpanded} bind:this={descriptionEl}>
					{displayBody}
				</p>
				{#if needsMore && !bodyExpanded}
					<button type="button" class="more" onclick={expandBody}>ещё</button>
				{/if}
			</div>
		{/if}

		<footer class="meta">
			<span class="meta-line">
				{publishedLabel}
				<span class="dot" aria-hidden="true">·</span>
				{#if event.source_url}
					<a href={event.source_url} target="_blank" rel="noopener noreferrer">{sourceLabel}</a>
				{:else}
					{sourceLabel}
				{/if}
				{#if event.location}
					<span class="dot" aria-hidden="true">·</span>
					<span class="location" title={event.location}>{event.location}</span>
				{/if}
				{#each nearHints as hint}
					<span class="dot" aria-hidden="true">·</span>
					<span class="near-hint">{hint}</span>
				{/each}
			</span>
		</footer>
	</div>
</article>

<style>
	.card {
		height: 100%;
		display: flex;
		flex-direction: column;
		background: var(--bg-surface);
		color: var(--text-primary);
		overflow: hidden;
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
	}

	.media {
		position: relative;
		display: block;
		width: 100%;
		height: 38%;
		min-height: 140px;
		max-height: 280px;
		padding: 0;
		border: 0;
		border-bottom: 1px solid var(--border);
		background: var(--bg-canvas);
		cursor: pointer;
		overflow: hidden;
		flex-shrink: 0;
	}

	.map-shortcut {
		position: absolute;
		bottom: 12px;
		right: 12px;
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-strong);
		background: var(--bg-raised);
		pointer-events: none;
	}
	.media.placeholder .map-shortcut {
		bottom: 12px;
	}
	.map-shortcut img {
		width: 20px;
		height: 20px;
		opacity: 0.9;
		filter: invert(1);
	}
	.media:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}
	.media.placeholder {
		background: var(--bg-elevated);
	}

	.media > img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.importance-bar {
		height: 2px;
		background: var(--importance-color);
		flex-shrink: 0;
	}

	.body {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-4);
		padding-bottom: calc(var(--space-5) + env(safe-area-inset-bottom));
		min-height: 0;
		overflow: hidden;
	}

	.title {
		margin: 0;
		font-size: var(--fs-20);
		font-weight: 600;
		line-height: 1.3;
		letter-spacing: -0.015em;
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		flex-shrink: 0;
	}

	.disaster {
		color: var(--danger);
		flex-shrink: 0;
		margin-top: 2px;
	}

	.description-wrap {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		position: relative;
	}

	.description {
		margin: 0;
		flex: 1;
		min-height: 0;
		overflow: hidden;
		font-size: var(--fs-14);
		line-height: 1.5;
		color: var(--text-secondary);
		white-space: pre-wrap;
	}

	.description.expanded {
		overflow: auto;
	}

	.more {
		align-self: flex-start;
		margin-top: var(--space-1);
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--accent);
		font: inherit;
		font-size: var(--fs-14);
		font-weight: 500;
		cursor: pointer;
		flex-shrink: 0;
	}

	.more:hover {
		color: var(--accent-hover);
		text-decoration: underline;
		text-underline-offset: 2px;
	}

	.meta {
		font-size: var(--fs-12);
		font-family: var(--font-mono);
		color: var(--text-tertiary);
		padding-top: var(--space-3);
		border-top: 1px solid var(--border);
		flex-shrink: 0;
	}

	.meta-line {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.meta a {
		color: var(--accent);
		text-decoration: none;
	}

	.meta a:hover {
		text-decoration: underline;
		text-underline-offset: 2px;
	}

	.dot {
		margin: 0 0.35em;
		opacity: 0.55;
	}

	.near-hint {
		color: var(--success);
	}
</style>

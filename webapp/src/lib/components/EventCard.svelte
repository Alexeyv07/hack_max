<script lang="ts">
	import type { FeedItem } from '$lib/types/event';
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
			? '#e53935'
			: event.importance === 2
				? '#fb8c00'
				: '#5c9ead'
	);

	const displayTitle = $derived(
		(event.title ?? '').trim() || event.body.trim().split('\n')[0]?.trim() || 'Событие'
	);
	const displayBody = $derived.by(() => {
		const explicitTitle = (event.title ?? '').trim();
		if (explicitTitle) return event.body;
		const lines = event.body.split('\n').map((l) => l.trim()).filter(Boolean);
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

	function formatDistance(meters: number | null, proximity: string | null | undefined): string | null {
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
	<button
		type="button"
		class="media"
		class:placeholder={!event.image_url}
		aria-label={`Открыть карту: ${displayTitle}`}
		onclick={() => onopenmap(event)}
	>
		{#if event.image_url}
			<img src={event.image_url} alt="" loading="lazy" decoding="async" />
		{:else}
			<EventMapPreview {event} />
		{/if}
	</button>

	<div class="importance-bar" aria-hidden="true"></div>

	<div class="body">
		<h2 class="title">
			{#if event.disaster_flag}
				<span class="disaster" title="Важная новость / ЧС" aria-label="Важная новость">
					<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
						<path
							fill="currentColor"
							d="M12 2 1 21h22L12 2zm0 3.99L19.53 19H4.47L12 5.99zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"
						/>
					</svg>
				</span>
			{/if}
			{displayTitle}
		</h2>

		{#if displayBody}
		<div class="description-wrap">
			<p
				class="description"
				class:expanded={bodyExpanded}
				bind:this={descriptionEl}
			>
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
		background: #101820;
		color: #eef3f6;
		overflow: hidden;
	}

	.media {
		display: block;
		width: 100%;
		height: 38%;
		min-height: 140px;
		max-height: 280px;
		padding: 0;
		border: 0;
		background: #000;
		cursor: pointer;
		overflow: hidden;
		flex-shrink: 0;
	}

	.media.placeholder {
		background: #122e34;
	}

	.media img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.importance-bar {
		height: 4px;
		background: var(--importance-color);
		flex-shrink: 0;
	}

	.body {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1rem 1.1rem 1.25rem;
		min-height: 0;
		overflow: hidden;
	}

	.title {
		margin: 0;
		font-size: clamp(1.15rem, 4.2vw, 1.45rem);
		font-weight: 700;
		line-height: 1.25;
		letter-spacing: -0.02em;
		display: flex;
		align-items: flex-start;
		gap: 0.45rem;
		flex-shrink: 0;
	}

	.disaster {
		color: #e53935;
		flex-shrink: 0;
		margin-top: 0.1rem;
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
		font-size: 0.95rem;
		line-height: 1.45;
		opacity: 0.88;
		white-space: pre-wrap;
	}

	.description.expanded {
		overflow: auto;
	}

	.more {
		align-self: flex-start;
		margin-top: 0.35rem;
		padding: 0;
		border: 0;
		background: transparent;
		color: #4da3ff;
		font: inherit;
		font-size: 0.95rem;
		font-weight: 600;
		cursor: pointer;
		flex-shrink: 0;
	}

	.more:hover {
		text-decoration: underline;
		text-underline-offset: 2px;
	}

	.meta {
		font-size: 0.78rem;
		opacity: 0.72;
		padding-top: 0.35rem;
		border-top: 1px solid rgba(255, 255, 255, 0.08);
		flex-shrink: 0;
	}

	.meta-line {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.meta a {
		color: #8ec8d8;
		text-decoration: underline;
		text-underline-offset: 2px;
	}

	.dot {
		margin: 0 0.35em;
		opacity: 0.55;
	}

	.near-hint {
		color: #9fd0c0;
	}

</style>

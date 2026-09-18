<script lang="ts">
	import type { FeedItem } from '$lib/types/event';

	type Props = {
		event: FeedItem;
	};

	let { event }: Props = $props();

	let imageExpanded = $state(false);
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

	const publishedLabel = $derived(formatPublished(event.published_at ?? event.created_at));
	const sourceLabel = $derived(formatSource(event.source, event.source_msg_id));

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
		if (sourceMsgId?.includes(':')) {
			const outlet = sourceMsgId.split(':', 1)[0];
			if (outlet) return outlet.toUpperCase();
		}
		const map: Record<string, string> = {
			news: 'Новости',
			neighbors_chat: 'Чат соседей',
			max_public: 'Паблик Max',
			manual: 'Вручную'
		};
		return map[source] ?? source;
	}

	function measureOverflow() {
		const el = descriptionEl;
		if (!el || bodyExpanded) {
			needsMore = false;
			return;
		}
		needsMore = el.scrollHeight > el.clientHeight + 1;
	}

	$effect(() => {
		// Сброс при смене карточки / текста.
		void event.id;
		void event.body;
		bodyExpanded = false;
		needsMore = false;
		const id = requestAnimationFrame(() => {
			requestAnimationFrame(measureOverflow);
		});
		return () => cancelAnimationFrame(id);
	});

	function expandBody() {
		bodyExpanded = true;
		needsMore = false;
	}

	function closeLightbox() {
		imageExpanded = false;
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && imageExpanded) {
			closeLightbox();
		}
	}
</script>

<svelte:window onkeydown={onKeydown} />

<article class="card" style:--importance-color={importanceColor}>
	<button
		type="button"
		class="media"
		class:placeholder={!event.image_url}
		aria-label={event.image_url ? 'Открыть изображение' : 'Нет изображения'}
		onclick={() => {
			if (event.image_url) imageExpanded = true;
		}}
		disabled={!event.image_url}
	>
		{#if event.image_url}
			<img src={event.image_url} alt="" loading="lazy" />
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
			{event.title}
		</h2>

		<div class="description-wrap">
			<p
				class="description"
				class:expanded={bodyExpanded}
				bind:this={descriptionEl}
			>
				{event.body}
			</p>
			{#if needsMore && !bodyExpanded}
				<button type="button" class="more" onclick={expandBody}>ещё</button>
			{/if}
		</div>

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
			</span>
		</footer>
	</div>
</article>

{#if imageExpanded && event.image_url}
	<!-- lightbox: клик по фону / крестик закрывает -->
	<div class="lightbox" role="dialog" aria-modal="true" aria-label="Изображение">
		<button type="button" class="lightbox-backdrop" aria-label="Закрыть" onclick={closeLightbox}
		></button>
		<img src={event.image_url} alt={event.title} class="lightbox-img" />
		<button type="button" class="lightbox-close" aria-label="Закрыть" onclick={closeLightbox}>
			<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">
				<path
					fill="currentColor"
					d="M18.3 5.71 12 12.01l-6.3-6.3-1.4 1.42 6.29 6.29-6.3 6.3 1.42 1.4 6.29-6.29 6.3 6.3 1.4-1.42-6.29-6.29 6.3-6.3z"
				/>
			</svg>
		</button>
	</div>
{/if}

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
		cursor: zoom-in;
		overflow: hidden;
		flex-shrink: 0;
	}

	.media:disabled {
		cursor: default;
	}

	.media.placeholder {
		background: #000;
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

	.lightbox {
		position: fixed;
		inset: 0;
		z-index: 1000;
		display: grid;
		place-items: center;
		padding: 1.5rem;
	}

	.lightbox-backdrop {
		position: absolute;
		inset: 0;
		border: 0;
		background: rgba(0, 0, 0, 0.92);
		cursor: pointer;
	}

	.lightbox-img {
		position: relative;
		z-index: 1;
		max-width: min(96vw, 900px);
		max-height: 88vh;
		object-fit: contain;
		border-radius: 4px;
	}

	.lightbox-close {
		position: absolute;
		top: max(0.75rem, env(safe-area-inset-top));
		right: max(0.75rem, env(safe-area-inset-right));
		z-index: 2;
		width: 44px;
		height: 44px;
		border: 0;
		border-radius: 999px;
		background: rgba(30, 30, 30, 0.85);
		color: #fff;
		display: grid;
		place-items: center;
		cursor: pointer;
	}
</style>

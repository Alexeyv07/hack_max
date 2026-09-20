<script lang="ts">
	import EventCard from '$lib/components/EventCard.svelte';
	import type { FeedItem, FeedScope } from '$lib/types/event';

	type Props = {
		scope: FeedScope;
		items: FeedItem[];
		loading: boolean;
		error: string | null;
		hasMore: boolean;
		onnearend: () => void;
		onrequestcity?: () => void;
		/** Вызывается при свайпе/скролле на следующую карточку вниз. */
		ondownswipe?: () => void;
	};

	let {
		scope,
		items,
		loading,
		error,
		hasMore,
		onnearend,
		onrequestcity,
		ondownswipe
	}: Props = $props();

	let scroller: HTMLElement | undefined = $state();
	let activeIndex = $state(0);
	let lastSlideIndex = 0;

	const WINDOW = 1;

	function currentSlideIndex(): number {
		if (!scroller) return 0;
		const h = scroller.clientHeight || 1;
		return Math.round(scroller.scrollTop / h);
	}

	function isInWindow(index: number): boolean {
		return Math.abs(index - activeIndex) <= WINDOW;
	}

	function onScroll() {
		if (!scroller) return;

		const idx = currentSlideIndex();
		if (idx !== activeIndex) {
			activeIndex = idx;
		}
		if (idx > lastSlideIndex) {
			ondownswipe?.();
		}
		lastSlideIndex = idx;

		if (!hasMore || loading) return;
		const remaining = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
		if (remaining < scroller.clientHeight * 1.5) {
			onnearend();
		}
	}
</script>

<div class="scroller" bind:this={scroller} onscroll={onScroll} data-scope={scope}>
	{#if error && items.length === 0}
		<div class="state state-error">
			<p>{error}</p>
		</div>
	{:else if loading && items.length === 0}
		<div class="state state-loading-full" aria-live="polite">
			<div class="spinner" aria-hidden="true"></div>
			<p>Загрузка новостей…</p>
		</div>
	{:else if !loading && items.length === 0}
		<div class="state">
			{#if scope === 'nearby'}
				<p>Новости рядом закончились</p>
				{#if onrequestcity}
					<button type="button" class="cta" onclick={onrequestcity}>
						К новостям города →
					</button>
					<p class="sub">Или смахните вправо</p>
				{/if}
			{:else}
				<p>Новостей города пока нет</p>
			{/if}
		</div>
	{:else}
		{#each items as event, index (event.id)}
			<section class="slide" class:offscreen={!isInWindow(index)}>
				{#if isInWindow(index)}
					<EventCard {event} active={index === activeIndex} />
				{/if}
			</section>
		{/each}

		{#if scope === 'nearby' && !hasMore && items.length > 0}
			<section class="slide end-slide">
				<div class="state">
					<p>Новости рядом закончились</p>
					{#if onrequestcity}
						<button type="button" class="cta" onclick={onrequestcity}>
							К новостям города →
						</button>
						<p class="sub">Или смахните вправо</p>
					{/if}
				</div>
			</section>
		{/if}

		{#if loading}
			<div class="state state-loading" aria-live="polite">Загрузка…</div>
		{/if}
		{#if error}
			<div class="state state-loading state-error-inline" aria-live="polite">{error}</div>
		{/if}
	{/if}
</div>

<style>
	.scroller {
		height: 100%;
		overflow-y: auto;
		scroll-snap-type: y mandatory;
		scroll-behavior: smooth;
		overscroll-behavior-y: contain;
		-webkit-overflow-scrolling: touch;
	}

	.slide {
		height: 100%;
		scroll-snap-align: start;
		scroll-snap-stop: always;
		content-visibility: auto;
		contain-intrinsic-size: 100dvh;
	}

	.slide.offscreen {
		/* Плейсхолдер той же высоты — snap не ломается, DOM лёгкий. */
		background: #0c1218;
	}

	.end-slide {
		background: #0c1218;
	}

	.state {
		height: 100%;
		display: grid;
		align-content: center;
		justify-items: center;
		gap: 0.75rem;
		padding: 2rem 1.5rem;
		text-align: center;
		color: #e8f0f2;
	}

	.state p {
		margin: 0;
		font-size: 1.1rem;
		font-weight: 600;
	}

	.sub {
		font-size: 0.85rem !important;
		font-weight: 400 !important;
		opacity: 0.65;
	}

	.state-error {
		color: #ff8a80;
	}

	.state-error-inline {
		color: #ff8a80;
		height: auto;
		min-height: 3rem;
	}

	.state-loading {
		padding: 1.5rem;
		text-align: center;
		opacity: 0.7;
		font-size: 0.9rem;
		height: auto;
	}

	.state-loading-full {
		gap: 1rem;
	}

	.spinner {
		width: 2rem;
		height: 2rem;
		border: 2px solid rgba(255, 255, 255, 0.15);
		border-top-color: #8ec8d8;
		border-radius: 50%;
		animation: spin 0.75s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.cta {
		border: 0;
		border-radius: 999px;
		padding: 0.65rem 1.2rem;
		background: #2a6f7a;
		color: #fff;
		font: inherit;
		font-weight: 600;
		cursor: pointer;
	}
</style>

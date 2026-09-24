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
		onrequestnearby?: () => void;
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
		onrequestnearby,
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

	function maybeLoadMore() {
		if (!scroller || !hasMore || loading || items.length === 0) return;
		const idx = currentSlideIndex();
		// Догружаем, когда до конца осталось ≤3 карточки.
		const remainingSlides = items.length - idx - 1;
		if (remainingSlides <= 3) {
			onnearend();
			return;
		}
		const remainingPx = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
		if (remainingPx < scroller.clientHeight * 3) {
			onnearend();
		}
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
		maybeLoadMore();
	}

	// После append страницы scroll-событие не приходит — догружаем, если всё ещё у края.
	$effect(() => {
		void items.length;
		void loading;
		void hasMore;
		if (!scroller || loading || !hasMore) return;
		const id = requestAnimationFrame(() => maybeLoadMore());
		return () => cancelAnimationFrame(id);
	});
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
				<p>Рядом с вашей улицей пока тихо</p>
				{#if onrequestcity}
					<button type="button" class="cta" onclick={onrequestcity}>
						К новостям города →
					</button>
					<p class="sub">Подключите чат соседей в боте или смахните вправо</p>
				{/if}
			{:else}
				<p>Новости города закончились</p>
				{#if onrequestnearby}
					<button type="button" class="cta" onclick={onrequestnearby}>
						← К новостям рядом
					</button>
					<p class="sub">Или смахните влево</p>
				{/if}
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

		{#if !hasMore && items.length > 0}
			<section class="slide end-slide">
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
						<p>Новости города закончились</p>
						{#if onrequestnearby}
							<button type="button" class="cta" onclick={onrequestnearby}>
								← К новостям рядом
							</button>
							<p class="sub">Или смахните влево</p>
						{/if}
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

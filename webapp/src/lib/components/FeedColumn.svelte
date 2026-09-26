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
		onopenmap: (event: FeedItem) => void;
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
		ondownswipe,
		onopenmap
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
			<svg
				class="state-icon"
				viewBox="0 0 24 24"
				width="20"
				height="20"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				aria-hidden="true"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z"
				/>
			</svg>
			<p>{error}</p>
		</div>
	{:else if loading && items.length === 0}
		<div class="state state-loading-full" aria-live="polite">
			<div class="skel-card" aria-hidden="true">
				<div class="skeleton skel-media"></div>
				<div class="skel-body">
					<div class="skeleton skel-line skel-title"></div>
					<div class="skeleton skel-line"></div>
					<div class="skeleton skel-line skel-short"></div>
					<div class="skeleton skel-line skel-meta"></div>
				</div>
			</div>
		</div>
	{:else if !loading && items.length === 0}
		<div class="state">
			<svg
				class="state-icon muted"
				viewBox="0 0 24 24"
				width="20"
				height="20"
				fill="none"
				stroke="currentColor"
				stroke-width="1.5"
				aria-hidden="true"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z"
				/>
			</svg>
			{#if scope === 'nearby'}
				<p>Рядом с вашей улицей пока тихо</p>
				{#if onrequestcity}
					<button type="button" class="btn btn-primary cta" onclick={onrequestcity}>
						К новостям города
					</button>
					<p class="sub">Подключите чат соседей в боте или смахните вправо</p>
				{/if}
			{:else}
				<p>Новости города закончились</p>
				{#if onrequestnearby}
					<button type="button" class="btn btn-secondary cta" onclick={onrequestnearby}>
						К новостям рядом
					</button>
					<p class="sub">Или смахните влево</p>
				{/if}
			{/if}
		</div>
	{:else}
		{#each items as event, index (event.id)}
			<section class="slide" class:offscreen={!isInWindow(index)}>
				{#if isInWindow(index)}
					<EventCard {event} active={index === activeIndex} {onopenmap} />
				{/if}
			</section>
		{/each}

		{#if !hasMore && items.length > 0}
			<section class="slide end-slide">
				<div class="state">
					<svg
						class="state-icon muted"
						viewBox="0 0 24 24"
						width="20"
						height="20"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						aria-hidden="true"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z"
						/>
					</svg>
					{#if scope === 'nearby'}
						<p>Новости рядом закончились</p>
						{#if onrequestcity}
							<button type="button" class="btn btn-primary cta" onclick={onrequestcity}>
								К новостям города
							</button>
							<p class="sub">Или смахните вправо</p>
						{/if}
					{:else}
						<p>Новости города закончились</p>
						{#if onrequestnearby}
							<button type="button" class="btn btn-secondary cta" onclick={onrequestnearby}>
								К новостям рядом
							</button>
							<p class="sub">Или смахните влево</p>
						{/if}
					{/if}
				</div>
			</section>
		{/if}

		{#if loading}
			<div class="state state-loading" aria-live="polite">
				<div class="skeleton skel-inline" aria-hidden="true"></div>
				<span>Загрузка…</span>
			</div>
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
		background: var(--bg-canvas);
	}

	.slide {
		height: 100%;
		scroll-snap-align: start;
		scroll-snap-stop: always;
		content-visibility: auto;
		contain-intrinsic-size: 100dvh;
	}

	.slide.offscreen,
	.end-slide {
		background: var(--bg-surface);
	}

	.state {
		height: 100%;
		display: grid;
		align-content: center;
		justify-items: start;
		gap: var(--space-3);
		padding: var(--space-8) var(--space-5);
		text-align: left;
		color: var(--text-primary);
	}

	.state-icon {
		color: var(--danger);
		margin-bottom: var(--space-1);
	}

	.state-icon.muted {
		color: var(--text-tertiary);
	}

	.state p {
		margin: 0;
		font-size: var(--fs-16);
		font-weight: 500;
		letter-spacing: -0.01em;
		max-width: 28ch;
	}

	.sub {
		font-size: var(--fs-12) !important;
		font-weight: 400 !important;
		color: var(--text-tertiary);
		max-width: 32ch;
	}

	.state-error {
		color: var(--danger);
	}

	.state-error p {
		color: var(--danger);
	}

	.state-error-inline {
		color: var(--danger);
		height: auto;
		min-height: 48px;
		padding: var(--space-4);
	}

	.state-loading {
		display: flex;
		flex-direction: row;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		padding: var(--space-4);
		text-align: center;
		color: var(--text-tertiary);
		font-size: var(--fs-12);
		height: auto;
	}

	.state-loading-full {
		padding: 0;
		align-content: stretch;
		justify-items: stretch;
	}

	.skel-card {
		height: 100%;
		display: flex;
		flex-direction: column;
		background: var(--bg-surface);
	}

	.skel-media {
		height: 38%;
		min-height: 140px;
		border-radius: 0;
	}

	.skel-body {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-4);
	}

	.skel-line {
		height: 14px;
		width: 100%;
	}

	.skel-title {
		height: 20px;
		width: 78%;
	}

	.skel-short {
		width: 62%;
	}

	.skel-meta {
		width: 48%;
		margin-top: var(--space-2);
	}

	.skel-inline {
		width: 48px;
		height: 8px;
		border-radius: 2px;
	}

	.cta {
		margin-top: var(--space-2);
		width: auto;
		min-width: 160px;
	}
</style>

<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchFeed } from '$lib/api/events';
	import FeedColumn from '$lib/components/FeedColumn.svelte';
	import FeedTabs from '$lib/components/FeedTabs.svelte';
	import {
		recordCitySwitch,
		recordDownSwipe,
		shouldShowCityHint,
		shouldShowDownHint
	} from '$lib/feedHints';
	import { getMaxUserId, readyMaxWebApp, waitForMaxStartParam } from '$lib/maxUser';
	import {
		clearActiveChatLinkMode,
		isChatLinkMode,
		loadActiveChatLinkMode,
		parseChatLinkMode,
		saveActiveChatLinkMode
	} from '$lib/chatLinkSession';
	import AddressPicker from '$lib/components/AddressPicker.svelte';
	import type { FeedItem, FeedScope } from '$lib/types/event';

	type FeedState = {
		items: FeedItem[];
		cursor: string | null;
		loading: boolean;
		error: string | null;
		exhausted: boolean;
	};

	function emptyState(loading = false): FeedState {
		return {
			items: [],
			cursor: null,
			loading,
			error: null,
			exhausted: false
		};
	}

	const cachedChatLinkMode = loadActiveChatLinkMode();
	let startParam = $state<string | null>(cachedChatLinkMode);
	let bridgeReady = $state(cachedChatLinkMode !== null);
	let pickerStart = $derived(parseChatLinkMode(startParam));
	let scope = $state<FeedScope>('nearby');
	/** Nearby стартует в loading — до ответа API не показываем «новостей нет». */
	let nearby = $state<FeedState>(emptyState(true));
	let city = $state<FeedState>(emptyState());

	let rail: HTMLElement | undefined = $state();
	let touchStartX = 0;
	let touchStartY = 0;
	let swiping = false;
	let nearbyInflight = false;
	let cityInflight = false;

	let showDownHint = $state(false);
	let showCityHint = $state(false);

	function refreshHints() {
		showDownHint = shouldShowDownHint();
		showCityHint = shouldShowCityHint() && scope === 'nearby';
	}

	function onDownSwipe() {
		if (!shouldShowDownHint()) return;
		recordDownSwipe();
		refreshHints();
	}

	function getState(target: FeedScope): FeedState {
		return target === 'nearby' ? nearby : city;
	}

	function setState(target: FeedScope, next: FeedState) {
		if (target === 'nearby') nearby = next;
		else city = next;
	}

	async function loadMore(target: FeedScope, reset = false) {
		if (target === 'nearby' ? nearbyInflight : cityInflight) return;
		const prev = getState(target);
		if (!reset && (prev.loading || prev.exhausted)) return;

		if (target === 'nearby') nearbyInflight = true;
		else cityInflight = true;

		const cursor = reset ? null : prev.cursor;
		const baseItems = reset ? [] : prev.items;

		setState(target, {
			...prev,
			items: baseItems,
			cursor,
			loading: true,
			error: null,
			exhausted: reset ? false : prev.exhausted
		});

		try {
			const page = await fetchFeed(target, { cursor, limit: 20 });
			const merged = [
				...baseItems,
				...page.items.filter((item) => !baseItems.some((x) => x.id === item.id))
			];
			setState(target, {
				items: merged,
				cursor: page.next_cursor,
				loading: false,
				error: null,
				exhausted: !page.next_cursor
			});
		} catch (err) {
			const message = err instanceof Error ? err.message : 'Не удалось загрузить ленту';
			setState(target, {
				...getState(target),
				loading: false,
				error: message
			});
		} finally {
			if (target === 'nearby') nearbyInflight = false;
			else cityInflight = false;
		}
	}

	function setScope(next: FeedScope) {
		if (scope === next) return;
		const prev = scope;
		scope = next;
		if (next === 'city' && prev === 'nearby') {
			recordCitySwitch();
		}
		refreshHints();
		queueMicrotask(() => {
			if (!rail) return;
			rail.scrollTo({
				left: next === 'city' ? rail.clientWidth : 0,
				behavior: 'smooth'
			});
		});
		const state = getState(next);
		if (state.items.length === 0 && !state.loading && !state.error) {
			void loadMore(next, true);
		}
	}

	function onRailScroll() {
		if (!rail) return;
		const mid = rail.scrollLeft + rail.clientWidth / 2;
		const next: FeedScope = mid >= rail.clientWidth ? 'city' : 'nearby';
		if (next !== scope) {
			const prev = scope;
			scope = next;
			if (next === 'city' && prev === 'nearby') {
				recordCitySwitch();
			}
			refreshHints();
			const state = getState(next);
			if (state.items.length === 0 && !state.loading && !state.error) {
				void loadMore(next, true);
			}
		}
	}

	function onTouchStart(e: TouchEvent) {
		const t = e.changedTouches[0];
		if (!t) return;
		touchStartX = t.clientX;
		touchStartY = t.clientY;
		swiping = true;
	}

	function onTouchEnd(e: TouchEvent) {
		if (!swiping) return;
		swiping = false;
		const t = e.changedTouches[0];
		if (!t) return;
		const dx = t.clientX - touchStartX;
		const dy = t.clientY - touchStartY;
		if (Math.abs(dx) < 56 || Math.abs(dx) < Math.abs(dy) * 1.2) return;
		// Палец влево → лента города справа; в UI говорим «свайп вправо» (к вкладке справа).
		if (dx < 0) setScope('city');
		else setScope('nearby');
	}

	onMount(() => {
		let cancelled = false;
		readyMaxWebApp();
		void (async () => {
			const param = await waitForMaxStartParam();
			if (cancelled) return;

			if (isChatLinkMode(param)) {
				startParam = param;
				bridgeReady = true;
				saveActiveChatLinkMode(param);
				return;
			}

			// Если MAX временно не отдал Bridge во время reload WebView, не выбрасываем
			// пользователя из уже открытого address-flow. API сам дождётся user id.
			if (getMaxUserId() === null && isChatLinkMode(startParam)) {
				bridgeReady = true;
				return;
			}

			clearActiveChatLinkMode();
			startParam = param;
			bridgeReady = true;
			refreshHints();
			void loadMore('nearby', true);
		})();
		return () => {
			cancelled = true;
		};
	});
</script>

{#if pickerStart?.mode === 'map'}
	<AddressPicker mode="map" targetChatId={pickerStart.targetChatId} residentChatId={pickerStart.residentChatId} />
{:else if pickerStart?.mode === 'text'}
	<AddressPicker mode="text" targetChatId={pickerStart.targetChatId} residentChatId={pickerStart.residentChatId} />
{:else if bridgeReady}
<div
	class="feed-root"
	role="application"
	aria-label="Лента новостей"
	ontouchstart={onTouchStart}
	ontouchend={onTouchEnd}
>
	<FeedTabs {scope} onselect={setScope} />

	{#if showCityHint}
		<span class="hint hint-city" aria-hidden="true">
			<span class="hint-label">свайп вправо</span>
			<svg class="hint-arrow" viewBox="0 0 24 24" width="18" height="18">
				<path
					fill="currentColor"
					d="M8.59 16.59 13.17 12 8.59 7.41 10 6l6 6-6 6-1.41-1.41z"
				/>
			</svg>
		</span>
	{/if}

	{#if showDownHint && scope === 'nearby'}
		<span class="hint hint-down" aria-hidden="true">
			<span class="hint-label">свайп вниз</span>
			<svg class="hint-arrow" viewBox="0 0 24 24" width="18" height="18">
				<path
					fill="currentColor"
					d="M16.59 8.59 12 13.17 7.41 8.59 6 10l6 6 6-6-1.41-1.41z"
				/>
			</svg>
		</span>
	{/if}

	<div class="rail" bind:this={rail} onscroll={onRailScroll}>
		<div class="pane">
			<FeedColumn
				scope="nearby"
				items={nearby.items}
				loading={nearby.loading}
				error={nearby.error}
				hasMore={!nearby.exhausted}
				onnearend={() => loadMore('nearby')}
				onrequestcity={() => setScope('city')}
				ondownswipe={onDownSwipe}
			/>
		</div>
		<div class="pane">
			<FeedColumn
				scope="city"
				items={city.items}
				loading={city.loading}
				error={city.error}
				hasMore={!city.exhausted}
				onnearend={() => loadMore('city')}
				onrequestnearby={() => setScope('nearby')}
				ondownswipe={onDownSwipe}
			/>
		</div>
	</div>
</div>

{/if}

<style>
	.feed-root {
		position: relative;
		height: 100dvh;
		max-height: 100dvh;
		overflow: hidden;
		background: #0a1014;
		color: #eef3f6;
		touch-action: pan-y;
		/* На широком экране колонка как телефон, по краям фон страницы. */
		width: min(100%, 28rem);
		margin-inline: auto;
		box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.04);
	}

	.rail {
		display: flex;
		height: 100%;
		overflow-x: auto;
		overflow-y: hidden;
		scroll-snap-type: x mandatory;
		scroll-behavior: smooth;
		scrollbar-width: none;
	}

	.rail::-webkit-scrollbar {
		display: none;
	}

	.pane {
		flex: 0 0 100%;
		width: 100%;
		height: 100%;
		scroll-snap-align: start;
		scroll-snap-stop: always;
	}

	.hint {
		pointer-events: none;
		position: absolute;
		z-index: 25;
		display: inline-flex;
		align-items: center;
		gap: 0.15rem;
		color: rgba(255, 255, 255, 0.7);
		font-size: 0.72rem;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		text-shadow: 0 1px 4px rgba(0, 0, 0, 0.55);
	}

	/* Ниже табов, чтобы «Новости города» не перекрывала на телефоне */
	.hint-city {
		top: calc(3.4rem + env(safe-area-inset-top));
		right: 0.85rem;
		animation: nudge-x 1.8s ease-in-out infinite;
	}

	.hint-down {
		left: 50%;
		bottom: calc(1.25rem + env(safe-area-inset-bottom));
		transform: translateX(-50%);
		flex-direction: column;
		animation: nudge-y 1.8s ease-in-out infinite;
	}

	@keyframes nudge-x {
		0%,
		100% {
			transform: translateX(0);
			opacity: 0.45;
		}
		50% {
			transform: translateX(5px);
			opacity: 0.95;
		}
	}
	@keyframes nudge-y {
		0%,
		100% {
			transform: translateX(-50%) translateY(0);
			opacity: 0.45;
		}
		50% {
			transform: translateX(-50%) translateY(5px);
			opacity: 0.95;
		}
	}
</style>

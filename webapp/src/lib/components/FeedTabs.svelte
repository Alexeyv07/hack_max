<script lang="ts">
	import type { FeedScope } from '$lib/types/event';

	type Props = {
		scope: FeedScope;
		onselect: (scope: FeedScope) => void;
	};

	let { scope, onselect }: Props = $props();
</script>

<nav class="tabs" aria-label="Ленты новостей">
	<button
		type="button"
		class="tab"
		class:active={scope === 'nearby'}
		aria-current={scope === 'nearby' ? 'page' : undefined}
		onclick={() => onselect('nearby')}
	>
		Новости рядом
	</button>
	<button
		type="button"
		class="tab"
		class:active={scope === 'city'}
		aria-current={scope === 'city' ? 'page' : undefined}
		onclick={() => onselect('city')}
	>
		Новости города
	</button>
</nav>

<style>
	.tabs {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		z-index: 20;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 1.1rem;
		padding: calc(0.65rem + env(safe-area-inset-top)) 1rem 0.5rem;
		background: linear-gradient(180deg, rgba(0, 0, 0, 0.72) 0%, rgba(0, 0, 0, 0) 100%);
		pointer-events: none;
	}

	.tab {
		pointer-events: auto;
		border: 0;
		background: transparent;
		color: rgba(255, 255, 255, 0.55);
		font: inherit;
		font-size: 0.95rem;
		font-weight: 500;
		padding: 0.35rem 0.15rem;
		cursor: pointer;
		text-shadow: 0 1px 4px rgba(0, 0, 0, 0.45);
		transition: color 0.2s ease;
	}

	.tab.active {
		color: #fff;
		font-weight: 700;
	}
</style>

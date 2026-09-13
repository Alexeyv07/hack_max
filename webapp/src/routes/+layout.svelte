<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';
	import '$lib/styles/app.css';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Умный город · Max</title>
</svelte:head>

<div class="app-shell">
	{@render children()}
</div>

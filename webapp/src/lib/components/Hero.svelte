<section class="hero">
	<p class="brand">Умный город</p>
	<h1>WebApp для Max</h1>
	<p class="lead">Мини-приложение мессенджера Max. Скелет SvelteKit готов к доработке.</p>
</section>

<style>
	.hero {
		min-height: 100vh;
		display: grid;
		align-content: center;
		gap: 0.75rem;
		padding: 2rem;
		background:
			radial-gradient(ellipse 80% 60% at 20% 10%, rgba(34, 120, 90, 0.25), transparent 60%),
			radial-gradient(ellipse 70% 50% at 90% 80%, rgba(20, 60, 90, 0.3), transparent 55%),
			linear-gradient(160deg, #0f1a1f 0%, #15252c 45%, #1a3038 100%);
		color: #e8f0f2;
	}

	.brand {
		margin: 0;
		font-family: 'Segoe UI', system-ui, sans-serif;
		font-size: clamp(2rem, 5vw, 3.25rem);
		font-weight: 700;
		letter-spacing: -0.03em;
	}

	h1 {
		margin: 0;
		font-size: clamp(1.1rem, 2.5vw, 1.5rem);
		font-weight: 500;
		opacity: 0.9;
	}

	.lead {
		margin: 0;
		max-width: 36rem;
		line-height: 1.5;
		opacity: 0.75;
	}
</style>

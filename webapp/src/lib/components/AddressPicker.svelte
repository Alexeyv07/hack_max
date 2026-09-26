<script lang="ts">
	import { HIDE_YANDEX_ATTRIBUTION } from '$lib/mapAppearance';
	import { onMount, tick } from 'svelte';
	import {
		nearestAddresses,
		searchAddresses,
		selectAddress,
		type AddressOption,
		type SelectResult
	} from '$lib/api/chatLink';
	import {
		buildChatLinkMode,
		clearActiveChatLinkMode,
		saveActiveChatLinkMode,
		type ChatLinkMode
	} from '$lib/chatLinkSession';
	import { getMaxUserIdForStorage } from '$lib/maxUser';
	import { loadYandexMaps, type YandexMapInstance } from '$lib/yandexMaps';

	let { mode, targetChatId = null, residentChatId = null }: {
		mode: 'map' | 'text';
		targetChatId?: number | null;
		residentChatId?: number | null;
	} = $props();

	type PickerDraft = {
		version: 6;
		mode: 'map' | 'text';
		savedAt: number;
		query: string;
		lat: number;
		lon: number;
		selected: AddressOption | null;
		zoom?: number;
	};

	const DRAFT_TTL_MS = 30 * 60 * 1000;
	const MAP_ZOOM = 16;
	let activeMode: ChatLinkMode = $derived(buildChatLinkMode(mode, targetChatId, residentChatId));

	let query = $state('');
	let options = $state<AddressOption[]>([]);
	let selected = $state<AddressOption | null>(null);
	let result = $state<SelectResult | null>(null);
	let error = $state('');
	let loading = $state(false);
	let linkCopied = $state(false);
	let showAdminHelp = $state(false);
	let searchTimer: number | null = null;
	let searchSeq = 0;

	let lat = $state(55.751244);
	let lon = $state(37.618423);
	let mapZoom = $state(MAP_ZOOM);
	let mapElement: HTMLDivElement | undefined = $state();
	let yandexMap: YandexMapInstance | null = null;
	let mapReady = $state(false);
	let mapLoadError = $state('');
	let mapDisposed = false;

	function storageKey() {
		return `chat-link-picker-v6:${getMaxUserIdForStorage()}:${mode}:${targetChatId ?? `resident-${residentChatId ?? 'new'}`}`;
	}

	function legacyStorageKeys() {
		const userId = getMaxUserIdForStorage();
		return [
			`chat-link-picker-v5:${userId}:${mode}:user`,
			`chat-link-picker-v5:${userId}:${mode}:admin`,
			`chat-link-picker-v4:${userId}:${mode}`,
			`chat-link-picker-v3:${userId}:${mode}`,
			`chat-link-picker-v2:${userId}:${mode}`
		];
	}

	function loadDraft(): PickerDraft | null {
		try {
			const raw = localStorage.getItem(storageKey());
			if (!raw) return null;
			const draft = JSON.parse(raw) as PickerDraft;
			if (
				draft.version !== 6 ||
				draft.mode !== mode ||
				Date.now() - draft.savedAt > DRAFT_TTL_MS
			) {
				localStorage.removeItem(storageKey());
				return null;
			}
			return draft;
		} catch {
			return null;
		}
	}

	function saveDraft() {
		try {
			const draft: PickerDraft = {
				version: 6,
				mode,
				savedAt: Date.now(),
				query,
				lat,
				lon,
				selected,
				zoom: mapZoom
			};
			localStorage.setItem(storageKey(), JSON.stringify(draft));
			saveActiveChatLinkMode(activeMode);
		} catch {
			// localStorage может быть запрещён WebView; основной flow при этом продолжает работать.
		}
	}

	function clearDraft() {
		try {
			localStorage.removeItem(storageKey());
			for (const key of legacyStorageKeys()) {
				localStorage.removeItem(key);
				sessionStorage.removeItem(key);
			}
			clearActiveChatLinkMode();
		} catch {
			// Storage может быть запрещён WebView; основной flow при этом продолжает работать.
		}
	}

	async function refreshNearest(settings: { preserveSelectedId?: number } = {}) {
		const preserveSelectedId = settings.preserveSelectedId;
		loading = true;
		if (preserveSelectedId == null) selected = null;
		try {
			error = '';
			const next = await nearestAddresses(lat, lon);
			options = next;
			selected = preserveSelectedId
				? next.find((item) => item.id === preserveSelectedId) ?? null
				: null;
			if (!next.length) {
				error = 'Рядом с курсором нет дома из справочника. Передвиньте карту к нужному дому.';
			}
			saveDraft();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : 'Ошибка поиска';
		} finally {
			loading = false;
		}
	}

	function moveMap(latitude: number, longitude: number) {
		yandexMap?.update({
			location: {
				center: [longitude, latitude],
				zoom: mapZoom,
				duration: 250
			}
		});
	}

	function zoomMap(delta: number) {
		if (!yandexMap) return;
		mapZoom = Math.max(8, Math.min(20, mapZoom + delta));
		yandexMap.update({
			location: {
				center: [lon, lat],
				zoom: mapZoom,
				duration: 180
			}
		});
		saveDraft();
	}

	function locate() {
		if (!navigator.geolocation) {
			error = 'Геопозиция недоступна. Передвиньте карту вручную.';
			void refreshNearest();
			return;
		}
		navigator.geolocation.getCurrentPosition(
			(position) => {
				lat = position.coords.latitude;
				lon = position.coords.longitude;
				moveMap(lat, lon);
				saveDraft();
				void refreshNearest();
			},
			() => {
				error = 'Не удалось получить геопозицию. Передвиньте карту вручную.';
				void refreshNearest();
			},
			{ enableHighAccuracy: true, timeout: 8000 }
		);
	}

	async function initYandexMap(draft: PickerDraft | null) {
		if (!mapElement) return;
		mapLoadError = '';
		try {
			const ymaps3 = await loadYandexMaps();
			if (mapDisposed || !mapElement) return;

			yandexMap = new ymaps3.YMap(mapElement, {
				location: { center: [lon, lat], zoom: mapZoom },
				behaviors: ['drag', 'pinchZoom', 'scrollZoom', 'dblClick', 'oneFingerZoom'],
				theme: 'dark',
				distribution: !HIDE_YANDEX_ATTRIBUTION,
				distributionPosition: 'top left',
				copyrightsPosition: 'bottom right'
			});
			yandexMap.addChild(new ymaps3.YMapDefaultSchemeLayer({}));
			yandexMap.addChild(
				new ymaps3.YMapListener({
					onUpdate: ({ location }) => {
						lon = location.center[0];
						lat = location.center[1];
						if (typeof location.zoom === 'number') mapZoom = location.zoom;
					},
					onActionEnd: ({ location }) => {
						lon = location.center[0];
						lat = location.center[1];
						if (typeof location.zoom === 'number') mapZoom = location.zoom;
						saveDraft();
						void refreshNearest();
					}
				})
			);
			mapReady = true;
			if (draft) {
				void refreshNearest({ preserveSelectedId: selected?.id });
			} else {
				locate();
			}
		} catch (cause) {
			mapReady = false;
			mapLoadError =
				cause instanceof Error ? cause.message : 'Не удалось открыть Яндекс Карты.';
		}
	}

	async function runSearch(value: string, settings: { preserveSelectedId?: number } = {}) {
		const trimmed = value.trim();
		if (trimmed.length < 3) {
			options = [];
			selected = null;
			error = '';
			saveDraft();
			return;
		}

		const seq = ++searchSeq;
		loading = true;
		error = '';
		try {
			const next = await searchAddresses(trimmed);
			if (seq !== searchSeq) return;
			options = next;
			const preserveSelectedId = settings.preserveSelectedId;
			selected = preserveSelectedId
				? next.find((item) => item.id === preserveSelectedId) ?? null
				: null;
			if (!next.length) {
				error = 'Пока ничего не найдено. Продолжите ввод — можно писать только часть адреса.';
			}
			saveDraft();
		} catch (cause) {
			if (seq !== searchSeq) return;
			error = cause instanceof Error ? cause.message : 'Ошибка поиска';
		} finally {
			if (seq === searchSeq) loading = false;
		}
	}

	function scheduleSearch(value: string) {
		query = value;
		selected = null;
		options = [];
		loading = false;
		error = '';
		searchSeq += 1;
		if (searchTimer !== null) window.clearTimeout(searchTimer);
		saveDraft();
		if (value.trim().length < 3) {
			return;
		}
		searchTimer = window.setTimeout(() => {
			searchTimer = null;
			void runSearch(value);
		}, 220);
	}

	function choose(item: AddressOption) {
		selected = item;
		error = '';
		saveDraft();
	}

	async function confirm() {
		if (!selected) return;
		loading = true;
		error = '';
		try {
			result = await selectAddress(selected.id, targetChatId, residentChatId);
			showAdminHelp = false;
			if (mode === 'map') {
				yandexMap?.destroy();
				yandexMap = null;
				mapReady = false;
			}
			clearDraft();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : 'Ошибка выбора адреса';
		} finally {
			loading = false;
		}
	}

	async function copyAdminLink() {
		if (!result?.admin_link) return;
		try {
			await navigator.clipboard.writeText(
                `Здравствуйте! Помогите подключить домовой чат по адресу ${result.address.address_text} к боту «КасаетсяМеня»: ${result.admin_link}`
            );
			linkCopied = true;
		} catch {
			error = 'Не удалось скопировать ссылку. Попробуйте открыть выбор адреса из бота ещё раз.';
		}
	}

	async function startAnother() {
		result = null;
		selected = null;
		options = [];
		error = '';
		linkCopied = false;
		showAdminHelp = false;
		query = '';
		clearDraft();
		saveActiveChatLinkMode(activeMode);
		if (mode === 'text') return;
		mapLoadError = '';
		await tick();
		void initYandexMap(null);
	}

	onMount(() => {
		mapDisposed = false;
		saveActiveChatLinkMode(activeMode);
		try {
			for (const key of legacyStorageKeys()) {
				localStorage.removeItem(key);
				sessionStorage.removeItem(key);
			}
		} catch {
			// Старый draft не критичен, если storage закрыт WebView.
		}

		const draft = loadDraft();
		if (draft) {
			query = draft.query;
			lat = draft.lat;
			lon = draft.lon;
			mapZoom = draft.zoom ?? MAP_ZOOM;
			selected = draft.selected;
		}

		if (!result) {
			if (mode === 'map') {
				void initYandexMap(draft);
			} else if (query.trim().length >= 3) {
				void runSearch(query, { preserveSelectedId: selected?.id });
			}
		}

		return () => {
			mapDisposed = true;
			yandexMap?.destroy();
			yandexMap = null;
			if (result) clearDraft();
			else saveDraft();
			if (searchTimer !== null) window.clearTimeout(searchTimer);
			searchSeq += 1;
		};
	});
</script>

<div class="picker">
	<h1>{result ? 'Адрес выбран' : mode === 'map' ? 'Укажите дом на карте' : 'Введите адрес'}</h1>

	{#if !result}
		{#if mode === 'map'}
			<div class="map-shell" role="application" aria-label="Карта выбора дома">
				<div class="map" class:yandex-map-clean={HIDE_YANDEX_ATTRIBUTION} bind:this={mapElement}></div>
				<div class="pin" aria-hidden="true">
					<span class="pin-dot"></span>
				</div>
				{#if mapReady}
					<div class="zoom-controls" aria-label="Масштаб карты">
						<button type="button" aria-label="Приблизить карту" onclick={() => zoomMap(1)}>+</button>
						<button type="button" aria-label="Отдалить карту" onclick={() => zoomMap(-1)}>−</button>
					</div>
				{/if}
				{#if mapLoadError}
					<div class="map-loading map-load-error">
						<span>{mapLoadError}</span>
						<button type="button" onclick={() => void initYandexMap(loadDraft())}>Повторить</button>
					</div>
				{:else if !mapReady}
					<div class="map-loading">Загружаем Яндекс Карты…</div>
				{/if}
			</div>
			<button class="secondary" type="button" onclick={locate}>Моя геопозиция</button>
		{:else}
			<div class="search-box">
				<input
					aria-label="Адрес дома"
					value={query}
					oninput={(event) => scheduleSearch(event.currentTarget.value)}
					placeholder="Например: улица, дом, район"
					autocomplete="street-address"
					inputmode="text"
				/>
			</div>
			<p class="hint-text">Можно вводить слова в любом порядке, использовать сокращения и небольшие опечатки.</p>
		{/if}

		{#if loading && !options.length}
			<p class="muted">Ищем адреса…</p>
		{/if}

		{#if options.length}
			<p class="list-title">{mode === 'map' ? 'Ближайшие дома' : 'Подходящие адреса'}</p>
			<div class="options" aria-label="Варианты адреса">
				{#each options as item}
					<button
						type="button"
						class:selected={selected?.id === item.id}
						aria-pressed={selected?.id === item.id}
						onclick={() => choose(item)}
					>
						<span class="choice" aria-hidden="true">{selected?.id === item.id ? '●' : '○'}</span>
						<span class="address-label">{item.address_text}</span>
					</button>
				{/each}
			</div>
		{/if}

		<div class="confirm-wrap">
			{#if selected}
				<p class="selection-status">Выбран адрес: <b>{selected.address_text}</b></p>
			{:else if options.length}
				<p class="selection-status muted">Нажмите на нужный адрес в списке.</p>
			{/if}
			<button class="primary" type="button" disabled={!selected || loading} onclick={confirm}>
				{loading && selected ? 'Сохраняем…' : 'Подтвердить адрес'}
			</button>
		</div>
	{:else}
		<div class="done">
			<b>{result.address.address_text}</b>
			{#if result.mode === 'group_connected'}
				<p>Домовой чат успешно привязан к этому адресу. Можно вернуться в групповой чат.</p>
			{:else if result.mode === 'already_member'}
				<p>Вы состоите в этом домовом чате. Чат привязан к вашему профилю.</p>
			{:else if result.mode === 'resident_address' || result.mode === 'personal_address'}
				<p>Ваш адрес сохранён. Новости рядом доступны.</p>
			{:else if showAdminHelp}
				<p>
					Добавьте бота в нужный групповой чат и назначьте его администратором с правом
					«Читать все сообщения». После этого чат подключится автоматически —
					дополнительных команд не нужно.
				</p>
				<button class="secondary" type="button" onclick={() => (showAdminHelp = false)}>
					← Я не администратор
				</button>
			{:else}
				<p>
					Для этого дома пока нет подключённого чата. Если вы обычный житель, отправьте
					администратору домового чата ссылку кнопкой ниже.
				</p>
				{#if result.admin_link}
					<button class="primary" type="button" onclick={copyAdminLink}>
						{linkCopied ? 'Ссылка скопирована' : 'Скопировать пригласительное сообщение'}
					</button>
				{/if}
				<button class="secondary" type="button" onclick={() => (showAdminHelp = true)}>
					Я администратор чата
				</button>
			{/if}
			{#if result.mode === 'group_connected'}
				<button class="secondary" type="button" onclick={startAnother}>Добавить ещё дом к чату</button>
			{:else if result.mode === 'resident_address' || result.mode === 'personal_address'}
				<button class="secondary" type="button" onclick={startAnother}>Изменить свой адрес</button>
			{:else}
				<button class="secondary" type="button" onclick={startAnother}>Выбрать другой адрес</button>
			{/if}
		</div>
	{/if}

	{#if error}<p class="error">{error}</p>{/if}
</div>

<style>
	.picker {
		box-sizing: border-box;
		height: 100dvh;
		overflow-y: auto;
		overflow-x: hidden;
		overscroll-behavior: contain;
		-webkit-overflow-scrolling: touch;
		background: var(--bg-canvas);
		color: var(--text-primary);
		padding: calc(16px + env(safe-area-inset-top)) 16px calc(24px + env(safe-area-inset-bottom));
		font-family: var(--font);
		max-width: 28rem;
		margin-inline: auto;
		border-inline: 1px solid var(--border);
	}
	h1 {
		font-size: var(--fs-20);
		font-weight: 600;
		letter-spacing: -0.015em;
		margin: 0 0 16px;
	}
	.map-shell {
		height: 48dvh;
		min-height: 280px;
		position: relative;
		overflow: hidden;
		border-radius: var(--radius-lg);
		border: 1px solid var(--border);
		background: var(--bg-elevated);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
	}
	.map {
		position: absolute;
		inset: 0;
	}
	.pin {
		position: absolute;
		left: 50%;
		top: 50%;
		z-index: 2;
		transform: translate(-50%, -50%);
		pointer-events: none;
		width: 20px;
		height: 20px;
		display: grid;
		place-items: center;
	}
	.pin-dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		background: var(--accent);
		border: 2px solid #fff;
		box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.35);
	}
	.zoom-controls {
		position: absolute;
		right: 12px;
		top: 12px;
		z-index: 3;
		display: grid;
		overflow: hidden;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-strong);
		background: var(--bg-raised);
	}
	.zoom-controls button {
		width: 36px;
		height: 36px;
		border: 0;
		background: transparent;
		color: var(--text-primary);
		font-size: var(--fs-20);
		font-weight: 500;
		cursor: pointer;
		transition: background var(--ease);
	}
	.zoom-controls button:hover {
		background: rgba(255, 255, 255, 0.04);
	}
	.zoom-controls button + button {
		border-top: 1px solid var(--border);
	}
	.map-loading {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		pointer-events: none;
		background: var(--bg-elevated);
		color: var(--text-secondary);
		font-size: var(--fs-14);
	}
	.map-load-error {
		z-index: 4;
		align-content: center;
		gap: 12px;
		padding: 24px;
		box-sizing: border-box;
		text-align: left;
		pointer-events: auto;
		justify-items: start;
	}
	.map-load-error button {
		border: 0;
		border-radius: var(--radius-md);
		padding: 10px 16px;
		background: var(--accent);
		color: #0a0a0a;
		font-weight: 500;
		font-size: var(--fs-14);
		cursor: pointer;
	}
	.list-title {
		margin: 16px 0 8px;
		font-size: var(--fs-12);
		font-weight: 500;
		color: var(--text-tertiary);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.options {
		display: grid;
		gap: 8px;
		padding-right: 2px;
	}
	.options button {
		display: grid;
		grid-template-columns: 20px minmax(0, 1fr);
		align-items: center;
		gap: 8px;
		width: 100%;
		background: var(--bg-surface);
		color: var(--text-primary);
		border: 1px solid var(--border);
		padding: 12px;
		text-align: left;
		border-radius: var(--radius-md);
		cursor: pointer;
		font: inherit;
		font-size: var(--fs-14);
		transition:
			background var(--ease),
			border-color var(--ease);
	}
	.options button:hover {
		background: var(--bg-elevated);
	}
	.options button.selected {
		border-color: var(--accent);
		background: var(--accent-muted);
	}
	.choice {
		display: grid;
		place-items: center;
		width: 20px;
		height: 20px;
		font-size: 12px;
		color: var(--text-tertiary);
	}
	.options button.selected .choice {
		color: var(--accent);
	}
	.address-label {
		min-width: 0;
		line-height: 1.35;
	}
	.selection-status {
		margin: 0 0 8px;
		line-height: 1.35;
		font-size: var(--fs-12);
		color: var(--text-secondary);
	}
	.selection-status b {
		font-weight: 600;
		color: var(--text-primary);
	}
	.hint-text {
		margin: 8px 0 12px;
		color: var(--text-tertiary);
		font-size: var(--fs-12);
	}
	.search-box {
		width: 100%;
	}
	input {
		box-sizing: border-box;
		width: 100%;
		min-width: 0;
		padding: 10px 12px;
		border-radius: var(--radius-md);
		border: 1px solid var(--border-strong);
		background: var(--bg-surface);
		color: var(--text-primary);
		font: inherit;
		font-size: var(--fs-16);
		transition: border-color var(--ease);
	}
	input:focus {
		outline: none;
		border-color: var(--accent);
		box-shadow: 0 0 0 2px var(--accent-muted);
	}
	input::placeholder {
		color: var(--text-tertiary);
	}
	.primary,
	.secondary {
		width: 100%;
		min-height: 40px;
		padding: 10px 16px;
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		margin-top: 8px;
		font: inherit;
		font-size: var(--fs-14);
		font-weight: 500;
		cursor: pointer;
		transition:
			background var(--ease),
			border-color var(--ease),
			opacity var(--ease);
	}
	.primary {
		background: var(--accent);
		color: #0a0a0a;
		border-color: var(--accent);
	}
	.primary:hover:not(:disabled) {
		background: var(--accent-hover);
	}
	.primary:disabled {
		opacity: 0.45;
		cursor: default;
	}
	.confirm-wrap {
		margin-top: 16px;
		padding-bottom: max(2px, env(safe-area-inset-bottom));
	}
	.confirm-wrap .primary {
		margin-top: 0;
	}
	.secondary {
		background: transparent;
		color: var(--text-primary);
		border-color: var(--border-strong);
	}
	.secondary:hover {
		background: var(--bg-elevated);
	}
	.done {
		display: grid;
		gap: 12px;
	}
	.done > b {
		font-size: var(--fs-16);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.done p {
		margin: 0;
		font-size: var(--fs-14);
		color: var(--text-secondary);
		line-height: 1.45;
	}
	.muted {
		color: var(--text-tertiary);
		font-size: var(--fs-14);
	}
	.error {
		color: var(--danger);
		font-size: var(--fs-14);
		margin-top: 12px;
	}
</style>

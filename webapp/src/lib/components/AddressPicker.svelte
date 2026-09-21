<script lang="ts">
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

	let { mode, targetChatId = null }: {
		mode: 'map' | 'text';
		targetChatId?: number | null;
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
	let activeMode: ChatLinkMode = $derived(buildChatLinkMode(mode, targetChatId));

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
		return `chat-link-picker-v6:${getMaxUserIdForStorage()}:${mode}:${targetChatId ?? 'resident'}`;
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
			const apiKey = import.meta.env.VITE_YANDEX_MAPS_API_KEY ?? '';
			const ymaps3 = await loadYandexMaps(apiKey);
			if (mapDisposed || !mapElement) return;

			yandexMap = new ymaps3.YMap(mapElement, {
				location: { center: [lon, lat], zoom: mapZoom },
				behaviors: ['drag', 'pinchZoom', 'scrollZoom', 'dblClick', 'oneFingerZoom'],
				theme: 'dark',
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
		error = '';
		searchSeq += 1;
		if (searchTimer !== null) window.clearTimeout(searchTimer);
		saveDraft();
		if (value.trim().length < 3) {
			loading = false;
			options = [];
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
			result = await selectAddress(selected.id, targetChatId);
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
			await navigator.clipboard.writeText(result.admin_link);
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
		clearDraft();
		saveActiveChatLinkMode(activeMode);
		if (mode === 'text') {
			query = '';
			return;
		}
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
				<div class="map" bind:this={mapElement}></div>
				<div class="pin" aria-hidden="true">＋</div>
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
						<span class="choice" aria-hidden="true">{selected?.id === item.id ? '✓' : '○'}</span>
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
				<p>✅ Домовой чат успешно привязан к этому адресу. Можно вернуться в групповой чат.</p>
			{:else if result.mode === 'existing_chat' && result.chats.length}
				<p>
					Для этого дома уже подключён чат соседей. Вступите по ссылке — после
					фактического вступления бот привяжет ваш профиль к дому.
				</p>
				{#each result.chats as chat}
					{#if chat.invite_link}
						<a class="primary link" href={chat.invite_link} target="_blank" rel="noreferrer">
							{chat.title}
						</a>
					{:else}
						<p class="muted">{chat.title}: попросите администратора прислать приглашение.</p>
					{/if}
				{/each}
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
						{linkCopied ? 'Ссылка скопирована' : 'Скопировать ссылку для администратора'}
					</button>
				{/if}
				<button class="secondary" type="button" onclick={() => (showAdminHelp = true)}>
					Я администратор чата
				</button>
			{/if}
			{#if result.mode !== 'group_connected'}
				<button class="secondary" type="button" onclick={startAnother}>Добавить ещё адрес</button>
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
		background: #0a1014;
		color: #eef3f6;
		padding: 18px 18px calc(28px + env(safe-area-inset-bottom));
		font-family: system-ui;
	}
	h1 { font-size: 22px; margin: 0 0 14px; }
	.map-shell {
		height: 52dvh;
		min-height: 330px;
		position: relative;
		overflow: hidden;
		border-radius: 18px;
		background: #202a30;
	}
	.map { position: absolute; inset: 0; }
	.pin {
		position: absolute;
		left: 50%;
		top: 50%;
		z-index: 2;
		transform: translate(-50%, -50%);
		pointer-events: none;
		font-size: 42px;
		color: #fff;
		text-shadow: 0 1px 4px #000, 0 0 8px #000;
	}
	.zoom-controls {
		position: absolute;
		right: 12px;
		top: 12px;
		z-index: 3;
		display: grid;
		overflow: hidden;
		border-radius: 12px;
		box-shadow: 0 3px 12px #0004;
	}
	.zoom-controls button {
		width: 42px;
		height: 42px;
		border: 0;
		background: #fff;
		color: #172027;
		font-size: 25px;
		font-weight: 500;
		cursor: pointer;
	}
	.zoom-controls button + button { border-top: 1px solid #dbe2e6; }
	.map-loading {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		pointer-events: none;
		background: #202a30;
		color: #aebbc3;
	}
	.map-load-error {
		z-index: 4;
		align-content: center;
		gap: 14px;
		padding: 24px;
		box-sizing: border-box;
		text-align: center;
		pointer-events: auto;
	}
	.map-load-error button {
		border: 0;
		border-radius: 10px;
		padding: 10px 18px;
		background: #168de2;
		color: #fff;
		font-weight: 600;
	}
	.list-title { margin: 14px 0 8px; font-weight: 700; }
	.options {
		display: grid;
		gap: 8px;
		padding-right: 2px;
	}
	.options button {
		display: grid;
		grid-template-columns: 24px minmax(0, 1fr);
		align-items: center;
		gap: 8px;
		width: 100%;
		background: #18242c;
		color: #fff;
		border: 1px solid #2b3c47;
		padding: 12px;
		text-align: left;
		border-radius: 12px;
		cursor: pointer;
	}
	.options button.selected {
		border: 2px solid #168de2;
		background: #142b3a;
		padding: 11px;
	}
	.choice { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; font-weight: 800; color: #52b7ff; }
	.address-label { min-width: 0; line-height: 1.3; }
	.selection-status { margin: 0 0 8px; line-height: 1.35; font-size: 13px; }
	.hint-text { margin: 8px 2px 0; color: #8fa0aa; font-size: 13px; }
	.search-box { width: 100%; }
	input {
		box-sizing: border-box;
		width: 100%;
		min-width: 0;
		padding: 15px 14px;
		border-radius: 12px;
		border: 1px solid #344;
		background: #172027;
		color: #fff;
		font-size: 16px;
	}
	.primary, .secondary { width: 100%; padding: 13px; border: 0; border-radius: 12px; margin-top: 10px; background: #168de2; color: #fff; font-weight: 600; }
	.primary:disabled { opacity: 0.45; }
	.confirm-wrap {
		margin-top: 14px;
		padding-bottom: max(2px, env(safe-area-inset-bottom));
	}
	.confirm-wrap .primary { margin-top: 0; }
	.link { display: block; box-sizing: border-box; text-align: center; text-decoration: none; }
	.secondary { background: #263740; }
	.done { display: grid; gap: 12px; }
	.muted { color: #aebbc3; }
	.error { color: #ff8d8d; }
</style>

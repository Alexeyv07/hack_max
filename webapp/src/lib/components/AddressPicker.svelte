<script lang="ts">
	import { onMount } from 'svelte';
	import {
		nearestAddresses,
		searchAddresses,
		selectAddress,
		type AddressOption,
		type SelectResult
	} from '$lib/api/chatLink';
	import { getMaxUserIdForStorage } from '$lib/maxUser';
	import { clearActiveChatLinkMode, saveActiveChatLinkMode } from '$lib/chatLinkSession';

	let { mode }: { mode: 'map' | 'text' } = $props();

	type PickerDraft = {
		version: 4;
		mode: 'map' | 'text';
		savedAt: number;
		query: string;
		lat: number;
		lon: number;
		selected: AddressOption | null;
	};

	const DRAFT_TTL_MS = 30 * 60 * 1000;

	let query = $state('');
	let options = $state<AddressOption[]>([]);
	let selected = $state<AddressOption | null>(null);
	let result = $state<SelectResult | null>(null);
	let error = $state('');
	let loading = $state(false);
	let searchTimer: number | null = null;
	let searchSeq = 0;

	let lat = $state(55.751244);
	let lon = $state(37.618423);
	const zoom = 16;
	let map: HTMLDivElement | undefined = $state();
	let dragStart: { x: number; y: number; lat: number; lon: number } | null = null;

	function storageKey() {
		return `chat-link-picker-v4:${getMaxUserIdForStorage()}:${mode}`;
	}

	function legacyStorageKeys() {
		const userId = getMaxUserIdForStorage();
		return [
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
				draft.version !== 4 ||
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
				version: 4,
				mode,
				savedAt: Date.now(),
				query,
				lat,
				lon,
				selected
			};
			localStorage.setItem(storageKey(), JSON.stringify(draft));
			saveActiveChatLinkMode(mode === 'map' ? 'chat_link_map' : 'chat_link_text');
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

	function world(latitude: number, longitude: number) {
		const scale = 256 * 2 ** zoom;
		const x = ((longitude + 180) / 360) * scale;
		const sin = Math.sin((latitude * Math.PI) / 180);
		const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale;
		return { x, y };
	}

	function coords(x: number, y: number) {
		const scale = 256 * 2 ** zoom;
		const longitude = (x / scale) * 360 - 180;
		const n = Math.PI - (2 * Math.PI * y) / scale;
		const latitude = (180 / Math.PI) * Math.atan(Math.sinh(n));
		return { lat: latitude, lon: longitude };
	}

	let tiles = $derived.by(() => {
		const center = world(lat, lon);
		const tileX = Math.floor(center.x / 256);
		const tileY = Math.floor(center.y / 256);
		const items = [];
		for (let dy = -2; dy <= 2; dy += 1) {
			for (let dx = -2; dx <= 2; dx += 1) {
				items.push({
					x: tileX + dx,
					y: tileY + dy,
					left: (tileX + dx) * 256 - center.x,
					top: (tileY + dy) * 256 - center.y
				});
			}
		}
		return items;
	});

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

	function pointerDown(event: PointerEvent) {
		if (!map) return;
		map.setPointerCapture(event.pointerId);
		dragStart = { x: event.clientX, y: event.clientY, lat, lon };
	}

	function pointerMove(event: PointerEvent) {
		if (!dragStart) return;
		const base = world(dragStart.lat, dragStart.lon);
		const center = coords(
			base.x - (event.clientX - dragStart.x),
			base.y - (event.clientY - dragStart.y)
		);
		lat = center.lat;
		lon = center.lon;
	}

	function pointerUp() {
		if (!dragStart) return;
		dragStart = null;
		saveDraft();
		void refreshNearest();
	}

	function locate() {
		if (!navigator.geolocation) {
			error = 'Геопозиция недоступна. Передвиньте карту вручную.';
			return;
		}
		navigator.geolocation.getCurrentPosition(
			(position) => {
				lat = position.coords.latitude;
				lon = position.coords.longitude;
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
			result = await selectAddress(selected.id);
			clearDraft();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : 'Ошибка выбора адреса';
		} finally {
			loading = false;
		}
	}

	function startAnother() {
		result = null;
		selected = null;
		options = [];
		error = '';
		clearDraft();
		if (mode === 'text') {
			query = '';
		} else {
			void refreshNearest();
		}
	}

	onMount(() => {
		saveActiveChatLinkMode(mode === 'map' ? 'chat_link_map' : 'chat_link_text');
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
			selected = draft.selected;
		}

		if (!result) {
			if (mode === 'map') {
				if (draft) {
					void refreshNearest({ preserveSelectedId: selected?.id });
				} else {
					locate();
				}
			} else if (query.trim().length >= 3) {
				void runSearch(query, { preserveSelectedId: selected?.id });
			}
		}

		return () => {
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
			<div
				class="map"
				role="application"
				aria-label="Карта выбора дома"
				bind:this={map}
				onpointerdown={pointerDown}
				onpointermove={pointerMove}
				onpointerup={pointerUp}
				onpointercancel={pointerUp}
			>
				{#each tiles as tile}
					<img
						src={`https://tile.openstreetmap.org/${zoom}/${tile.x}/${tile.y}.png`}
						alt=""
						draggable="false"
						style={`left:calc(50% + ${tile.left}px);top:calc(50% + ${tile.top}px)`}
					/>
				{/each}
				<div class="pin">＋</div>
				<a
					class="attribution"
					href="https://www.openstreetmap.org/copyright"
					target="_blank"
					rel="noreferrer">© OpenStreetMap</a
				>
			</div>
			<button class="secondary" type="button" onclick={locate}>Моя геопозиция</button>
		{:else}
			<div class="search-box">
				<input
					value={query}
					oninput={(event) => scheduleSearch(event.currentTarget.value)}
					placeholder="Например: сельск 15"
					autocomplete="street-address"
					inputmode="text"
				/>
			</div>
			<p class="hint-text">Подсказки появляются автоматически по мере ввода.</p>
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
			{#if result.mode === 'existing_chat' && result.chats.length}
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
			{:else}
				<p>
					Адрес выбран. Добавьте бота в групповой чат соседей и назначьте его
					администратором с правом «Читать все сообщения». После этого чат подключится
					автоматически — дополнительных команд не нужно.
				</p>
				{#if result.admin_link}
					<p>Если вы не администратор, перешлите админу эту ссылку:</p>
					<code>{result.admin_link}</code>
				{/if}
			{/if}
			<button class="secondary" type="button" onclick={startAnother}>Добавить ещё адрес</button>
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
	.map { height: 52dvh; min-height: 330px; position: relative; overflow: hidden; border-radius: 18px; background: #202a30; touch-action: none; }
	.map img { position: absolute; width: 256px; height: 256px; user-select: none; }
	.pin { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); font-size: 42px; color: #168de2; text-shadow: 0 1px 3px #fff; }
	.attribution { position: absolute; right: 6px; bottom: 5px; background: #fffc; color: #234; padding: 2px 5px; border-radius: 5px; font-size: 10px; text-decoration: none; }
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
	.done code { white-space: normal; word-break: break-all; background: #172027; padding: 12px; border-radius: 10px; }
	.muted { color: #aebbc3; }
	.error { color: #ff8d8d; }
</style>

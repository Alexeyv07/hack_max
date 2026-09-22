/** MAX Bridge: user id и start_param из мини-приложения. */

export type MaxWebApp = {
	initData?: string;
	initDataUnsafe?: {
		user?: {
			id?: number;
		};
		start_param?: string;
	};
	ready?: () => void;
};

declare global {
	interface Window {
		WebApp?: MaxWebApp;
	}
}

/** Локальная разработка без Max Bridge (`npm run dev` на localhost). */
export const LOCAL_DEV_USER_ID = 159064979;

export function readyMaxWebApp(): void {
	try {
		window.WebApp?.ready?.();
	} catch {
		// Вне MAX Bridge ready может отсутствовать.
	}
}

const USER_ID_CACHE_KEY = 'max-webapp-user-id-v1';

function isLocalDevHost(): boolean {
	try {
		const host = window.location.hostname;
		return host === 'localhost' || host === '127.0.0.1' || host === '[::1]';
	} catch {
		return false;
	}
}

function parseInitData(raw: string | undefined): URLSearchParams | null {
	if (!raw) return null;
	try {
		return new URLSearchParams(raw);
	} catch {
		return null;
	}
}

function initDataFromHash(): URLSearchParams | null {
	try {
		const hash = window.location.hash.replace(/^#/, '');
		if (!hash) return null;
		const outer = new URLSearchParams(hash);
		const webAppData = outer.get('WebAppData');
		return parseInitData(webAppData ?? undefined);
	} catch {
		return null;
	}
}

function userIdFromParams(params: URLSearchParams | null): number | null {
	if (!params) return null;
	const rawUser = params.get('user');
	if (!rawUser) return null;
	try {
		const user = JSON.parse(rawUser) as { id?: unknown };
		const id = user.id;
		if (typeof id !== 'number' || !Number.isFinite(id) || id <= 0) return null;
		return Math.trunc(id);
	} catch {
		return null;
	}
}

function normalizeUserId(id: unknown): number | null {
	if (typeof id !== 'number' || !Number.isFinite(id) || id <= 0) return null;
	return Math.trunc(id);
}

function cacheUserId(id: number): number {
	try {
		localStorage.setItem(USER_ID_CACHE_KEY, String(id));
	} catch {
		// WebView может запрещать storage.
	}
	return id;
}

export function getMaxUserId(): number | null {
	// Браузер на localhost: всегда фейковый user (не из Bridge / WebApp).
	if (isLocalDevHost()) {
		return cacheUserId(LOCAL_DEV_USER_ID);
	}

	const unsafeId = normalizeUserId(window.WebApp?.initDataUnsafe?.user?.id);
	if (unsafeId !== null) return cacheUserId(unsafeId);

	const initDataId = userIdFromParams(parseInitData(window.WebApp?.initData));
	if (initDataId !== null) return cacheUserId(initDataId);

	// MAX также передаёт тот же WebAppData во fragment URL. Это спасает reload WebView,
	// когда глобальный объект Bridge появляется позже стартового рендера.
	const hashId = userIdFromParams(initDataFromHash());
	if (hashId !== null) return cacheUserId(hashId);

	return null;
}

export function getMaxUserIdForStorage(): string {
	const live = getMaxUserId();
	if (live !== null) return String(live);
	try {
		return localStorage.getItem(USER_ID_CACHE_KEY) ?? 'unknown';
	} catch {
		return 'unknown';
	}
}

/** ID пользователя MAX из стартовых данных Mini App. */
export function requireMaxUserId(): number {
	const id = getMaxUserId();
	if (id === null) {
		throw new Error(
			'MAX не передал данные пользователя. Закройте мини-приложение и откройте его заново из кнопки бота.'
		);
	}
	return id;
}

export async function waitForMaxUserId(timeoutMs = 6000): Promise<number> {
	const immediate = getMaxUserId();
	if (immediate !== null) return immediate;

	const started = Date.now();
	while (Date.now() - started < timeoutMs) {
		await new Promise((resolve) => window.setTimeout(resolve, 50));
		const id = getMaxUserId();
		if (id !== null) return id;
	}
	return requireMaxUserId();
}

export function getMaxStartParam(): string | null {
	const unsafe = window.WebApp?.initDataUnsafe?.start_param;
	if (unsafe) return unsafe;

	const fromInitData = parseInitData(window.WebApp?.initData)?.get('start_param');
	if (fromInitData) return fromInitData;

	const fromHash = initDataFromHash()?.get('start_param');
	if (fromHash) return fromHash;

	try {
		return new URL(window.location.href).searchParams.get('WebAppStartParam');
	} catch {
		return null;
	}
}

/**
 * Bridge иногда заполняет стартовые данные уже после первого рендера WebApp.
 * Коротко ждём payload, чтобы onboarding не мигал обычной лентой новостей.
 */
function hasMaxLaunchData(): boolean {
	if (window.WebApp?.initDataUnsafe?.user?.id || window.WebApp?.initData) return true;
	try {
		const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
		return hash.has('WebAppData');
	} catch {
		return false;
	}
}

export async function waitForMaxStartParam(timeoutMs = 6000): Promise<string | null> {
	const immediate = getMaxStartParam();
	if (immediate !== null) return immediate;
	if (hasMaxLaunchData()) return null;

	const started = Date.now();
	while (Date.now() - started < timeoutMs) {
		await new Promise((resolve) => window.setTimeout(resolve, 50));
		const value = getMaxStartParam();
		if (value !== null) return value;
		if (hasMaxLaunchData()) return null;
	}
	return null;
}

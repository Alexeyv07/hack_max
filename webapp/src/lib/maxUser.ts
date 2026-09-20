/** Max Bridge: user id из мини-приложения. */

export type MaxWebApp = {
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

export function readyMaxWebApp(): void {
	try {
		window.WebApp?.ready?.();
	} catch {
		// вне Max Bridge ready может отсутствовать
	}
}

const USER_ID_CACHE_KEY = 'max-webapp-user-id-v1';

export function getMaxUserId(): number | null {
	const id = window.WebApp?.initDataUnsafe?.user?.id;
	if (typeof id !== 'number' || !Number.isFinite(id) || id <= 0) return null;
	const normalized = Math.trunc(id);
	try {
		localStorage.setItem(USER_ID_CACHE_KEY, String(normalized));
	} catch {
		// WebView может запрещать storage; Bridge всё равно остаётся источником identity.
	}
	return normalized;
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

/** ID пользователя Max из Bridge. Без Bridge — ошибка (локальный браузер без Max). */
export function requireMaxUserId(): number {
	const id = getMaxUserId();
	if (id === null) {
		throw new Error(
			'Нет user id Max. Откройте мини-приложение из бота Max (Bridge initDataUnsafe.user.id).'
		);
	}
	return id;
}

export async function waitForMaxUserId(timeoutMs = 4000): Promise<number> {
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
	return window.WebApp?.initDataUnsafe?.start_param ?? null;
}

/**
 * Bridge иногда заполняет initDataUnsafe уже после первого рендера WebApp.
 * Коротко ждём payload, чтобы onboarding не мигал обычной лентой новостей.
 */
export async function waitForMaxStartParam(timeoutMs = 4000): Promise<string | null> {
	const readWhenBridgeIsReady = (): string | null | undefined => {
		const userId = getMaxUserId();
		if (userId === null) return undefined;
		return window.WebApp?.initDataUnsafe?.start_param ?? null;
	};

	const immediate = readWhenBridgeIsReady();
	if (immediate !== undefined) return immediate;

	const started = Date.now();
	while (Date.now() - started < timeoutMs) {
		await new Promise((resolve) => window.setTimeout(resolve, 50));
		const value = readWhenBridgeIsReady();
		if (value !== undefined) return value;
	}
	return null;
}

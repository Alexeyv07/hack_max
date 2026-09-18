/** Max Bridge: user id из мини-приложения. */

export type MaxWebApp = {
	initDataUnsafe?: {
		user?: {
			id?: number;
		};
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

/** ID пользователя Max из Bridge. Без Bridge — ошибка (локальный браузер без Max). */
export function requireMaxUserId(): number {
	const id = window.WebApp?.initDataUnsafe?.user?.id;
	if (typeof id !== 'number' || !Number.isFinite(id) || id <= 0) {
		throw new Error(
			'Нет user id Max. Откройте мини-приложение из бота Max (Bridge initDataUnsafe.user.id).'
		);
	}
	return Math.trunc(id);
}

/** Обучение жестам ленты: счётчики в localStorage. */

const KEY_DOWN = 'hack_max_hint_down_seen';
const KEY_CITY = 'hack_max_hint_city_seen';

const DOWN_MAX = 3;

function readInt(key: string): number {
	if (typeof localStorage === 'undefined') return DOWN_MAX;
	const raw = localStorage.getItem(key);
	const n = Number(raw);
	return Number.isFinite(n) && n >= 0 ? n : 0;
}

/** Показывать «свайп вниз», пока не было 3 свайпов вниз. */
export function shouldShowDownHint(): boolean {
	return readInt(KEY_DOWN) < DOWN_MAX;
}

/** Засчитать один свайп вниз (после 3-го подсказка больше не показывается). */
export function recordDownSwipe(): void {
	if (typeof localStorage === 'undefined') return;
	const n = readInt(KEY_DOWN);
	if (n >= DOWN_MAX) return;
	localStorage.setItem(KEY_DOWN, String(n + 1));
}

/** Показывать «свайп вправо» (на город), пока пользователь ни разу не перешёл в city. */
export function shouldShowCityHint(): boolean {
	if (typeof localStorage === 'undefined') return false;
	return localStorage.getItem(KEY_CITY) !== '1';
}

/** Отметить, что пользователь уже открывал ленту города. */
export function recordCitySwitch(): void {
	if (typeof localStorage === 'undefined') return;
	localStorage.setItem(KEY_CITY, '1');
}

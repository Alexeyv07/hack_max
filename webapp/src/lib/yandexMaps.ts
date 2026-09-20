export type YandexLocation = {
	center: [number, number];
	zoom?: number;
};

export type YandexMapInstance = {
	addChild(child: unknown): YandexMapInstance;
	update(props: {
		location?: {
			center?: [number, number];
			zoom?: number;
			duration?: number;
		};
	}): void;
	destroy(): void;
};

type YandexMapsApi = {
	ready: Promise<void>;
	YMap: new (
	container: HTMLElement,
	props: {
		location: { center: [number, number]; zoom: number };
		behaviors?: string[];
		theme?: 'light' | 'dark';
		distributionPosition?: 'top left' | 'top right' | 'bottom left' | 'bottom right';
		copyrightsPosition?: 'top left' | 'top right' | 'bottom left' | 'bottom right';
	}
) => YandexMapInstance;
	YMapDefaultSchemeLayer: new (props?: Record<string, unknown>) => unknown;
	YMapListener: new (props: {
		onUpdate?: (event: { location: YandexLocation }) => void;
		onActionEnd?: (event: { location: YandexLocation }) => void;
	}) => unknown;
};

declare global {
	interface Window {
		ymaps3?: YandexMapsApi;
	}
}

let loading: Promise<YandexMapsApi> | null = null;

function loadErrorMessage() {
	const host = window.location.hostname || 'домен miniapp';
	return (
		`Не удалось загрузить Yandex Maps API. Проверьте, что в ограничении HTTP Referer ` +
		`для ключа разрешён домен «${host}» и после изменения ключа прошло до 15 минут.`
	);
}

export function loadYandexMaps(apiKey: string): Promise<YandexMapsApi> {
	const key = apiKey.trim();
	if (!key) {
		return Promise.reject(new Error('Не задан ключ Yandex Maps API.'));
	}
	if (window.ymaps3) {
		return window.ymaps3.ready.then(() => window.ymaps3 as YandexMapsApi);
	}
	if (loading) return loading;

	loading = new Promise<YandexMapsApi>((resolve, reject) => {
		const existing = document.querySelector<HTMLScriptElement>('script[data-yandex-maps-api]');
		const script = existing ?? document.createElement('script');
		let timeoutId: number | null = null;

		const cleanup = () => {
			if (timeoutId !== null) window.clearTimeout(timeoutId);
		};
		const fail = (cause: unknown) => {
			cleanup();
			loading = null;
			script.remove();
			reject(cause);
		};

		const finish = async () => {
			try {
				if (!window.ymaps3) throw new Error(loadErrorMessage());
				await window.ymaps3.ready;
				cleanup();
				resolve(window.ymaps3);
			} catch (cause) {
				fail(cause);
			}
		};

		script.addEventListener('load', () => void finish(), { once: true });
		script.addEventListener('error', () => fail(new Error(loadErrorMessage())), { once: true });

		if (!existing) {
			script.dataset.yandexMapsApi = '1';
			script.async = true;
			// В WebView явно просим браузер передавать origin страницы как Referer.
			script.referrerPolicy = 'origin';
			script.src = `https://api-maps.yandex.ru/v3/?apikey=${encodeURIComponent(key)}&lang=ru_RU`;
			document.head.appendChild(script);
		}

		timeoutId = window.setTimeout(
			() => fail(new Error(`${loadErrorMessage()} Загрузка превысила 15 секунд.`)),
			15_000
		);

		if (window.ymaps3) void finish();
	});

	return loading;
}

export type ChatLinkMode = 'chat_link_map' | 'chat_link_text';

const ACTIVE_MODE_KEY = 'chat-link-active-mode-v1';
const ACTIVE_MODE_TTL_MS = 30 * 60 * 1000;

type StoredMode = {
	mode: ChatLinkMode;
	savedAt: number;
};

export function isChatLinkMode(value: string | null): value is ChatLinkMode {
	return value === 'chat_link_map' || value === 'chat_link_text';
}

export function loadActiveChatLinkMode(): ChatLinkMode | null {
	try {
		const raw = localStorage.getItem(ACTIVE_MODE_KEY);
		if (!raw) return null;
		const stored = JSON.parse(raw) as StoredMode;
		if (!isChatLinkMode(stored.mode) || Date.now() - stored.savedAt > ACTIVE_MODE_TTL_MS) {
			localStorage.removeItem(ACTIVE_MODE_KEY);
			return null;
		}
		return stored.mode;
	} catch {
		return null;
	}
}

export function saveActiveChatLinkMode(mode: ChatLinkMode): void {
	try {
		localStorage.setItem(ACTIVE_MODE_KEY, JSON.stringify({ mode, savedAt: Date.now() }));
	} catch {
		// WebView может запрещать storage; flow продолжит работать без восстановления.
	}
}

export function clearActiveChatLinkMode(): void {
	try {
		localStorage.removeItem(ACTIVE_MODE_KEY);
	} catch {
		// WebView может запрещать storage.
	}
}
